"""Collect official Item 1.05 metadata from EDGAR's current public search API.

The endpoint, pagination and document URLs follow SEC's published search client.
Search every 8-K document in a bounded 30-day window, then require the actual
Item 1.05 filing metadata and primary form; generic cybersecurity mentions and
exhibits cannot create breach reports. No contact identity is invented.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import re
from urllib.parse import urlencode

from .adapters import clean, parse_date
from .models import Collection, Report, SourceError
from .network import PublicClient
from .special_portals import SOURCES as ORIGINAL

SOURCES = {'sec': dict(ORIGINAL['sec'], method='Official Item 1.05 search metadata')}
CLIENT_FACTORY = PublicClient
PAGE_SIZE = 100
VERSION = 'sec-public-search-1'


def search_url(start, end, offset):
    # These parameters and 100-hit offsets are used by edgar_full_text_search.js.
    return 'https://efts.sec.gov/LATEST/search-index?' + urlencode({
        'dateRange': 'custom', 'category': 'custom', 'forms': '8-K',
        'startdt': start.isoformat(), 'enddt': end.isoformat(), 'from': offset})


def parse_search_page(content, *, start, end):
    try:
        data = json.loads(content)
        hits = data['hits']['hits']
        total = data['hits']['total']
        shards = data['_shards']
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError('SEC: expected the public search JSON envelope') from exc
    if (not isinstance(shards, dict) or type(shards.get('total')) is not int or shards['total'] <= 0
            or data.get('timed_out') is not False or shards.get('failed') != 0
            or shards.get('successful') != shards.get('total')):
        raise SourceError('SEC: search timed out or returned incomplete search shards')
    if (not isinstance(hits, list) or len(hits) > PAGE_SIZE or not isinstance(total, dict)
            or type(total.get('value')) is not int or total['value'] < 0
            or total.get('relation') not in ('eq', 'gte')):
        raise SourceError('SEC: invalid public search counts')
    reports, hit_ids = [], set()
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get('_source'), dict):
            raise SourceError('SEC: invalid public search record')
        source = hit['_source']
        identity = hit.get('_id')
        if not isinstance(identity, str) or identity in hit_ids:
            raise SourceError('SEC: missing or repeated document identity on a search page')
        hit_ids.add(identity)
        if not isinstance(source.get('file_type'), str) or not isinstance(source.get('form'), str):
            raise SourceError('SEC: search record omitted its form classification')
        if source.get('file_type') not in ('8-K', '8-K/A'):
            continue  # Exhibits and attachments are not separate incident filings.
        if source.get('form') not in ('8-K', '8-K/A') or not isinstance(source.get('items'), list):
            raise SourceError('SEC: primary current report omitted its explicit filing items')
        if '1.05' not in source['items']:
            continue
        match = re.fullmatch(r'(\d{10}-\d{2}-\d{6}):([A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:htm|html|txt))', identity, re.I)
        ciks, names = source.get('ciks'), source.get('display_names')
        if (not match or source.get('adsh') != match[1] or not isinstance(ciks, list)
                or not ciks or not all(isinstance(c, str) and re.fullmatch(r'\d{1,10}', c) and int(c) > 0 for c in ciks)
                or not isinstance(names, list) or not names or not all(isinstance(n, str) and clean(n) for n in names)):
            raise SourceError('SEC: Item 1.05 filing identity is incomplete or unsafe')
        flags = []
        filed = parse_date(source.get('file_date'), flags, 'SEC filing date', today=end)
        if not filed or not start.isoformat() <= filed <= end.isoformat():
            raise SourceError('SEC: Item 1.05 filing date is outside the requested window')
        organization = '; '.join(dict.fromkeys(clean(re.sub(r'\s*\(CIK \d+\)\s*$', '', n)) for n in names))
        # Same official construction as SEC's search UI, from actual hit metadata.
        url = f'https://www.sec.gov/Archives/edgar/data/{int(ciks[0])}/{match[1].replace("-", "")}/{match[2]}'
        reports.append(Report('sec', match[1], organization, url, published_date=filed,
                              notice_url=url, summary=f'Official {source["form"]} filing metadata identifies Item 1.05, Material Cybersecurity Incidents. The primary document has not been enriched.',
                              quality_flags=flags, parser_version=VERSION))
    return reports, hit_ids, total['value'], total['relation']


def collect_with_client(client, *, max_pages=None, today=None):
    limit = 100 if max_pages is None else max_pages
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise SourceError('SEC max_pages must be an integer from 1 to 100')
    today = today or date.today()
    start = today - timedelta(days=30)
    reports, seen_docs, by_accession = [], set(), {}
    expected = None
    exact = False
    exhausted = False
    stopped = ''
    page_count = 0
    for page in range(limit):
        try:
            response = client.request(search_url(start, today, page * PAGE_SIZE))
            current, ids, total, relation = parse_search_page(response.content, start=start, end=today)
            if expected is not None and (total != expected or (relation == 'eq') != exact):
                raise SourceError('Search total changed during pagination; rerun needed for full window coverage')
            if seen_docs.intersection(ids):
                raise SourceError('Search pagination repeated documents; window coverage is incomplete')
            if not ids and len(seen_docs) < total:
                raise SourceError('Search pagination ended before its declared total')
        except SourceError as exc:
            if not reports:
                raise
            stopped = str(exc)
            break
        expected, exact = total, relation == 'eq'
        seen_docs.update(ids)
        page_count += 1
        for report in current:
            existing = by_accession.get(report.native_id)
            if existing and existing != report:
                raise SourceError('SEC: conflicting primary records for the same filing accession')
            if not existing:
                by_accession[report.native_id] = report
                reports.append(report)
        if exact and len(seen_docs) == total:
            exhausted = True
            break
        if exact and len(seen_docs) > total or len(ids) < PAGE_SIZE:
            stopped = 'Search page size and declared total do not reconcile.'
            break
    if not reports and not exhausted:
        raise SourceError('SEC: no Item 1.05 reports found before the bounded search stopped; empty coverage is unverified')
    message = (f'Official 8-K search from {start} through {today}: {len(seen_docs)} of '
               f'{expected if exact else "at least " + str(expected)} document hits inspected across {page_count} pages; '
               f'{len(reports)} distinct primary Item 1.05 filings. '
               'Earlier filings, other disclosure items and document enrichment are outside this rolling window. ')
    message += 'The declared search-window total reconciled.' if exhausted else 'The window is incomplete. ' + (stopped or 'Page budget reached.')
    return Collection('sec', reports, len(reports), message=message, complete=False,
                      empty_is_valid=exhausted and not reports,
                      evidence={'requests': client.requests, 'bytes': client.bytes, 'pageCount': page_count,
                                'searchHitCount': len(seen_docs), 'declaredTotal': expected,
                                'windowStart': start.isoformat(), 'windowEnd': today.isoformat(),
                                'windowReconciled': exhausted})


def collect(source_id, *, max_pages=None):
    if source_id != 'sec':
        raise SourceError('Unknown SEC search source')
    client = CLIENT_FACTORY(max_requests=205, max_bytes=35_000_000, deadline_seconds=480)
    try:
        return collect_with_client(client, max_pages=max_pages)
    finally:
        client.close()
