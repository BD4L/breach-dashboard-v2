"""Three conservative public-source adapters. Parsing is separate from transport."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
import re
from urllib.parse import parse_qs, urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import pdfplumber

from ingestion.models import Collection, Report, SOURCES, SourceError
from ingestion.network import PublicClient

PARSER_VERSION = 'pilot-2'
CA_MAX_PAGES = 120
HHS_MAX_PAGES = 12
MAX_CONFIGURABLE_PAGES = 200
UNKNOWN = {'', 'n/a', 'na', 'unknown', 'pending', 'not provided', 'none', 'various'}


def clean(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def key(value) -> str:
    return re.sub(r'[^a-z0-9]', '', clean(value).lower())


def flag(flags, code, message):
    flags.append({'code': code, 'message': message})


def parse_date(value, flags, field, *, today=None):
    raw = clean(value)
    if raw.lower() in UNKNOWN:
        return None
    parsed = None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y', '%d-%b-%y'):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            pass
    if parsed is None:
        flag(flags, 'unparsed_date', f'{field}: {raw}')
        return None
    if parsed > (today or date.today()):
        flag(flags, 'future_date', f'{field}: {raw}')
        return None
    return parsed.isoformat()


def parse_count(value, flags):
    raw = clean(value)
    if raw.lower() in UNKNOWN:
        return None, 'unknown'
    match = re.fullmatch(r'(?P<qual><|>=|≥|at least)?\s*(?P<count>\d+(?:,\d{3})*)', raw, re.I)
    if not match:
        flag(flags, 'unparsed_count', f'Affected count: {raw}')
        return None, 'unknown'
    qualifier = 'less_than' if match['qual'] == '<' else 'at_least' if match['qual'] else 'exact'
    return int(match['count'].replace(',', '')), qualifier


def official_url(base, value, host):
    url = urljoin(base, value)
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != host or parts.username or parts.password:
        raise SourceError('Source supplied an unexpected evidence link')
    return url


def _checked(source, reports, parsed, rejected, message='', **kwargs):
    if not reports:
        raise SourceError(f'{source}: no valid reports parsed; empty or changed source schema')
    ids = [report.native_id for report in reports]
    if len(ids) != len(set(ids)):
        raise SourceError(f'{source}: duplicate native report IDs; refusing ambiguous snapshot')
    return Collection(source, reports, parsed, rejected, message, **kwargs)


def discover_ma_reports(html: str, *, today=None):
    """Discover current and previous report years, covering year rollover revisions."""
    year = (today or date.today()).year
    by_year = {}
    for link in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
        href = link['href']
        if not re.search(r'data[- ]breach', href + ' ' + link.get_text(' '), re.I):
            continue
        match = re.search(r'\b(20\d{2})\b', href + ' ' + link.get_text(' '))
        if match and int(match[1]) in (year, year - 1) and ('/doc/' in href or '.pdf' in href.lower()):
            by_year[int(match[1])] = official_url(SOURCES['massachusetts']['homepage'], href, 'www.mass.gov')
    if not by_year:
        raise SourceError(f'Massachusetts: no linked {year} or {year - 1} annual report found')
    return sorted(by_year.items(), reverse=True)


MA_HEADERS = {
    'breachnumber': 'id', 'breachid': 'id',
    'datereportedtooca': 'reported', 'datereported': 'reported', 'datereportedtoocabr': 'reported',
    'reportingorganizationname': 'organization', 'organizationname': 'organization',
    'reportingorganizationtype': 'type', 'maresidentsaffected': 'count',
    'massachusettsresidentsaffected': 'count', 'ssnbreached': 'Social Security numbers',
    'medicalrecordsbreached': 'Medical records', 'financialaccountbreached': 'Financial accounts',
    'driverslicensesbreached': "Driver's licenses", 'creditdebitnumbersbreached': 'Credit/debit card numbers',
}


def parse_ma_tables(tables, document_url: str, *, today=None):
    """Parse pdfplumber rows with repeated headers and headerless continuation pages."""
    reports, parsed, rejected, header = [], 0, 0, None
    for table in tables:
        for row in table or []:
            values = [clean(cell) for cell in row]
            if not any(values):
                continue
            candidate = {MA_HEADERS[key(cell)]: i for i, cell in enumerate(values) if key(cell) in MA_HEADERS}
            if {'id', 'organization', 'reported', 'count'} <= candidate.keys():
                header = candidate
                continue
            if header is None:
                if sum(bool(value) for value in values) > 1:
                    raise SourceError('Massachusetts: multi-column rows appeared before a validated report header')
                continue
            def get(name):
                index = header.get(name, len(values))
                return values[index] if index < len(values) else ''
            native_id = get('id')
            if not re.fullmatch(r'20\d{2}-\d+', native_id):
                # Any row that resembles report data must be accounted for, not silently dropped.
                if native_id or get('organization'):
                    parsed += 1
                    rejected += 1
                continue
            parsed += 1
            if not get('organization') or len(values) <= max(header.values()):
                rejected += 1
                continue
            flags = []
            reported = parse_date(get('reported'), flags, 'Date reported to OCABR', today=today)
            count, qualifier = parse_count(get('count'), flags)
            data_types = [label for label in MA_HEADERS.values() if label not in {'id','organization','reported','type','count'}
                          and get(label).lower() in {'yes', 'y', 'true', 'x'}]
            reports.append(Report('massachusetts', native_id, get('organization'), document_url,
                                  reported_date=reported, affected_count=count, affected_scope='state',
                                  affected_jurisdiction='MA', affected_qualifier=qualifier,
                                  data_types=sorted(set(data_types)), notice_url=document_url,
                                  summary='Massachusetts annual notification report. Count covers Massachusetts residents.',
                                  quality_flags=flags, parser_version=PARSER_VERSION))
    return _checked('massachusetts', reports, parsed, rejected)


def parse_ma_pdf(content: bytes, url: str, *, today=None, expected_count=None):
    """Extract rows conservatively; text checks detect omissions, not completeness.

    Only an independently established annual source count can establish full
    coverage. The current collector has no validated count feed and stays partial.
    """
    if not content.startswith(b'%PDF-'):
        raise SourceError('Massachusetts: annual report response is not a PDF')
    if expected_count is not None and (isinstance(expected_count, bool)
                                       or not isinstance(expected_count, int) or expected_count < 1):
        raise SourceError('Massachusetts: independent annual report count must be a positive integer')
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            if len(pdf.pages) > 500:
                raise SourceError('Massachusetts: annual report exceeds 500-page parse budget')
            tables = []
            for number, page in enumerate(pdf.pages, 1):
                page_tables = page.extract_tables()
                if not page_tables:
                    raise SourceError(f'Massachusetts: page {number} has no validated table extraction; coverage unknown')
                page_text = page.extract_text() or ''
                text_ids = set(re.findall(r'\b20\d{2}-\d+\b', page_text))
                table_ids = {match for table in page_tables for row in table or [] for cell in row or []
                             for match in re.findall(r'\b20\d{2}-\d+\b', clean(cell))}
                if not text_ids or not table_ids or text_ids != table_ids:
                    raise SourceError(f'Massachusetts: page {number} text/table report IDs disagree or cannot be validated')
                tables.extend(page_tables)
            result = parse_ma_tables(tables, url, today=today)
            if expected_count is not None and len(result.reports) != expected_count:
                raise SourceError('Massachusetts: parsed reports do not match the independent annual source count')
            result.complete = expected_count is not None and result.rejected == 0
            result.message = ('Annual source count matched parsed reports.' if result.complete else
                              'PDF coverage remains unverified: no independent annual source count is available.')
            return result
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f'Massachusetts PDF extraction failed: {type(exc).__name__}') from exc


def _find_table(soup, required):
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            headings = row.find_all('th', recursive=False)
            if not headings:
                continue
            headers = {key(h.get('aria-label') or h.get_text(' ', strip=True)): i for i, h in enumerate(headings)}
            if required <= headers.keys():
                return table, headers
    raise SourceError('Expected named report-table headers not found; source schema may have changed')


def parse_ca_listing(html: str, url=None, *, today=None):
    url = url or SOURCES['california']['homepage']
    soup = BeautifulSoup(html, 'html.parser')
    table, headers = _find_table(soup, {'organizationname', 'datesofbreach', 'reporteddate'})
    reports, parsed, rejected = [], 0, 0
    rejected_notes = []
    for row in table.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if not cells:
            continue
        parsed += 1
        if len(cells) <= max(headers.values()):
            rejected += 1
            continue
        org_cell = cells[headers['organizationname']]
        link = org_cell.find('a', href=True)
        if not link:
            rejected += 1
            rejected_notes.append('Missing original-source link')
            continue
        source_url = official_url(url, link['href'], 'oag.ca.gov')
        native = re.search(r'/reports/(sb24-\d+)(?:/|$)', urlsplit(source_url).path)
        if not native:
            rejected += 1
            rejected_notes.append('Missing native report identifier')
            continue
        if not clean(org_cell.get_text(' ')):
            rejected += 1
            rejected_notes.append(f'{native[1]}: organization name missing from official listing')
            continue
        flags = []
        reported = parse_date(cells[headers['reporteddate']].get_text(' '), flags, 'Reported date', today=today)
        raw_breach = clean(cells[headers['datesofbreach']].get_text(' '))
        breach = None
        if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', raw_breach):
            breach = parse_date(raw_breach, flags, 'Breach date', today=today)
        elif raw_breach.lower() not in UNKNOWN:
            # Lists of two dates are not necessarily a continuous start/end range.
            flag(flags, 'multiple_or_unparsed_breach_dates', f'Source breach dates: {raw_breach}')
        reports.append(Report('california', native[1], clean(org_cell.get_text(' ')), source_url,
                              reported_date=reported, breach_start=breach,
                              summary='California sample-notice listing. Affected count and data types require notice review.',
                              quality_flags=flags, parser_version=PARSER_VERSION))
    result = _checked('california', reports, parsed, rejected)
    next_url, terminal, page_number, total_pages = ca_pagination(soup, url)
    result.complete = terminal
    result.message = '; '.join(rejected_notes)
    result.evidence = {'pageNumber': page_number, 'totalPages': total_pages}
    if not terminal and not next_url:
        result.message += ' Listing pagination could not establish coverage.'
    return result, next_url


def ca_pagination(soup, url):
    """Validate the source's active/next/last controls before claiming completion."""
    def page_of(link):
        query = parse_qs(urlsplit(link).query)
        value = query.get('page', ['0'])
        if len(value) != 1 or not re.fullmatch(r'\d+', value[0]):
            raise SourceError('California: invalid listing page offset')
        return int(value[0])
    current = page_of(url)
    pager = soup.select_one('ul.pagination, ul.pager')
    if pager is None:
        return None, False, current + 1, None
    active = pager.select_one('li.active, li.pager-current')
    if active is None or clean(active.get_text(' ')) != str(current + 1):
        raise SourceError('California: displayed page does not match requested page')
    next_link = pager.select_one('li.next a[href], li.pager-next a[href], a[rel="next"][href], a[title="Go to next page"][href]')
    last_link = pager.select_one('li.pager-last a[href], a[title="Go to last page"][href]')
    total = page_of(official_url(url, last_link['href'], 'oag.ca.gov')) + 1 if last_link else None
    if next_link:
        next_url = official_url(url, next_link['href'], 'oag.ca.gov')
        if page_of(next_url) != current + 1:
            raise SourceError('California: next link skips or repeats a listing page')
        if total is not None and total <= current + 1:
            raise SourceError('California: next and last page controls disagree')
        return next_url, False, current + 1, total
    later_links = [a for a in pager.find_all('a', href=True)
                   if page_of(official_url(url, a['href'], 'oag.ca.gov')) > current]
    if later_links:
        raise SourceError('California: next-page control missing while later listing pages remain')
    previous = pager.select_one('li.prev a[href], li.pager-previous a[href], a[title="Go to previous page"][href]')
    # The actual final source page exposes its active number and previous control.
    # A removed/unknown pager is not evidence that the entire listing is complete.
    terminal = previous is not None and page_of(official_url(url, previous['href'], 'oag.ca.gov')) == current - 1
    return None, terminal, current + 1, current + 1 if terminal else total



@dataclass
class HHSPage:
    collection: Collection
    table_id: str
    total: int
    first: int
    last: int


def parse_hhs_table(html: str, *, today=None):
    soup = BeautifulSoup(html, 'html.parser')
    required = {'nameofcoveredentity', 'state', 'individualsaffected', 'breachsubmissiondate'}
    table, headers = _find_table(soup, required)
    container = table.find_parent('div', class_='ui-datatable')
    if not container or not container.get('id'):
        raise SourceError('HHS: report table has no pagination identity')
    pagination = container.select_one('.ui-paginator-current')
    match = re.search(r'Displaying\s+([\d,]+)\s*-\s*([\d,]+)\s+of\s+([\d,]+)', pagination.get_text(' ') if pagination else '')
    if not match:
        raise SourceError('HHS: cannot establish result count/pagination coverage')
    first, last, total = [int(v.replace(',', '')) for v in match.groups()]
    reports, parsed, rejected = [], 0, 0
    for row in table.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if not cells or 'ui-expanded-row-content' in row.get('class', []):
            continue
        parsed += 1
        native = row.get('data-rk', '')
        if not re.fullmatch(r'\d+', native) or len(cells) <= max(headers.values()):
            rejected += 1
            continue
        def get(name):
            return clean(cells[headers[name]].get_text(' ')) if name in headers else ''
        organization = get('nameofcoveredentity')
        if not organization:
            rejected += 1
            continue
        flags = []
        reported = parse_date(get('breachsubmissiondate'), flags, 'Breach submission date', today=today)
        count, qualifier = parse_count(get('individualsaffected'), flags)
        # State is the entity's address, not the jurisdiction of the affected count.
        summary = get('webdescription') or '; '.join(filter(None, [get('typeofbreach'), get('locationofbreachedinformation')]))
        reports.append(Report('hhs', native, organization,
                              'https://ocrportal.hhs.gov/ocr/breach/breach_report_hip.jsf',
                              reported_date=reported, affected_count=count, affected_scope='reported',
                              affected_qualifier=qualifier, summary=summary,
                              quality_flags=flags, parser_version=PARSER_VERSION))
    if parsed != last - first + 1:
        raise SourceError('HHS: parsed table row count differs from portal pagination count')
    return HHSPage(_checked('hhs', reports, parsed, rejected), container['id'], total, first, last)


def hhs_form(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', id='ocrForm')
    if not form:
        raise SourceError('HHS: public report navigation form is missing')
    data = {el['name']: el.get('value', '') for el in form.select('input[type="hidden"][name]')}
    if not data.get('javax.faces.ViewState'):
        raise SourceError('HHS: navigation state is missing')
    # URL session tokens are transport-only, never report identity or exported links.
    action = official_url(url, form.get('action', url), 'ocrportal.hhs.gov')
    return form, action, data


def hhs_navigation(html, url):
    form, action, data = hhs_form(html, url)
    link = next((link for link in form.find_all('a') if clean(link.get_text(' ')) == 'View HIPAA Breach Reports'), None)
    if not link:
        raise SourceError('HHS: View HIPAA Breach Reports action not found')
    href = link.get('href', '')
    if href and href != '#':
        return official_url(url, href, 'ocrportal.hhs.gov'), None
    match = re.search(r"\{'([^']+)':'[^']+'\}", link.get('onclick', ''))
    if not match:
        raise SourceError('HHS: unsupported public navigation action')
    data[match[1]] = match[1]
    return action, data


def hhs_page_request(table_id, first, page_size, data):
    return {**data, 'javax.faces.partial.ajax': 'true', 'javax.faces.source': table_id,
            'javax.faces.partial.execute': table_id, 'javax.faces.partial.render': table_id,
            'javax.faces.behavior.event': 'page', 'javax.faces.partial.event': 'page',
            f'{table_id}_pagination': 'true', f'{table_id}_first': str(first),
            f'{table_id}_rows': str(page_size), f'{table_id}_skipChildren': 'true',
            f'{table_id}_encodeFeature': 'true'}


def hhs_partial_response(xml, table_id):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SourceError('HHS: pagination did not return the expected public XML response') from exc
    if root.find('.//error') is not None or root.find('.//redirect') is not None:
        raise SourceError('HHS: pagination session failed or redirected')
    table_html, view_state = None, None
    for update in root.findall('.//update'):
        if update.get('id') == table_id:
            table_html = update.text
        if 'javax.faces.ViewState' in update.get('id', ''):
            view_state = update.text
    if not table_html:
        raise SourceError('HHS: pagination response omitted the report table')
    return table_html, view_state



def hhs_page_html(fragment, template, table_id, expected_first, total):
    """PrimeFaces pagination returns row fragments; reuse captured named headers."""
    soup = BeautifulSoup(fragment, 'html.parser')
    if soup.find('table'):
        return fragment
    rows = soup.find_all('tr', recursive=False)
    if not rows:
        raise SourceError('HHS: pagination returned no report rows')
    try:
        indexes = [int(row['data-ri']) for row in rows]
    except (KeyError, ValueError) as exc:
        raise SourceError('HHS: pagination rows omitted their source offsets') from exc
    if indexes != list(range(expected_first, expected_first + len(rows))) or indexes[-1] >= total:
        raise SourceError('HHS: pagination returned noncontiguous or unexpected source offsets')
    original = BeautifulSoup(template, 'html.parser').find('div', id=table_id)
    if original is None or original.find('tbody') is None:
        raise SourceError('HHS: original pagination header template is missing')
    body = original.find('tbody')
    body.clear()
    for row in rows:
        body.append(row)
    original.select_one('.ui-paginator-current').string = f'(Displaying {indexes[0] + 1} - {indexes[-1] + 1} of {total})'
    return str(original)


def collect(source_id: str, *, max_pages: int | None = None) -> Collection:
    if source_id not in {'massachusetts', 'california', 'hhs'}:
        raise SourceError(f'Unknown source: {source_id}')
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int)
                                  or not 1 <= max_pages <= MAX_CONFIGURABLE_PAGES):
        raise SourceError(f'max_pages must be an integer from 1 to {MAX_CONFIGURABLE_PAGES}')
    page_limit = max_pages if max_pages is not None else CA_MAX_PAGES if source_id == 'california' else HHS_MAX_PAGES
    client = PublicClient(max_requests=page_limit * 2 + 8 if source_id != 'massachusetts' else 12,
                          max_bytes=40_000_000 if source_id == 'california' else 15_000_000,
                          deadline_seconds=540 if source_id == 'california' else 240)
    try:
        if source_id == 'massachusetts':
            landing = client.request(SOURCES[source_id]['homepage'])
            links = discover_ma_reports(landing.text)
            batches = [parse_ma_pdf(client.request(url).content, url) for _, url in links]
            result = _checked(source_id, [r for b in batches for r in b.reports],
                              sum(b.parsed for b in batches), sum(b.rejected for b in batches))
            years = ', '.join(str(year) for year, _ in links)
            current_year_linked = date.today().year in {year for year, _ in links}
            result.complete = current_year_linked and all(batch.complete for batch in batches)
            result.message = f'Annual reports {years}; extracted rows checked. Earlier report years excluded.'
            if not all(batch.complete for batch in batches):
                result.message += ' PDF coverage remains unverified without independent annual source counts.'
            if not current_year_linked:
                result.message += ' Current-year report not linked yet.'
        elif source_id == 'california':
            url, seen, batches = SOURCES[source_id]['homepage'], set(), []
            for _ in range(page_limit):
                if url in seen:
                    raise SourceError('California: pagination repeated a page')
                seen.add(url)
                response = client.request(url)
                batch, url = parse_ca_listing(response.text, response.url)
                batches.append(batch)
                if not url:
                    break
            result = _checked(source_id, [r for b in batches for r in b.reports],
                              sum(b.parsed for b in batches), sum(b.rejected for b in batches))
            result.complete = url is None and batches[-1].complete
            total_pages = batches[0].evidence.get('totalPages') or batches[-1].evidence.get('totalPages')
            covered = f'{len(batches)} of {total_pages}' if total_pages else str(len(batches))
            result.message = f'Collected {covered} listing pages ({result.parsed} source reports). '
            result.message += ('Complete listing; original notice links retained without PDF enrichment.' if result.complete else
                               f'Page limit {page_limit} reached or pagination unverified; older pages excluded, prior saved reports retained.')
            rejection_messages = [batch.message for batch in batches if batch.rejected and batch.message]
            if rejection_messages:
                result.message += ' Withheld rows: ' + '; '.join(rejection_messages)
        else:
            front = client.request(SOURCES[source_id]['homepage'])
            action, data = hhs_navigation(front.text, front.url)
            response = client.request(action, data=data)
            _, action, data = hhs_form(response.text, response.url)
            template = response.text
            selected_tab = BeautifulSoup(template, 'html.parser').select_one('.ui-tabs-nav [aria-selected="true"]')
            if selected_tab is None or clean(selected_tab.get_text(' ')) != 'Under Investigation':
                raise SourceError('HHS: expected HIPAA Under Investigation view is not selected')
            page = parse_hhs_table(template)
            batches, total, table_id = [page.collection], page.total, page.table_id
            if page.first != 1:
                raise SourceError('HHS: initial report page did not begin at row 1')
            page_size = page.last
            for _ in range(page_limit - 1):
                if page.last >= total:
                    break
                first = page.last
                response = client.request(action, data=hhs_page_request(table_id, first, page_size, data),
                                          headers={'Faces-Request': 'partial/ajax'})
                table_html, view_state = hhs_partial_response(response.text, table_id)
                if view_state:
                    data['javax.faces.ViewState'] = view_state
                page = parse_hhs_table(hhs_page_html(table_html, template, table_id, first, total))
                if page.first != first + 1 or page.total != total or page.table_id != table_id:
                    raise SourceError('HHS: pagination coverage changed during collection; retry next run')
                batches.append(page.collection)
            result = _checked(source_id, [r for b in batches for r in b.reports],
                              sum(b.parsed for b in batches), sum(b.rejected for b in batches))
            result.complete = page.last >= total
            result.message = f'HIPAA Under Investigation: {result.parsed} of {total} reports. Archive and Part 2 excluded.'
            if not result.complete:
                result.message += ' Page cap reached; incomplete current dataset.'
        result.evidence = {'requests': client.requests, 'bytes': client.bytes,
                           'pageCount': len(batches)}
        return result
    finally:
        client.close()
