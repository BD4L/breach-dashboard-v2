# Staff email alerts

The alert worker reads the full public snapshot and keeps subscriptions, recipient
addresses, frozen email payloads, delivery IDs, leases and retry history in
**private Supabase tables**. None belongs in the public repository, collection-state
branch, Pages snapshot, workflow artifacts or logs. Scrapers do not depend on email
delivery. No SQL, subscriptions or delivery credentials are installed by this code.

## Preview

```sh
python -m ingestion.alerts --snapshot state/dashboard.json
```

This default mode is offline: no credentials, database calls or email requests.
It shows a candidate count and up to 20 public message previews. `--since` accepts
an aware ISO observation timestamp; `--recent-days` defaults to seven, maximum 30.
The input must be the full schema-1 live snapshot, not the 200-record bootstrap.

Only source publication/reported dates within that window qualify. Ransomware
claims use `sourceObservedAt` and are explicitly described as unverified, with
RansomLook attribution and its CC BY 4.0 license. Incident dates and `lastSeen`
never make an old report new. The latest creation or material before/after change
in the exported history supplies the event identity. Later technical changes do
not hide it or create another alert. The public export retains 20 revisions;
material events older than that suffix cannot be reconstructed by this worker.
Undated reports remain available on the dashboard but do not enter automatic staff
alerts. Malformed history or claim classification stops delivery.

## Explicit configuration

1. Review and apply [alerts.sql](alerts.sql) in the chosen private Supabase project.
   It creates only `breach_alert_*` tables/functions. RLS is enabled; public,
   anonymous and authenticated roles receive no access. The worker uses the service
   role and must never run in the browser.
2. Staff create a subscription after confirming the authorized address, set
   `verified_at`, and enable it. Leave `activated_at` at its current-time default.
   No observation before that activation can be queued. First setup therefore
   cannot email the existing archive. Backfilled old source dates are also excluded.
   Disable a subscription to pause pending delivery. To change its recipient,
   disable it and create a new subscription with a fresh activation time.
3. Configure `RESEND_API_KEY`, `ALERT_FROM_EMAIL`, `SUPABASE_URL` and
   `SUPABASE_SERVICE_KEY` as private Actions secrets. Confirm the sender domain is
   authorized with Resend and the recipients are permitted. There is no default
   sender, hardcoded recipient or automatic fake verification.
   Before enabling successor subscriptions, explicitly retire the original email
   notification path; its separate ledger cannot deduplicate this worker's sends.
   The original scraping jobs can remain independent.
4. Set repository variable `ALERTS_ENABLED=true` after private setup and original
   notification cutover are complete. Optionally set `ALERT_DELIVERY_LIMIT`
   (default 25; accepted range 1–100). The separate `Deliver staff breach alerts`
   workflow runs after `Collect public sources and publish` and
   `Publish preserved public history` complete, or through manual dispatch.
   It has its own serialized concurrency group and read-only repository permission.
   It always checks out trusted `main`; private credentials are present only in
   the delivery step, never in collection jobs or downloaded artifacts.

For a configured local invocation, fetch the published snapshot and deliver in
separate commands:

```sh
python -m ingestion.alerts --fetch-published /tmp/alerts-snapshot.json
python -m ingestion.alerts --snapshot /tmp/alerts-snapshot.json --deliver --limit 25
```

The downloader reads only the fixed HTTPS Pages `data/dashboard.json` endpoint.
It rejects redirects, oversized responses, demo/partial snapshots, snapshots older
than two hours and timestamps more than two minutes in the future. Delivery checks
freshness again before private storage access. An upstream run can publish useful
partial results and then fail its source-health check, so alerts use fresh published
data without requiring overall workflow success. Re-reading the same recent
snapshot cannot create duplicate outbox rows. Pending deliveries are also drained
when that snapshot has no new candidates. Collection and publication continue
independently when alerts fail.

## Delivery guarantees and recovery

The private outbox has one row per subscription and source/report/revision key.
Insertion is idempotent; workers claim one row using a durable lease and
`SKIP LOCKED`. The original recipient, sender and content remain frozen on retries.
Resend receives the same opaque `Idempotency-Key` for every attempt at that row.
Successful provider acceptance is recorded before processing the next message;
acceptance is not proof of inbox delivery.

Resend retains keys for **24 hours**. Retries and abandoned leases are held for
staff reconciliation after 23 hours from the first attempt, or when the source
date expires. An ambiguous old request is never blindly sent again. Staff must
reconcile held records with provider delivery history before any manual recovery.
There is no unconditional exactly-once guarantee across unlimited outages.
[Resend idempotency documentation](https://resend.com/docs/dashboard/emails/idempotency-keys).

Requests have connection/read deadlines, response-size limits and no redirects.
Storage failures stop sending; provider errors are sanitized to error codes.
Permanent provider errors are held; transient failures are retried with delay.
The command exits nonzero for failed sends or held records. Logs contain delivery
counts, never recipient addresses, payloads, API responses or keys.

Resend's free transactional allowance is currently 100 emails/day and 3,000/month;
each recipient consumes quota. Default API rate is five requests/second per team.
Configure invocation limits and scheduling for the actual staff list, and respect
provider quota failures. No plan upgrade is performed.
[Resend limits](https://resend.com/docs/knowledge-base/account-quotas-and-limits).

## Verification boundary

Offline tests cover date/activation selection, amendments, claim labeling, HTML
escaping, bounded public downloads, snapshot freshness, explicit API authentication,
offline previews, fail-closed storage handling, retry idempotency, private logging
and nonzero failures. SQL is supplied for review; no production SQL or
provider request is executed by those tests. Private schema deployment, sender
authorization and actual delivery require separate configured verification.
