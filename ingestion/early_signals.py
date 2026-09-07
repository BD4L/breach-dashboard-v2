"""RansomLook's public, metadata-only discovery feed; claims are not confirmations.

Only the documented /api/posts date-range endpoint is requested. We never follow
victim URLs or fetch source HTML, screenshots, onion sites, or leaked documents.
RansomLook publishes these metadata under CC BY 4.0; see its /about page.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata
from urllib.parse import quote, urlencode, urlsplit

from ingestion.models import Collection, Report, SourceError
from ingestion.network import PublicClient

SOURCE_ID = 'ransomlook'
BASE_URL = 'https://www.ransomlook.io'
PARSER_VERSION = 'ransomlook-metadata-1'
MAX_RESPONSE_BYTES = 2_000_000
MAX_POSTS = 5_000
WINDOW_DAYS = 3
CLIENT_FACTORY = PublicClient
_FIELDS = {'group_name', 'post_title', 'discovered'}


class _MetadataError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SourceError('RansomLook collection time must be timezone-aware')
    return value.astimezone(timezone.utc)


def _window(today: date | None, now: datetime) -> tuple[date, date]:
    end = today or now.date()
    if type(end) is not date or end > now.date():
        raise SourceError('RansomLook window must end on a known UTC date')
    return end - timedelta(days=WINDOW_DAYS - 1), end


def posts_url(start: date, end: date) -> str:
    if type(start) is not date or type(end) is not date or (end - start).days != WINDOW_DAYS - 1:
        raise SourceError('RansomLook requires one three-day UTC window')
    return BASE_URL + '/api/posts?' + urlencode({'from': start.isoformat(), 'to': end.isoformat()})


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError('Missing, non-text, or oversized metadata')
    # Preserve the source spelling while preventing hidden/control text. The UI
    # must still render these untrusted strings as text, never as HTML.
    if any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('Control characters in metadata')
    value = ' '.join(unicodedata.normalize('NFC', value).split())
    if not value or '<' in value or '>' in value:
        raise ValueError('Empty or markup-like metadata')
    return value


def _discovered(value: object, *, start: date, end: date, now: datetime) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value):
        raise _MetadataError('invalid_discovery_timestamp')
    try:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise _MetadataError('invalid_discovery_timestamp') from exc
    if observed > now:
        raise _MetadataError('future_discovery_timestamp')
    if not start <= observed.date() <= end:
        raise _MetadataError('outside_requested_window')
    return observed


def parse_posts(value: object, *, start: date, end: date,
                now: datetime | None = None) -> Collection:
    """Validate the full metadata response and conservatively withhold collisions."""
    now = _utc(now)
    posts_url(start, end)  # Validate the same window contract as the request.
    if end > now.date():
        raise SourceError('RansomLook requested window ends in the future')
    if not isinstance(value, dict) or set(value) != {'posts'} or not isinstance(value['posts'], list):
        raise SourceError('RansomLook metadata response omitted its posts list or changed schema')
    rows = value['posts']
    if len(rows) > MAX_POSTS:
        raise SourceError('RansomLook metadata response exceeded the record limit')
    reports, conflicted = {}, set()
    rejected = duplicates = conflicts = 0
    rejection_reasons = {}

    def reject(reason: str, count: int = 1):
        nonlocal rejected
        rejected += count
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + count

    for row in rows:
        try:
            if not isinstance(row, dict) or set(row) != _FIELDS:
                raise ValueError('Metadata row schema changed')
            group = _text(row['group_name'], maximum=80)
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}', group):
                raise ValueError('Group is not a safe public group slug')
            title = _text(row['post_title'], maximum=300)
            observed = _discovered(row['discovered'], start=start, end=end, now=now)
            observed_at = observed.isoformat().replace('+00:00', 'Z')
            # The metadata endpoint has no native post ID. Timestamp is part of
            # the identity so repeat claims about the same company do not merge.
            identity = json.dumps([group.casefold(), title.casefold(), observed_at],
                                  ensure_ascii=False, separators=(',', ':'))
            native = 'claim:' + hashlib.sha256(identity.encode('utf-8')).hexdigest()
            report = Report(
                source_id=SOURCE_ID, native_id=native, organization=title,
                source_url=BASE_URL + '/group/' + quote(group, safe=''),
                reported_date=observed.date().isoformat(),
                source_observed_at=observed.replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
                signal_type='ransomware_claim',
                summary=f'Unverified ransomware claim attributed to {group}, observed by RansomLook. This collector has not independently confirmed a breach.',
                quality_flags=[
                    {'code': 'unverified_claim', 'message': 'Threat-actor claim reported by RansomLook; this is not a confirmed breach notification.'},
                    {'code': 'derived_claim_identity', 'message': 'The provider exposes no stable post ID in this feed; identity uses group, title and discovery timestamp. Title corrections may appear as a separate claim.'},
                ], parser_version=PARSER_VERSION,
            )
        except (ValueError, TypeError, KeyError) as exc:
            reject(exc.code if isinstance(exc, _MetadataError) else 'invalid_metadata')
            continue
        if native in conflicted:
            reject('conflicting_identity')
        elif native in reports:
            if reports[native] == report:
                reject('identical_duplicate')
                duplicates += 1
            else:
                del reports[native]
                conflicted.add(native)
                reject('conflicting_identity', 2)
                conflicts += 1
        else:
            reports[native] = report
    if rows and not reports:
        raise SourceError('RansomLook returned no usable, unambiguous claim metadata')
    # Success means the provider's returned metadata window was validated, not
    # universal ransomware coverage. A valid empty list is not absence of attacks.
    message = (f'RansomLook metadata from {start} through {end} UTC: {len(reports)} usable claims '
               f'from {len(rows)} returned rows. Claims are unverified. Only this rolling window '
               'was requested; the provider supplies no independent total or pagination marker. '
               'Earlier claims and confirmation by affected organizations are outside this collection.')
    if rejected:
        message += f' {rejected} rows withheld, including {duplicates} identical duplicates and {conflicts} conflicting identities.'
    if future := rejection_reasons.get('future_discovery_timestamp'):
        message += f' {future} provider discovery timestamps were in the future and were withheld without reinterpreting their UTC dates.'
    return Collection(
        SOURCE_ID, list(reports.values()), len(rows), rejected, message, complete=not rejected,
        empty_is_valid=not rows,
        evidence={'windowStart': start.isoformat(), 'windowEnd': end.isoformat(),
                  'returnedCount': len(rows), 'duplicateRows': duplicates,
                  'conflictingIdentities': conflicts, 'metadataOnly': True,
                  'rejectionReasons': rejection_reasons,
                  'independentTotalAvailable': False, 'license': 'CC BY 4.0',
                  'licenseUrl': 'https://creativecommons.org/licenses/by/4.0/',
                  'attributionUrl': BASE_URL + '/about'},
    )


def collect_with_client(client, *, today: date | None = None,
                        now: datetime | None = None) -> Collection:
    now = _utc(now)
    start, end = _window(today, now)
    url = posts_url(start, end)
    response = client.request(url, headers={'Accept': 'application/json'})
    # The production client restricts every fetch to this exact metadata URL.
    # Also guard injected clients against returning a different source view.
    if urlsplit(response.url) != urlsplit(url):
        raise SourceError('RansomLook metadata endpoint redirected to another source view')
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise SourceError('RansomLook metadata response exceeded the byte limit')
    if response.content_type.split(';', 1)[0].strip().lower() != 'application/json':
        raise SourceError('RansomLook metadata endpoint did not return JSON')
    try:
        value = json.loads(response.content)
    except (ValueError, UnicodeError) as exc:
        raise SourceError('RansomLook metadata response is invalid JSON') from exc
    result = parse_posts(value, start=start, end=end, now=now)
    result.evidence.update(requests=client.requests, bytes=client.bytes)
    return result


def collect(source_id: str = SOURCE_ID, *, max_pages: int | None = None,
            today: date | None = None, now: datetime | None = None) -> Collection:
    if source_id != SOURCE_ID:
        raise SourceError('Unknown early-signal source')
    if max_pages is not None and (type(max_pages) is not int or max_pages != 1):
        raise SourceError('RansomLook metadata uses one bounded request; max_pages must be 1')
    now = _utc(now)
    start, end = _window(today, now)
    client = CLIENT_FACTORY(max_requests=2, max_bytes=MAX_RESPONSE_BYTES, deadline_seconds=60,
                            allowed_urls={posts_url(start, end)})
    try:
        return collect_with_client(client, today=today, now=now)
    finally:
        client.close()
