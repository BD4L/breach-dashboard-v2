-- Private staff alerts only. Apply explicitly in the chosen Supabase project.
-- No changes to existing tables, user accounts, or public collection state.
begin;

create table if not exists public.breach_alert_subscriptions (
  id uuid primary key default gen_random_uuid(),
  email text not null check (position('@' in email) > 1 and email = btrim(email) and email !~ E'[\r\n]'),
  enabled boolean not null default false,
  verified_at timestamptz,
  activated_at timestamptz not null default now()
);
create unique index if not exists breach_alert_one_active_address
  on public.breach_alert_subscriptions (lower(email)) where enabled;

create table if not exists public.breach_alert_outbox (
  id uuid primary key default gen_random_uuid(),
  subscription_id uuid not null references public.breach_alert_subscriptions(id),
  event_key text not null check (event_key ~ '^[a-f0-9]{64}$'),
  observed_at timestamptz not null,
  source_date date not null,
  expires_at timestamptz not null,
  payload jsonb not null,
  state text not null default 'queued' check (state in ('queued', 'sending', 'retry', 'sent', 'held')),
  attempts integer not null default 0,
  first_attempt_at timestamptz,
  next_attempt_at timestamptz not null default now(),
  lease_until timestamptz,
  lease_token uuid,
  provider_id text,
  error_code text,
  sent_at timestamptz,
  unique (subscription_id, event_key)
);
create index if not exists breach_alert_due on public.breach_alert_outbox (state, next_attempt_at);

alter table public.breach_alert_subscriptions enable row level security;
alter table public.breach_alert_outbox enable row level security;
revoke all on public.breach_alert_subscriptions, public.breach_alert_outbox from public, anon, authenticated;
grant select, insert, update on public.breach_alert_subscriptions, public.breach_alert_outbox to service_role;

create or replace function public.breach_alert_enqueue(p_events jsonb, p_sender text, p_recent_days integer)
returns integer language plpgsql security definer set search_path = pg_catalog, public as $$
declare inserted integer;
begin
  if jsonb_typeof(p_events) <> 'array' or jsonb_array_length(p_events) > 100
      or p_recent_days not between 1 and 30 or position('@' in p_sender) < 2
      or p_sender ~ E'[\r\n]' then
    raise exception 'Invalid alert batch';
  end if;
  insert into public.breach_alert_outbox
    (subscription_id, event_key, observed_at, source_date, expires_at, payload)
  select s.id, e->>'event_key', (e->>'observed_at')::timestamptz, (e->>'source_date')::date,
    ((e->>'source_date')::date + p_recent_days + 1)::timestamp at time zone 'UTC',
    jsonb_build_object('from', p_sender, 'to', jsonb_build_array(s.email),
      'subject', e->>'subject', 'text', e->>'text', 'html', e->>'html')
  from public.breach_alert_subscriptions s cross join jsonb_array_elements(p_events) e
  where s.enabled and s.verified_at is not null
    and (e->>'observed_at')::timestamptz >= s.activated_at
    and (e->>'observed_at')::timestamptz <= now()
    and (e->>'source_date')::date between (now() at time zone 'UTC')::date - p_recent_days
                                          and (now() at time zone 'UTC')::date
    and length(e->>'subject') between 1 and 300
    and length(e->>'text') between 1 and 10000
    and length(e->>'html') between 1 and 20000
  on conflict (subscription_id, event_key) do nothing;
  get diagnostics inserted = row_count;
  return inserted;
end $$;

create or replace function public.breach_alert_claim()
returns table(id uuid, lease_token uuid, payload jsonb)
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  -- A timed-out send may already have been accepted. Stop before provider keys expire.
  update public.breach_alert_outbox o set state = 'held', error_code = 'retry_window_expired'
  where o.state in ('queued', 'retry', 'sending') and (o.lease_until is null or o.lease_until <= now())
    and (o.expires_at <= now() or o.first_attempt_at <= now() - interval '23 hours');
  update public.breach_alert_outbox o set state = 'held', error_code = 'recipient_changed'
  from public.breach_alert_subscriptions s
  where o.subscription_id = s.id and o.state in ('queued', 'retry', 'sending')
    and (o.lease_until is null or o.lease_until <= now()) and o.payload->'to'->>0 <> s.email;
  return query
  with candidate as (
    select o.id from public.breach_alert_outbox o join public.breach_alert_subscriptions s on s.id = o.subscription_id
    where s.enabled and s.verified_at is not null and o.observed_at >= s.activated_at
      and o.state in ('queued', 'retry', 'sending') and o.next_attempt_at <= now()
      and (o.lease_until is null or o.lease_until <= now())
    order by o.observed_at, o.id for update of o skip locked limit 1
  )
  update public.breach_alert_outbox o set state = 'sending', attempts = o.attempts + 1,
    first_attempt_at = coalesce(o.first_attempt_at, now()), lease_until = now() + interval '5 minutes',
    lease_token = gen_random_uuid()
  from candidate c where o.id = c.id returning o.id, o.lease_token, o.payload;
end $$;

create or replace function public.breach_alert_finish(p_id uuid, p_lease_token uuid, p_state text,
                                                      p_provider_id text, p_error_code text)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if p_state not in ('sent', 'retry', 'held') or (p_state = 'sent' and coalesce(p_provider_id, '') = '') then
    raise exception 'Invalid alert acknowledgement';
  end if;
  update public.breach_alert_outbox o set state = p_state, provider_id = p_provider_id,
    error_code = left(p_error_code, 100), sent_at = case when p_state = 'sent' then now() else null end,
    next_attempt_at = now() + make_interval(secs => least(3600, 60 * greatest(o.attempts, 1))),
    lease_until = null, lease_token = null
  where o.id = p_id and o.state = 'sending' and o.lease_token = p_lease_token;
  if not found then raise exception 'Alert lease no longer owned'; end if;
  return true;
end $$;

create or replace function public.breach_alert_health()
returns jsonb language sql security definer set search_path = pg_catalog, public as $$
  select jsonb_build_object('pending', count(*) filter (where o.state in ('queued', 'sending', 'retry')),
                            'held', count(*) filter (where o.state = 'held'))
  from public.breach_alert_outbox o join public.breach_alert_subscriptions s on s.id = o.subscription_id
  where s.enabled and s.verified_at is not null;
$$;

revoke all on function public.breach_alert_enqueue(jsonb, text, integer), public.breach_alert_claim(),
  public.breach_alert_finish(uuid, uuid, text, text, text), public.breach_alert_health() from public, anon, authenticated;
grant execute on function public.breach_alert_enqueue(jsonb, text, integer), public.breach_alert_claim(),
  public.breach_alert_finish(uuid, uuid, text, text, text), public.breach_alert_health() to service_role;
commit;
