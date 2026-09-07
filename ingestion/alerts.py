"""Offline alert previews and an explicit private Resend/Supabase delivery worker."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit
from uuid import UUID

from requests.auth import AuthBase

from .store import MAX_EXPORTED_HISTORY
from .validation import safe_url, timestamp, utc_now

MAX_SNAPSHOT_BYTES = 50_000_000
MAX_REPLY_BYTES = 1_000_000
REQUEST_TIMEOUT = (5, 20)
PUBLIC_SNAPSHOT_URL = 'https://bd4l.github.io/breach-dashboard-v2/data/dashboard.json'
MAX_SNAPSHOT_AGE = timedelta(hours=2)
CLOCK_SKEW = timedelta(minutes=2)
MATERIAL_FIELDS = {'organization', 'sourceUrl', 'noticeUrl', 'publishedDate', 'reportedDate',
                   'breachStart', 'breachEnd', 'discoveryDate', 'affected', 'dataTypes',
                   'summary', 'signalType', 'sourceObservedAt'}
ATTRIBUTION = ('RansomLook (https://www.ransomlook.io/), CC BY 4.0 '
               '(https://creativecommons.org/licenses/by/4.0/). '
               'Metadata normalized; claims are not independently verified.')


class AlertError(RuntimeError):
    """A sanitized operational error; never include provider bodies or recipients."""


class ProviderError(AlertError):
    def __init__(self, code, *, retry=True):
        super().__init__(code)
        self.retry = retry


class HeaderAuthorization(AuthBase):
    """Prevent implicit netrc credentials while preserving our explicit API header."""
    def __call__(self, request):
        return request


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Expected UTC observation timestamp')
    return utc_now(datetime.fromisoformat(value.replace('Z', '+00:00')))


def validate_published_snapshot(snapshot, *, now=None):
    now = utc_now(now)
    if (not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 1
            or snapshot.get('mode') != 'live' or not isinstance(snapshot.get('reports'), list)
            or not isinstance(snapshot.get('sources'), list)):
        raise AlertError('invalid_public_snapshot')
    try:
        age = now - instant(snapshot.get('generatedAt'))
    except (TypeError, ValueError):
        raise AlertError('invalid_public_snapshot_timestamp') from None
    if age > MAX_SNAPSHOT_AGE or age < -CLOCK_SKEW:
        raise AlertError('public_snapshot_not_fresh')


def fetch_published_snapshot(output, *, session=None, now=None):
    """Fetch only the fixed public Pages snapshot; never send private credentials."""
    import requests
    from .network import PublicOnlyAuth
    session = session or requests.Session()
    started = time.monotonic()
    try:
        with session.get(PUBLIC_SNAPSHOT_URL, timeout=REQUEST_TIMEOUT, allow_redirects=False,
                         stream=True, auth=PublicOnlyAuth(), headers={'Cache-Control': 'no-cache'}) as response:
            if response.status_code != 200:
                raise AlertError('public_snapshot_request_failed')
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_SNAPSHOT_BYTES or time.monotonic() - started > 90:
                    raise AlertError('public_snapshot_budget_exceeded')
        snapshot = json.loads(body)
    except (requests.RequestException, ValueError):
        raise AlertError('public_snapshot_download_failed') from None
    validate_published_snapshot(snapshot, now=now)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return snapshot


def source_date(report):
    if report.get('signalType') == 'ransomware_claim':
        try:
            return instant(report.get('sourceObservedAt')).date()
        except ValueError:
            return None
    for key in ('publishedDate', 'reportedDate'):
        value = report.get(key)
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
    return None


def text_value(value, limit=1200):
    return ' '.join(str(value or '').split())[:limit]


def latest_material_revision(report, generated):
    """Select from the export's contiguous revision suffix, without inventing history."""
    revision = report['revision']
    first_seen, last_changed = instant(report.get('firstSeen')), instant(report.get('lastChanged'))
    history = report.get('history')
    if (not first_seen <= last_changed <= generated or not isinstance(history, list)
            or len(history) != min(revision, MAX_EXPORTED_HISTORY)):
        raise ValueError('Malformed report history')
    selected, previous = None, last_changed
    for index, entry in enumerate(history):
        if not isinstance(entry, dict):
            raise ValueError('Malformed report history entry')
        observed = instant(entry.get('observedAt'))
        fields, changes = entry.get('changedFields'), entry.get('changes')
        event_revision = revision - index
        if (not first_seen <= observed <= previous or (index == 0 and observed != last_changed)
                or not isinstance(fields, list) or any(not isinstance(field, str) for field in fields)
                or not isinstance(changes, list)):
            raise ValueError('Malformed report history entry')
        if event_revision == 1:
            if fields != ['created'] or changes or observed != first_seen:
                raise ValueError('Malformed creation history')
            material = True
        else:
            if ('created' in fields or any(not isinstance(change, dict) or not isinstance(change.get('field'), str)
                    or 'before' not in change or 'after' not in change for change in changes)
                    or [change['field'] for change in changes] != fields):
                raise ValueError('Malformed change history')
            material = any(change['field'].split('.')[0] in MATERIAL_FIELDS
                           and change['before'] != change['after'] for change in changes)
        if selected is None and material:
            selected = event_revision, observed
        previous = observed
    return selected


def events_for_snapshot(snapshot, *, now=None, since=None, recent_days=7):
    """Use immutable report revisions, never collection lastSeen or incident date."""
    now = utc_now(now)
    if type(recent_days) is not int or not 1 <= recent_days <= 30:
        raise ValueError('recent_days must be between 1 and 30')
    if (not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 1
            or snapshot.get('mode') != 'live' or not isinstance(snapshot.get('reports'), list)
            or not isinstance(snapshot.get('sources'), list)):
        raise ValueError('Expected full live snapshot schema 1')
    generated = instant(snapshot.get('generatedAt'))
    if generated > now + CLOCK_SKEW:
        raise ValueError('Snapshot timestamp is in the future')
    if any(not isinstance(source, dict) or not isinstance(source.get('id'), str) for source in snapshot['sources']):
        raise ValueError('Malformed source catalog')
    sources = {source['id']: source for source in snapshot['sources']}
    if len(sources) != len(snapshot['sources']):
        raise ValueError('Duplicate source catalog identity')
    cutoff = now.date() - timedelta(days=recent_days)
    events, identities = [], set()
    for report in snapshot['reports']:
        if not isinstance(report, dict):
            raise ValueError('Malformed report')
        identifier, source_id, revision = report.get('id'), report.get('sourceId'), report.get('revision')
        if (not isinstance(identifier, str) or not isinstance(source_id, str) or source_id not in sources
                or not identifier.startswith(source_id + ':')
                or type(revision) is not int or revision < 1 or identifier in identities):
            raise ValueError('Malformed or duplicate report identity')
        identities.add(identifier)
        first_seen = instant(report.get('firstSeen'))
        signal = report.get('signalType')
        if signal not in (None, 'ransomware_claim') or (source_id == 'ransomlook') != (signal == 'ransomware_claim'):
            raise ValueError('Invalid source signal classification')
        claimed = signal == 'ransomware_claim'
        if claimed and instant(report.get('sourceObservedAt')) > generated:
            raise ValueError('Invalid claim observation timestamp')
        material = latest_material_revision(report, generated)
        if material is None:
            continue
        event_revision, observed = material
        dated = source_date(report)
        if dated is None or not cutoff <= dated <= now.date() or (since and observed < since):
            continue
        label = 'Unverified ransomware claim' if claimed else 'Official breach notice'
        status = 'Updated' if event_revision > 1 else 'New'
        organization = text_value(report.get('organization'), 180)
        if not organization or not safe_url(report.get('sourceUrl')):
            raise ValueError('Report needs organization and a safe source link')
        subject = f'{status} {label.lower()}: {organization}'
        lines = [f'{status} {label.lower()}', organization,
                 f'Source: {text_value(sources[source_id].get("label", source_id), 180)}',
                 f'{"Claim observed by source" if claimed else "Source publication/report date"}: {dated}',
                 f'Dashboard first observed: {timestamp(first_seen)}', f'Revision: {event_revision}']
        affected = report.get('affected') or {}
        if affected.get('count') is not None:
            lines.append(f'Affected: {affected["count"]}; scope: {text_value(affected.get("scope", "unknown"), 40)}; '
                         f'qualifier: {text_value(affected.get("qualifier", "unknown"), 40)}; '
                         f'jurisdiction: {text_value(affected.get("jurisdiction") or "unspecified", 40)}')
        if report.get('summary'):
            lines.append(text_value(report['summary']))
        lines.append(f'Original source: {report["sourceUrl"]}')
        if safe_url(report.get('noticeUrl')):
            lines.append(f'Notice: {report["noticeUrl"]}')
        if claimed:
            lines.extend(['This is a third-party ransomware claim, not an independently confirmed breach.', ATTRIBUTION])
        lines.append('Dashboard: https://bd4l.github.io/breach-dashboard-v2/')
        body = '\n'.join(lines)
        event_key = hashlib.sha256(json.dumps([source_id, identifier, event_revision], separators=(',', ':')).encode()).hexdigest()
        events.append({'event_key': event_key, 'observed_at': timestamp(observed), 'source_date': dated.isoformat(),
                       'subject': subject, 'text': body, 'html': '<pre style="white-space:pre-wrap">' + escape(body) + '</pre>'})
    return sorted(events, key=lambda event: (event['observed_at'], event['event_key']))


class PrivateDelivery:
    """Only these methods may contact private storage and the delivery provider."""
    def __init__(self, *, session=None, environment=None):
        config = os.environ if environment is None else environment
        required = ('RESEND_API_KEY', 'ALERT_FROM_EMAIL', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY')
        if any(not config.get(key) for key in required):
            raise AlertError('missing_delivery_configuration')
        self.sender = config['ALERT_FROM_EMAIL']
        if '\r' in self.sender or '\n' in self.sender or '@' not in self.sender:
            raise AlertError('invalid_sender_configuration')
        self.base = config['SUPABASE_URL'].rstrip('/')
        try:
            parts = urlsplit(self.base)
            port = parts.port
        except ValueError:
            raise AlertError('invalid_private_storage_origin') from None
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.path or parts.query or parts.fragment or port not in (None, 443)):
            raise AlertError('invalid_private_storage_origin')
        self.storage_headers = {'apikey': config['SUPABASE_SERVICE_KEY'],
                                'Authorization': 'Bearer ' + config['SUPABASE_SERVICE_KEY']}
        self.provider_headers = {'Authorization': 'Bearer ' + config['RESEND_API_KEY']}
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.last_provider_request = 0.0

    def request(self, url, headers, payload, *, provider=False):
        import requests
        try:
            if provider:
                time.sleep(max(0, 0.25 - (time.monotonic() - self.last_provider_request)))
                self.last_provider_request = time.monotonic()
            with self.session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT,
                                   allow_redirects=False, stream=True, auth=HeaderAuthorization()) as response:
                if not 200 <= response.status_code < 300:
                    if provider:
                        raise ProviderError(f'provider_http_{response.status_code}',
                                            retry=response.status_code in (408, 409, 429) or response.status_code >= 500)
                    raise AlertError('private_storage_request_failed')
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_REPLY_BYTES:
                        raise ValueError('oversize_reply')
                return json.loads(body)
        except (requests.RequestException, ValueError):
            raise (ProviderError('provider_response_uncertain') if provider else
                   AlertError('private_storage_response_failed')) from None

    def rpc(self, name, payload):
        return self.request(self.base + '/rest/v1/rpc/breach_alert_' + name, self.storage_headers, payload)

    def deliver(self, events, *, recent_days=7, limit=25):
        stats = {'queued': 0, 'sent': 0, 'retry': 0, 'held': 0}
        for offset in range(0, len(events), 100):
            queued = self.rpc('enqueue', {'p_events': events[offset:offset + 100],
                                         'p_sender': self.sender, 'p_recent_days': recent_days})
            if type(queued) is not int or queued < 0:
                raise AlertError('invalid_private_enqueue_result')
            stats['queued'] += queued
        for _ in range(limit):
            rows = self.rpc('claim', {})
            if not isinstance(rows, list) or len(rows) > 1:
                raise AlertError('invalid_private_claim_result')
            if not rows:
                break
            row = rows[0]
            if (not isinstance(row, dict) or not all(row.get(key) for key in ('id', 'lease_token', 'payload'))
                    or not isinstance(row['payload'], dict)):
                raise AlertError('invalid_private_claim_result')
            try:
                UUID(row['id'])
                UUID(row['lease_token'])
            except (ValueError, TypeError, AttributeError):
                raise AlertError('invalid_private_claim_identity') from None
            key = 'breach-alert/' + str(row['id'])
            status, message_id, error = 'sent', None, None
            try:
                result = self.request('https://api.resend.com/emails',
                                      {**self.provider_headers, 'Idempotency-Key': key}, row['payload'], provider=True)
                if (not isinstance(result, dict) or not isinstance(result.get('id'), str)
                        or not 1 <= len(result['id']) <= 128):
                    raise ProviderError('provider_response_uncertain')
                message_id = result['id']
            except ProviderError as failure:
                status, error = ('retry' if failure.retry else 'held'), str(failure)
            if self.rpc('finish', {'p_id': row['id'], 'p_lease_token': row['lease_token'], 'p_state': status,
                                   'p_provider_id': message_id, 'p_error_code': error}) is not True:
                raise AlertError('private_acknowledgement_failed')
            stats[status] += 1
        remaining = self.rpc('health', {})
        if not isinstance(remaining, dict) or any(type(remaining.get(key)) is not int for key in ('pending', 'held')):
            raise AlertError('invalid_private_health_result')
        stats.update({'pending': remaining['pending'], 'held_total': remaining['held']})
        return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path)
    source.add_argument('--fetch-published', type=Path, help='Download the fixed public Pages snapshot to this local JSON path.')
    parser.add_argument('--since', type=instant, help='Optional observation cutoff; subscription activation is enforced privately.')
    parser.add_argument('--recent-days', type=int, default=7)
    parser.add_argument('--deliver', action='store_true', help='Explicitly use private storage and send configured staff alerts.')
    parser.add_argument('--limit', type=int, default=25, help='Maximum deliveries per invocation (1–100).')
    args = parser.parse_args(argv)
    try:
        if args.fetch_published:
            if args.deliver:
                raise AlertError('download_and_delivery_must_be_separate_commands')
            snapshot = fetch_published_snapshot(args.fetch_published)
            print(json.dumps({'mode': 'download', 'reports': len(snapshot['reports']), 'generated_at': snapshot['generatedAt']}))
            return 0
        if not 1 <= args.limit <= 100 or args.snapshot.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError('input_budget')
        snapshot = json.loads(args.snapshot.read_text())
        if args.deliver:
            validate_published_snapshot(snapshot)
        events = events_for_snapshot(snapshot, since=args.since, recent_days=args.recent_days)
        if not args.deliver:
            print(json.dumps({'mode': 'dry_run', 'candidate_count': len(events), 'preview': events[:20],
                              'note': 'Offline candidates only. Private subscription activation further restricts delivery.'}))
            return 0
        stats = PrivateDelivery().deliver(events, recent_days=args.recent_days, limit=args.limit)
        print(json.dumps({'mode': 'delivery', **stats}))
        return int(bool(stats['retry'] or stats['held_total']))
    except AlertError as error:
        print(json.dumps({'mode': 'error', 'code': str(error)}))
        return 1
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        print(json.dumps({'mode': 'error', 'code': 'invalid_snapshot_or_arguments'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
