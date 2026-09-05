"""Recovered Massachusetts letter navigation; annual reports remain preferred.

The letter archive omits non-letter notifications and does not establish receipt
dates or resident counts. It can add newly identified reports while the store
preserves every existing, potentially richer annual-report observation.
"""
from __future__ import annotations

import calendar
from datetime import date
from io import BytesIO
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
import pdfplumber

from .adapters import MA_HEADERS, clean, discover_ma_reports, key, parse_date, parse_ma_tables
from .models import Collection, Report, SourceError
from .network import PublicClient

ARCHIVE_URL = 'https://www.mass.gov/archive/data-breach-notification-letters'
NH_HOME = 'https://www.doj.nh.gov/citizens/consumer-protection-antitrust-bureau/security-breach-notifications'
SOURCES = {'massachusetts': {'id': 'massachusetts', 'label': 'Massachusetts',
           'jurisdiction': 'MA', 'method': 'Annual report / official letter archive',
           'homepage': 'https://www.mass.gov/lists/data-breach-notification-reports'},
           'new_hampshire': {'id': 'new_hampshire', 'label': 'New Hampshire',
           'jurisdiction': 'NH', 'method': 'Official public document API', 'homepage': NH_HOME}}
VERSION = 'northeast-letters-1'
ANNUAL_VERSION = 'northeast-annual-1'
NH_VERSION = 'northeast-documents-2'
# A bounded ordinary-browser client can be injected without changing parsers.
# It must implement request(url)->Response and close(), plus requests/bytes.
CLIENT_FACTORY = PublicClient
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTH_TITLE = re.compile(r'^Data Breach Notification Letters ([A-Za-z]+) (20\d{2})$', re.I)
NH_PAGE_SIZE = 25
MA_REPORT_INDEX = 'https://www.mass.gov/lists/data-breach-notification-reports'


def ma_page_tables(page, number):
    """Repair only a missing bottom border established by the PDF's own grid."""
    tables = page.extract_tables()
    if not tables:
        raise SourceError(f'Massachusetts: page {number} has no validated table extraction')
    boundaries = page.find_tables()
    if len(boundaries) != 1:
        raise SourceError(f'Massachusetts: page {number} does not have one identifiable report table')
    headings = {MA_HEADERS[key(cell)]: i for i, cell in enumerate(tables[0][0]) if key(cell) in MA_HEADERS}
    if not {'id', 'reported', 'organization', 'count'} <= headings.keys():
        raise SourceError(f'Massachusetts: page {number} report column headings changed')
    id_column = boundaries[0].rows[0].cells[headings['id']]
    if id_column is None:
        raise SourceError(f'Massachusetts: page {number} has no report ID column boundaries')
    # Once IDs reach four digits the PDF wraps them into two physical lines.
    # Read the named ID column independently so intervening organization text
    # from the same row cannot corrupt or hide the source ID sequence.
    words = page.crop((max(0, id_column[0] - 1), id_column[1], min(page.width, id_column[2] + 1), page.height)).extract_words()
    source_ids = {}
    for index, word in enumerate(words):
        native = word['text']
        bottom = word['bottom']
        if re.fullmatch(r'20\d{2}-', native) and index + 1 < len(words):
            next_word = words[index + 1]
            if re.fullmatch(r'\d+', next_word['text']) and 0 <= next_word['top'] - word['bottom'] <= 20:
                native += next_word['text']
                bottom = next_word['bottom']
        if re.fullmatch(r'20\d{2}-\d+', native):
            if native in source_ids:
                raise SourceError(f'Massachusetts: page {number} repeats a source report ID')
            source_ids[native] = {'top': word['top'], 'bottom': bottom}
    text_ids = set(source_ids)
    def ids(items):
        return {match for table in items for row in table or [] for cell in row or []
                for match in re.findall(r'\b20\d{2}-\d+\b', re.sub(r'(20\d{2}-)\s+(\d+)', r'\1\2', str(cell or '')))}
    table_ids = ids(tables)
    if text_ids and table_ids == text_ids:
        return tables, False
    if len(boundaries) != 1 or not table_ids or not table_ids < text_ids:
        raise SourceError(f'Massachusetts: page {number} text/table report IDs disagree')
    left, top, right, table_bottom = boundaries[0].bbox
    vertical = [edge for edge in page.edges if edge.get('orientation') == 'v'
                and left - 2 <= edge['x0'] <= right + 2 and edge['top'] >= top - 2]
    bottom = max((edge['bottom'] for edge in vertical), default=table_bottom)
    missing_words = [source_ids[native] for native in text_ids - table_ids]
    # Every omitted ID must belong to the final row below the extracted table,
    # inside the existing source column borders, not arbitrary page/footer text.
    if (bottom <= table_bottom or not missing_words
            or any(word['top'] < table_bottom or word['bottom'] > bottom + 1 for word in missing_words)):
        raise SourceError(f'Massachusetts: page {number} omitted records outside a recoverable bottom row')
    markers = [edge for edge in page.edges if edge.get('orientation') == 'h'
               and abs(edge['top'] - bottom) <= 1 and left - 2 <= edge['x0'] <= right + 2]
    if len(markers) < 2 or not any(edge['x0'] <= left + 2 for edge in markers) or not any(edge['x1'] >= right - 2 for edge in markers):
        raise SourceError(f'Massachusetts: page {number} has no source bottom-border markers')
    repaired = page.extract_tables({'explicit_horizontal_lines': [bottom]})
    if ids(repaired) != text_ids:
        raise SourceError(f'Massachusetts: page {number} report IDs still disagree after bounded grid repair')
    return repaired, True


def parse_ma_annual(content, url, *, today=None):
    if not content.startswith(b'%PDF-'):
        raise SourceError('Massachusetts: annual document is not a PDF')
    try:
        tables, repaired_pages = [], []
        with pdfplumber.open(BytesIO(content)) as pdf:
            if len(pdf.pages) > 500:
                raise SourceError('Massachusetts: annual PDF exceeds the 500-page parse budget')
            page_count = len(pdf.pages)
            for number, page in enumerate(pdf.pages, 1):
                current, repaired = ma_page_tables(page, number)
                tables.extend(current)
                if repaired:
                    repaired_pages.append(number)
        # Normalize line wrapping only in the named ID column. Other source
        # fields continue through the existing conservative field parsers.
        for table in tables:
            id_column = None
            for row in table:
                header = {MA_HEADERS[key(cell)]: i for i, cell in enumerate(row) if key(cell) in MA_HEADERS}
                if 'id' in header:
                    id_column = header['id']
                elif id_column is not None and id_column < len(row):
                    value = str(row[id_column] or '')
                    if re.fullmatch(r'20\d{2}-\s*\d+', value):
                        row[id_column] = re.sub(r'\s+', '', value)
        result = parse_ma_tables(tables, url, today=today)
        for report in result.reports:
            report.parser_version = ANNUAL_VERSION
        result.complete = False
        result.message = f'Annual PDF: all {page_count} pages validated against source report IDs; {len(repaired_pages)} missing bottom borders repaired from source grid geometry. No independent annual record total is available; annual coverage remains partial.'
        result.evidence = {'pageCount': page_count, 'repairedBottomBorderPages': repaired_pages}
        return result
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f'Massachusetts: annual PDF extraction failed ({type(exc).__name__})') from exc


def collect_annual(source_id, *, max_pages=None):
    """Prefer richer annual records before attempting the independent letter list."""
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 200):
        raise SourceError('max_pages must be an integer from 1 to 200')
    client = PublicClient(max_requests=12, max_bytes=15_000_000, deadline_seconds=240)
    try:
        index = client.request(MA_REPORT_INDEX)
        links = discover_ma_reports(index.text)
        reports, parsed, rejected, years, documents = [], 0, 0, [], []
        stopped = None
        for year, url in links[:max_pages or len(links)]:
            try:
                response = client.request(url)
                current = parse_ma_annual(response.content, response.url)
            except SourceError as exc:
                if not reports:
                    raise
                stopped = str(exc)
                break
            reports.extend(current.reports)
            parsed += current.parsed
            rejected += current.rejected
            years.append(year)
            documents.append({'year': year, 'reports': len(current.reports), **current.evidence})
        message = f'Collected linked annual report years {", ".join(map(str, years))}. Every collected PDF page was checked against its source report IDs; no independent annual totals establish complete coverage.'
        unvisited = [year for year, _ in links if year not in years]
        if unvisited:
            message += f' Linked annual report years not collected: {", ".join(map(str, unvisited))}.'
        if stopped:
            message += ' Collection stopped before a later annual report: ' + stopped
        return Collection(source_id, reports, parsed, rejected,
            message, complete=False, evidence={'requests': client.requests, 'bytes': client.bytes,
                                               'years': years, 'unvisitedYears': unvisited, 'documents': documents})
    finally:
        client.close()


def _official_url(base, value, path_prefix):
    url = urljoin(base, value)
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'www.mass.gov' or parts.username
            or parts.password or parts.port not in (None, 443)
            or not parts.path.startswith(path_prefix) or parts.query or parts.fragment):
        raise SourceError('Massachusetts: letter navigation supplied an unexpected official URL')
    return url


def discover_ma_months(html, *, today=None):
    """Use actual current/prior-year month links, never construct missing pages."""
    today = today or date.today()
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('h1')
    if title:
        for prefix in title.select('.ma__visually-hidden'):
            prefix.decompose()
    if not title or clean(title.get_text(' ')).lower() != 'data breach notification letters':
        raise SourceError('Massachusetts: expected official letter archive heading not found')
    months = {}
    for anchor in soup.find_all('a', href=True):
        match = MONTH_TITLE.fullmatch(clean(anchor.get_text(' ')))
        if not match or match[1].lower() not in MONTHS:
            continue
        year, month = int(match[2]), MONTHS[match[1].lower()]
        if year not in (today.year, today.year - 1) or (year, month) > (today.year, today.month):
            continue
        url = _official_url(ARCHIVE_URL, anchor['href'], '/lists/data-breach-notification-letters-')
        # Require agreement between the published label and its actual destination.
        if urlsplit(url).path != f'/lists/data-breach-notification-letters-{match[1].lower()}-{year}':
            raise SourceError('Massachusetts: month link label and destination disagree')
        months[(year, month)] = url
    if not months:
        raise SourceError('Massachusetts: no current or prior-year monthly letter pages were linked')
    return [(year, month, url) for (year, month), url in sorted(months.items(), reverse=True)]


def parse_ma_letters(html, url):
    """Parse only identified source letters from a verified named monthly page."""
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.find('h1')
    match = MONTH_TITLE.fullmatch(clean(heading.get_text(' '))) if heading else None
    if not match or match[1].lower() not in MONTHS:
        raise SourceError('Massachusetts: expected named monthly letter heading not found')
    year = int(match[2])
    _official_url(ARCHIVE_URL, url, '/lists/data-breach-notification-letters-')
    if urlsplit(url).path != f'/lists/data-breach-notification-letters-{match[1].lower()}-{year}':
        raise SourceError('Massachusetts: returned month page differs from the requested page')
    reports, seen, parsed, rejected, placeholders = [], set(), 0, 0, 0
    for anchor in soup.select('a.ma__download-link__file-link[href]'):
        # The live anchor includes a screen-reader-only file type/size prefix.
        for prefix in anchor.select('.ma__visually-hidden'):
            prefix.decompose()
        label = clean(anchor.get_text(' '))
        record = re.fullmatch(r'(?:Assigned Data Breach Number\s*-\s*)?(20\d{2})-(\d+)\s*-\s*(.+)', label, re.I)
        if not record:
            if re.search(r'20\d{2}-\d', label):
                parsed += 1
                rejected += 1
            continue  # Archive labels and unrelated help PDFs are not reports.
        if int(record[2]) == 0 or 'placeholder' in record[3].lower():
            placeholders += 1
            continue
        parsed += 1
        if int(record[1]) != year:
            rejected += 1
            continue
        native_id = f'{year}-{int(record[2])}'
        organization = clean(record[3])
        if not organization:
            rejected += 1
            continue
        notice = _official_url(url, anchor['href'], '/doc/')
        if not urlsplit(notice).path.endswith('/download'):
            raise SourceError('Massachusetts: identified letter has no official document download link')
        if native_id in seen:
            raise SourceError('Massachusetts: duplicate native breach number in a monthly letter page')
        seen.add(native_id)
        reports.append(Report('massachusetts', native_id, organization, url,
            notice_url=notice, summary=f'Official letter listed in the {match[1]} {year} archive. Receipt date and Massachusetts resident count are not established by this listing.',
            quality_flags=[{'code': 'letter_listing_only', 'message': 'Only the official letter listing was collected. Month membership is not a report or publication date; dates and affected count remain unknown.'}],
            parser_version=VERSION))
    if not reports:
        raise SourceError('Massachusetts: no identified breach letters in the requested monthly page')
    result = Collection('massachusetts', reports, parsed, rejected,
        f'{len(reports)} identified letters from {match[1]} {year}; notices delivered without a letter are outside this archive.',
        complete=False, evidence={'month': f'{year}-{MONTHS[match[1].lower()]:02d}', 'skippedPlaceholders': placeholders})
    result.new_records_only = True
    return result


def collect_ma_letters(client, *, max_pages=None, today=None):
    limit = 24 if max_pages is None else max_pages
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise SourceError('max_pages must be an integer from 1 to 200')
    archive = client.request(ARCHIVE_URL)
    months = discover_ma_months(archive.text, today=today)
    reports, seen, parsed, rejected, visited, skipped = [], set(), 0, 0, [], 0
    stopped = None
    for year, month, url in months[:limit]:
        try:
            page = client.request(url)
            result = parse_ma_letters(page.text, page.url)
            if seen.intersection(report.native_id for report in result.reports):
                raise SourceError('Massachusetts: repeated native breach number across monthly pages; stop before choosing competing records')
        except SourceError as exc:
            stopped = str(exc)
            break
        reports.extend(result.reports)
        seen.update(report.native_id for report in result.reports)
        parsed += result.parsed
        rejected += result.rejected
        skipped += result.evidence['skippedPlaceholders']
        visited.append(f'{year}-{month:02d}')
    if not reports:
        raise SourceError('Massachusetts: letter archive yielded no usable reports. ' + (stopped or 'No monthly pages were collected.'))
    message = f'Letter-only fallback: {len(visited)} of {len(months)} linked current/prior-year month pages collected ({", ".join(visited)}). Notices sent without letters and unvisited months are excluded. Existing richer reports are preserved.'
    if stopped:
        message += ' Collection stopped: ' + stopped
    result = Collection('massachusetts', reports, parsed, rejected, message,
                        complete=False, evidence={'pageCount': len(visited), 'linkedMonthCount': len(months),
                                                   'months': visited, 'skippedPlaceholders': skipped})
    result.new_records_only = True
    return result


def nh_api_url(page, page_size=NH_PAGE_SIZE):
    # Exact action/category/filter contract observed in the official browser UI.
    return 'https://www.doj.nh.gov/content/api/documents?' + urlencode({
        'iterate_nodes': 'true', 'q': '@field_document_category|=|2146',
        'textsearch': '', 'sort': 'field_date_posted|desc|ALLOW_NULLS',
        'filter_mode': 'inclusive', 'type': 'document', 'page': page, 'size': page_size})


def parse_nh_api(data, *, page=1, page_size=NH_PAGE_SIZE, today=None):
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise SourceError('New Hampshire: public document response is not the expected JSON envelope')
    for key in ('item_count', 'total', 'last_page'):
        if isinstance(data.get(key), bool) or not isinstance(data.get(key), int) or data[key] < 0:
            raise SourceError('New Hampshire: public document pagination counts are missing or invalid')
    rows, total, last_page = data['data'], data['total'], data['last_page']
    if (not total or last_page != (total + page_size - 1) // page_size
            or page < 1 or page > last_page or data['item_count'] != len(rows)
            or len(rows) != min(page_size, total - (page - 1) * page_size)):
        raise SourceError('New Hampshire: document pagination counts disagree; coverage cannot be established')
    reports, rejected, seen, unresolved_documents = [], 0, set(), 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('fields'), dict):
            raise SourceError('New Hampshire: public document row schema changed')
        fields = row['fields']
        native = str(row.get('id', ''))
        if not native.isdigit() or fields.get('nid') != [native] or fields.get('moderation_state') != ['published']:
            rejected += 1
            continue
        if not any(str(category.get('id')) == '2146' for category in fields.get('field_document_category') or [] if isinstance(category, dict)):
            raise SourceError('New Hampshire: public API returned a document outside the breach category')
        organization = clean(row.get('title'))
        if not organization or fields.get('title') != [row.get('title')]:
            rejected += 1
            continue
        document_field = fields.get('field_document_file')
        document = document_field.get('uri') if isinstance(document_field, dict) else None
        if not isinstance(document, str):
            rejected += 1
            continue
        parts = urlsplit(document)
        if parts.scheme == 'public':
            # The live API sometimes exposes a Drupal storage URI instead of
            # an HTTP document link. There is no demonstrated public URL for
            # those rows; do not invent one from another document's route.
            rejected += 1
            unresolved_documents += 1
            continue
        if (parts.scheme != 'https' or parts.hostname not in ('mm.nh.gov', 'www.doj.nh.gov')
                or parts.username or parts.password or parts.port not in (None, 443)
                or parts.query or parts.fragment or not parts.path.lower().endswith('.pdf')):
            raise SourceError('New Hampshire: public API supplied an unexpected official document link')
        if native in seen:
            raise SourceError('New Hampshire: duplicate native document IDs in one page')
        seen.add(native)
        flags = []
        posted = fields.get('field_date_posted')
        if not isinstance(posted, list) or len(posted) != 1:
            published = None
            flags.append({'code': 'publication_date_unavailable', 'message': 'The public document listing has no unambiguous posted date.'})
        else:
            published = parse_date(posted[0], flags, 'Date posted', today=today)
        reports.append(Report('new_hampshire', native, organization, NH_HOME,
            published_date=published, notice_url=document,
            summary='Official New Hampshire breach-document listing. Publication date comes from the posted-date field; linked PDF contents and affected counts were not collected.',
            quality_flags=flags, parser_version=NH_VERSION))
    if not reports:
        raise SourceError('New Hampshire: no usable public documents in the requested page')
    return Collection('new_hampshire', reports, len(rows), rejected, complete=False,
                      evidence={'unresolvedDocumentRows': unresolved_documents}), total, last_page


def collect_nh_documents(client, *, max_pages=None, today=None):
    limit = 30 if max_pages is None else max_pages
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise SourceError('max_pages must be an integer from 1 to 200')
    by_id, seen, conflicts, page_signatures = {}, set(), set(), set()
    parsed, rejected, visited, duplicate_rows, unresolved_documents = 0, 0, 0, 0, 0
    expected_total, last_page, stopped = None, None, None
    for page in range(1, limit + 1):
        try:
            response = client.request(nh_api_url(page))
            try:
                data = json.loads(response.content)
            except (ValueError, UnicodeDecodeError) as exc:
                raise SourceError('New Hampshire: document API did not return JSON') from exc
            current, total, final_page = parse_nh_api(data, page=page, today=today)
            if expected_total is not None and (total != expected_total or final_page != last_page):
                raise SourceError('New Hampshire: total document count changed during pagination')
        except SourceError as exc:
            stopped = str(exc)
            break
        expected_total, last_page = total, final_page
        current_ids = {report.native_id for report in current.reports}
        signature = frozenset(current_ids)
        repeated_page = signature in page_signatures or current_ids <= seen
        page_signatures.add(signature)
        seen.update(current_ids)
        parsed += current.parsed
        rejected += current.rejected
        unresolved_documents += current.evidence['unresolvedDocumentRows']
        for report in current.reports:
            native_id = report.native_id
            if native_id in conflicts:
                rejected += 1  # Every later version of a disputed ID stays withheld.
            elif native_id in by_id:
                if by_id[native_id] == report:
                    rejected += 1
                    duplicate_rows += 1
                else:
                    del by_id[native_id]
                    conflicts.add(native_id)
                    rejected += 2  # Withhold both the prior and current versions.
            else:
                by_id[native_id] = report
        visited += 1
        if repeated_page:
            stopped = 'New Hampshire: public document pagination repeated a full page or cycled through previously seen IDs'
            break
        if page == last_page:
            break
    reports = list(by_id.values())
    if not reports:
        raise SourceError(stopped or 'New Hampshire: no public breach documents were collected')
    complete = (not stopped and visited == last_page and parsed == expected_total
                and len(reports) == expected_total and rejected == 0)
    message = f'{len(reports)} unique usable documents from {parsed} source rows, against {expected_total} declared public breach documents across {visited} of {last_page} pages; source sorts by posted date descending. Linked PDFs were not downloaded.'
    if duplicate_rows or conflicts or unresolved_documents:
        message += f' Rejected {duplicate_rows} identical overlapping rows, withheld all versions of {len(conflicts)} conflicting IDs, and rejected {unresolved_documents} unresolved Drupal document links.'
    if not complete:
        message += ' Coverage is partial; unvisited or rejected records remain outside this run.'
    if stopped:
        message += ' Collection stopped: ' + stopped
    return Collection('new_hampshire', reports, parsed, rejected, message, complete=complete,
                      evidence={'pageCount': visited, 'total': expected_total, 'lastPage': last_page,
                                'uniqueAcceptedCount': len(reports), 'duplicateRows': duplicate_rows,
                                'conflictingIds': len(conflicts), 'unresolvedDocumentRows': unresolved_documents})


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'No rediscovered collector for source: {source_id}')
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 200):
        raise SourceError('max_pages must be an integer from 1 to 200')
    annual_reason = None
    if source_id == 'massachusetts':
        try:
            return collect_annual(source_id, max_pages=max_pages)
        except SourceError as annual_error:
            annual_reason = str(annual_error)
    limit = max_pages or (24 if source_id == 'massachusetts' else 30)
    client = CLIENT_FACTORY(max_requests=2 * limit + 4, max_bytes=12_000_000, deadline_seconds=300)
    try:
        if source_id == 'massachusetts':
            result = collect_ma_letters(client, max_pages=max_pages)
            result.message += ' Annual report unavailable: ' + annual_reason
        else:
            result = collect_nh_documents(client, max_pages=max_pages)
        result.evidence.update({'requests': client.requests, 'bytes': client.bytes})
        return result
    finally:
        client.close()
