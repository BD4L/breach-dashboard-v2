"""The Delaware AG's linked current public Socrata breach database.

The former HTML table stops in July 2025. Its parent now links dir6-wx8v on the
official open-data portal. Only published SODA 2.1 reads are used, without tokens.
"""
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from .models import Collection, Report, SourceError
from .network import PublicClient
from .other_portals import clean, document_key, evidence_url, key, parse_count, parse_date, stable_id
from .rediscovered_states import maine_legacy_data_types

DATASET = 'dir6-wx8v'
HOMEPAGE = 'https://data.delaware.gov/Public-Safety/Data-Security-Breach-Database/dir6-wx8v/data_preview'
METADATA = f'https://data.delaware.gov/api/views/{DATASET}.json'
RESOURCE = f'https://data.delaware.gov/resource/{DATASET}.json'
SOURCES = {'delaware': {'id': 'delaware', 'label': 'Delaware', 'jurisdiction': 'DE',
                       'method': 'Official public open-data JSON', 'homepage': HOMEPAGE}}
FIELDS = {'company_name': 'text', 'date_of_breach': 'calendar_date', 'breach_discovered': 'calendar_date',
          'date_of_notice': 'calendar_date', 'de_residents_affected': 'number', 'total_affected': 'number',
          'supplemental_notification_date': 'calendar_date', 'supplemental_de_residents_affected': 'text',
          'supplemental_total_affected': 'text', 'information_breached': 'text', 'sample_of_notice': 'url'}
PAGE_SIZE = 500
VERSION = 'delaware-open-data-1'
LEGACY_URL = 'https://attorneygeneral.delaware.gov/fraud/cpu/securitybreachnotification/database/'


def read_json(response):
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError('Delaware: official open-data endpoint did not return JSON') from exc


def validate_metadata(data):
    if not isinstance(data, dict) or data.get('id') != DATASET or data.get('name') != 'Data Security Breach Database' or data.get('viewType') != 'tabular':
        raise SourceError('Delaware: published dataset identity changed')
    columns = data.get('columns')
    if not isinstance(columns, list):
        raise SourceError('Delaware: published column schema is missing')
    names = {c.get('fieldName'): c.get('dataTypeName') for c in columns if isinstance(c, dict)}
    if any(names.get(name) != kind for name, kind in FIELDS.items()):
        raise SourceError('Delaware: published breach columns changed')
    if type(data.get('rowsUpdatedAt')) is not int or data['rowsUpdatedAt'] <= 0:
        raise SourceError('Delaware: dataset revision marker is unavailable')
    return data['rowsUpdatedAt']


def count_rows(data):
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict) or not re.fullmatch(r'\d+', str(data[0].get('count', ''))):
        raise SourceError('Delaware: independent dataset count is invalid')
    return int(data[0]['count'])


def page_url(offset):
    return RESOURCE + '?' + urlencode({'$select': ','.join([':id', *FIELDS]), '$order': ':id',
                                       '$limit': PAGE_SIZE, '$offset': offset})


def source_date(value, flags, label, today):
    raw = clean(value)
    if raw.lower() in ('', 'null', 'none'):
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00\.000', raw):
        raise SourceError('Delaware: source calendar-date format changed')
    return parse_date(raw[:10], flags, label, today=today)


def parse_rows(rows, *, aliases=None, today=None):
    today = today or date.today()
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise SourceError('Delaware: unexpected public record page')
    aliases = aliases or {}
    reports, ids, rejected = [], set(), 0
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r'row-[a-z0-9~_.-]+', str(row.get(':id', ''))):
            raise SourceError('Delaware: missing stable published row ID')
        identity = row[':id']
        if identity in ids:
            raise SourceError('Delaware: repeated published row ID')
        ids.add(identity)
        organization = clean(row.get('company_name'))
        if not organization:
            rejected += 1; continue
        flags = []
        notice_field = row.get('sample_of_notice')
        if notice_field is not None and not isinstance(notice_field, dict):
            raise SourceError('Delaware: notice-link schema changed')
        notice = evidence_url(HOMEPAGE, (notice_field or {}).get('url'), flags)
        alias = aliases.get(identity)
        if alias and alias['match_key'] != stable_id(document_key(notice).casefold(), key(organization)):
            # A changed/reused publisher row ID must not inherit another
            # organization's legacy identity, dates or affected counts.
            rejected += 1; continue
        occurred = source_date(row.get('date_of_breach'), flags, 'Breach date', today)
        discovered = source_date(row.get('breach_discovered'), flags, 'Breach discovered', today)
        notified = source_date(row.get('date_of_notice'), flags, 'Source notice date', today)
        supplement = source_date(row.get('supplemental_notification_date'), flags, 'Supplemental notice date', today)
        count, qualifier = parse_count('' if str(row.get('de_residents_affected', '')).lower() == 'null' else row.get('de_residents_affected'), flags)
        native = alias['native_id'] if alias else 'socrata-' + identity
        reported = alias.get('reported_date') if alias else None
        end = None
        if alias:
            flags.append({'code': 'legacy_identity_preserved', 'message': 'Native identity and any reported date are retained from the legacy official table, matched one-to-one by notice document and normalized organization.'})
            old_start, old_end = alias.get('breach_start'), alias.get('breach_end')
            if old_end:
                if occurred == old_start and occurred and old_end >= occurred:
                    end = old_end
                    flags.append({'code': 'legacy_breach_end_preserved', 'message': f'Breach end {end} is retained from the legacy official table because the current start is unchanged. Current dataset has no end-date column. Legacy source: {LEGACY_URL}'})
                else:
                    flags.append({'code': 'legacy_breach_range_context', 'message': f'Legacy official table recorded breach range {old_start or "unknown"} through {old_end}. Current dataset supplies a different single date; no combined range was inferred. Legacy source: {LEGACY_URL}'})
            if count is None and clean(row.get('de_residents_affected')).lower() in ('', 'null', 'none') and alias.get('affected_count') is not None:
                count, qualifier = alias['affected_count'], alias['affected_qualifier']
                flags.append({'code': 'legacy_affected_count_preserved', 'message': f'Original Delaware resident count {count} is retained from the legacy official table because the current original-count field is empty. This is prior evidence, not a newly verified count. Legacy source: {LEGACY_URL}'})
        flags.append({'code': 'notice_date_not_receipt_date', 'message': 'The current dataset names a Date of Notice; it does not establish an AG receipt or publication date.'})
        summary = 'Current Delaware Attorney General open-data listing. Affected count covers Delaware residents only.'
        if notified:
            summary += f' Source notice date: {notified}.'
        if supplement:
            summary += f' Supplemental notice date: {supplement}.'
        if any(clean(row.get(name)).lower() not in ('', 'null', 'none') for name in ('supplemental_de_residents_affected', 'supplemental_total_affected')):
            flags.append({'code': 'supplemental_count_not_combined', 'message': 'Supplemental affected counts are available in the source; they were not added to or substituted for the original resident count.'})
        raw_types = clean(row.get('information_breached'))
        types = maine_legacy_data_types(raw_types, flags) if raw_types.lower() not in ('', 'null', 'none') else []
        reports.append(Report('delaware', native, organization, HOMEPAGE, reported_date=reported,
                              breach_start=occurred, breach_end=end, discovery_date=discovered, affected_count=count,
                              affected_scope='state', affected_jurisdiction='DE', affected_qualifier=qualifier,
                              notice_url=notice, data_types=types, summary=summary, quality_flags=flags,
                              parser_version=VERSION))
    return reports, ids, rejected


def collect(source_id='delaware', *, max_pages=None):
    if source_id != 'delaware':
        raise SourceError('Unknown Delaware source')
    limit = 20 if max_pages is None else max_pages
    if type(limit) is not int or not 1 <= limit <= 100:
        raise SourceError('Delaware max_pages must be an integer between 1 and 100')
    aliases = json.loads(Path(__file__).with_name('delaware_legacy_ids.json').read_text())
    client = PublicClient(max_requests=2 * limit + 8, max_bytes=20_000_000, deadline_seconds=240)
    reports, seen, rejected, pages = [], set(), 0, 0
    stop = ''
    try:
        revision = validate_metadata(read_json(client.request(METADATA)))
        count_url = RESOURCE + '?' + urlencode({'$select': 'count(*)'})
        total = count_rows(read_json(client.request(count_url)))
        for page in range(limit):
            if len(seen) >= total:
                break
            try:
                rows = read_json(client.request(page_url(page * PAGE_SIZE)))
                current, ids, bad = parse_rows(rows, aliases=aliases)
                if seen & ids or len(rows) != min(PAGE_SIZE, total - len(seen)):
                    raise SourceError('Delaware: page overlaps or disagrees with the independent row count')
            except SourceError as exc:
                if not reports: raise
                stop = str(exc); break
            reports.extend(current); seen.update(ids); rejected += bad; pages += 1
        try:
            final_count = count_rows(read_json(client.request(count_url)))
            final_revision = validate_metadata(read_json(client.request(METADATA)))
        except SourceError as exc:
            if not reports: raise
            final_count = final_revision = None
            stop = 'Final dataset consistency check failed: ' + str(exc)
        complete = not stop and len(seen) == total == final_count and revision == final_revision
        if not complete:
            stop = stop or 'Page budget reached or dataset changed while collecting.'
        if len({r.native_id for r in reports}) != len(reports):
            raise SourceError('Delaware: legacy identity mapping produced duplicate report identities')
        return Collection('delaware', reports, len(seen), rejected,
                          f'Current official dataset: {len(seen)} of {total} rows processed across {pages} pages. Independent counts and dataset revision checked before and after collection. Unmatched legacy history remains retained separately.' + (' Collection incomplete: ' + stop if stop else ''),
                          complete=complete and not rejected, empty_is_valid=complete and total == 0,
                          evidence={'pageCount': pages, 'declaredTotal': total, 'rowsUpdatedAt': revision,
                                    'requests': client.requests, 'bytes': client.bytes, 'legacyIdentitiesMatched': sum(r.native_id in {a['native_id'] for a in aliases.values()} for r in reports)})
    finally:
        client.close()
