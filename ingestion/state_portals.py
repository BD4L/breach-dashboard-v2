"""Bounded official state portals, independent of the legacy production database.

Indiana has no stable case ID in its annual PDF: identity includes organization
and source dates, never its unstable alphabetical row number. Maryland uses the
public list item ID. Maine explicitly withdrew its public database; failures
remain failures so the store can retain the last valid observations.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
import json
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
import pdfplumber

from ingestion.models import Collection, Report, SourceError
from ingestion.network import PublicClient

PARSER_VERSION = 'state-portals-1'
SOURCES = {
    'indiana': {'id': 'indiana', 'label': 'Indiana', 'jurisdiction': 'IN', 'method': 'Annual report', 'homepage': 'https://www.in.gov/attorneygeneral/consumer-protection-division/id-theft-prevention/security-breaches/'},
    'iowa': {'id': 'iowa', 'label': 'Iowa', 'jurisdiction': 'IA', 'method': 'Annual notices', 'homepage': 'https://www.iowaattorneygeneral.gov/for-consumers/security-breach-notifications'},
    'maine': {'id': 'maine', 'label': 'Maine', 'jurisdiction': 'ME', 'method': 'Public notices', 'homepage': 'https://www.maine.gov/ag/consumer-protection/data-security-breaches'},
    'north_dakota': {'id': 'north_dakota', 'label': 'North Dakota', 'jurisdiction': 'ND', 'method': 'Public notices', 'homepage': 'https://attorneygeneral.nd.gov/consumer-resources/data-breach-notices'},
    'oklahoma': {'id': 'oklahoma', 'label': 'Oklahoma state government', 'jurisdiction': 'OK', 'method': 'Government incidents', 'homepage': 'https://oklahoma.gov/omes/divisions/information-services/cyber-command/notices/cybersecurity-breaches.html'},
    'maryland': {'id': 'maryland', 'label': 'Maryland', 'jurisdiction': 'MD', 'method': 'Public notice lists', 'homepage': 'https://oag.maryland.gov/resources-info/Pages/security-breach-notices.aspx'},
}
DEFAULT_LIMITS = {'indiana': 80, 'iowa': 3, 'maine': 4, 'north_dakota': 4, 'oklahoma': 12, 'maryland': 12}
DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%B %d, %Y', '%b %d, %Y', '%A, %B %d, %Y')


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def key(value):
    return re.sub(r'[^a-z0-9]', '', clean(value).lower())


def _flag(flags, code, message):
    flags.append({'code': code, 'message': message})


def parse_date(value, flags, label, *, today=None):
    raw = clean(value)
    if raw.lower() in {'', '-', '--', 'n/a', 'unknown', 'pending', 'not provided'}:
        return None
    # Source ISO date-time fields express an explicit calendar date.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.]+Z', raw):
        raw = raw[:10]
    parsed = None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            pass
    if parsed is None:
        _flag(flags, 'unparsed_date', f'{label}: {raw[:150]}')
        return None
    if parsed > (today or date.today()):
        _flag(flags, 'future_date', f'{label}: {raw[:150]}')
        return None
    return parsed.isoformat()


def parse_count(value, flags, label):
    raw = clean(value)
    if raw.lower() in {'', '-', '--', 'n/a', 'unknown', 'pending', 'not provided'}:
        return None, 'unknown'
    match = re.fullmatch(r'(>=|≥|<|at least)?\s*(\d+(?:,\d{3})*)', raw, re.I)
    if not match:
        _flag(flags, 'unparsed_count', f'{label}: {raw[:120]}')
        return None, 'unknown'
    count = int(match[2].replace(',', ''))
    if count > 9_007_199_254_740_991:
        raise SourceError('Affected count exceeds the supported integer range')
    return count, 'less_than' if match[1] == '<' else 'at_least' if match[1] else 'exact'


def official_url(base, href, *, host=None):
    url = urljoin(base, str(href))
    parts = urlsplit(url)
    expected = host or urlsplit(base).hostname
    if parts.scheme != 'https' or parts.hostname != expected or parts.username or parts.password or parts.port not in (None, 443):
        raise SourceError('Source supplied a link outside its official HTTPS host')
    return url


def checked(source, reports, parsed, rejected=0, *, message, complete=False, evidence=None):
    if not reports:
        raise SourceError(f'{SOURCES[source]["label"]}: no valid reports; source schema or availability needs review')
    seen = {}
    unique = []
    for report in reports:
        previous = seen.get(report.native_id)
        if previous:
            if previous != report:
                raise SourceError(f'{SOURCES[source]["label"]}: conflicting duplicate source identities')
            rejected += 1
            continue
        seen[report.native_id] = report
        unique.append(report)
    return Collection(source, unique, parsed, rejected, message, complete and rejected == 0, evidence or {})


def discover_year_links(html, base, *, pdf=False, today=None):
    """Use links/options actually published by the source; never guess year URLs."""
    year = (today or date.today()).year
    result = {}
    for node in BeautifulSoup(html, 'html.parser').find_all(['a', 'option']):
        href = node.get('href') if node.name == 'a' else node.get('value')
        if not href:
            continue
        label = clean(node.get_text(' '))
        text = label + ' ' + href
        years = re.findall(r'(?<!\d)(20\d{2})(?!\d)', text)
        if not years or (pdf and not urlsplit(href).path.lower().endswith('.pdf')):
            continue
        candidate = int(years[0])
        if candidate > year or candidate < year - 1:
            continue
        if not pdf and not re.search(r'breach|notification', href, re.I):
            continue
        result[candidate] = official_url(base, href)
    if not result:
        raise SourceError(f'No linked {year} or {year - 1} source archive was found')
    return sorted(result.items(), reverse=True)


IN_HEADERS = {'rowno': 'row', 'mattername': 'organization', 'notificsent': 'notification', 'breachocc': 'breach', 'inaffected': 'state', 'totalaffected': 'total'}


def parse_indiana_tables(tables, document_url, year, *, today=None):
    reports, parsed, rejected, row_numbers = [], 0, 0, []
    for table in tables:
        header = None
        for row in table or []:
            values = [clean(v) for v in row]
            candidate = {IN_HEADERS[key(v)]: i for i, v in enumerate(values) if key(v) in IN_HEADERS}
            if {'row', 'organization', 'notification', 'breach', 'state', 'total'} <= candidate.keys():
                header = candidate
                continue
            if not any(values):
                continue
            if header is None:
                raise SourceError('Indiana: annual PDF table does not have the expected named columns')
            def get(name):
                i = header[name]
                return values[i] if i < len(values) else ''
            if not get('row').isdigit():
                raise SourceError('Indiana: unexpected non-record row inside the annual report table')
            row_numbers.append(int(get('row')))
            parsed += 1
            if len(values) <= max(header.values()) or not get('organization'):
                rejected += 1
                continue
            flags = []
            notification = parse_date(get('notification'), flags, 'Consumer notification sent', today=today)
            breach = parse_date(get('breach'), flags, 'Breach occurred', today=today)
            state_count, qualifier = parse_count(get('state'), flags, 'Indiana residents affected')
            identity_fields = [str(year), get('organization').casefold(),
                               parse_date(get('notification'), [], 'identity', today=date.max) or get('notification'),
                               parse_date(get('breach'), [], 'identity', today=date.max) or get('breach')]
            native = f'{year}-' + sha256(json.dumps(identity_fields, ensure_ascii=False).encode()).hexdigest()[:24]
            _flag(flags, 'derived_identity', 'The annual PDF has no stable case ID. Identity uses organization and source dates; corrections to those fields may appear as a new report.')
            _flag(flags, 'notification_date_only', 'The PDF gives the consumer notification date, not its publication date or the date received by the attorney general.')
            summary = f'Consumer notification sent: {notification or get("notification") or "not reported"}. '
            summary += f'Source-reported total affected: {get("total") or "not reported"}. The displayed count is Indiana residents only.'
            reports.append(Report('indiana', native, get('organization'), document_url,
                                  breach_start=breach, affected_count=state_count, affected_scope='state',
                                  affected_jurisdiction='IN', affected_qualifier=qualifier,
                                  notice_url=document_url, summary=summary, quality_flags=flags, parser_version=PARSER_VERSION))
    if len(row_numbers) != len(set(row_numbers)):
        raise SourceError('Indiana: duplicate annual PDF row numbers')
    return reports, parsed, rejected, row_numbers


def parse_indiana_pdf(content, document_url, year, *, max_pages=80, today=None):
    if not content.startswith(b'%PDF-'):
        raise SourceError('Indiana: linked annual document is not a PDF')
    reports, parsed, rejected, row_numbers = [], 0, 0, []
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            total_pages = len(pdf.pages)
            for page in pdf.pages[:max_pages]:
                tables = page.extract_tables()
                if not tables:
                    raise SourceError('Indiana: a requested PDF page has no extractable table')
                current, count, bad, numbers = parse_indiana_tables(tables, document_url, year, today=today)
                text_numbers = [int(m[1]) for line in (page.extract_text() or '').splitlines()
                                if (m := re.match(r'^\s*(\d+)\s+(?!of\s+\d+\s*$)\S', line))]
                if set(text_numbers) != set(numbers):
                    raise SourceError('Indiana: PDF text and table row numbers disagree')
                reports.extend(current); parsed += count; rejected += bad; row_numbers.extend(numbers)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f'Indiana: PDF extraction failed ({type(exc).__name__})') from exc
    if row_numbers != list(range(1, len(row_numbers) + 1)):
        raise SourceError('Indiana: annual PDF row sequence is incomplete or duplicated')
    used = min(total_pages, max_pages)
    return checked('indiana', reports, parsed, rejected,
                   message=f'Parsed {used} of {total_pages} pages of the linked {year} annual PDF. Older annual reports are outside this collection; no independent annual completeness total is available.',
                   evidence={'pages': used, 'total_pages': total_pages, 'year': year, 'coverage': 'annual_pdf'}, complete=False)


LIST_HEADERS = {
    'datereceived': 'date', 'datereported': 'date', 'date': 'date', 'notificationdate': 'date',
    'company': 'organization', 'companyname': 'organization', 'organization': 'organization',
    'organizationname': 'organization', 'entityname': 'organization', 'businessname': 'organization',
    'business': 'organization', 'name': 'organization',
}


def parse_notice_table(html, source, page_url, *, today=None):
    """Strict named-column tables for public notice lists; no layout-table fallback."""
    soup = BeautifulSoup(html, 'html.parser')
    reports, parsed, rejected = [], 0, 0
    recognized = False
    for table in soup.find_all('table'):
        header = None
        for row in table.find_all('tr'):
            cells = row.find_all(['th', 'td'], recursive=False)
            values = [clean(c.get_text(' ')) for c in cells]
            candidate = {LIST_HEADERS[key(v)]: i for i, v in enumerate(values) if key(v) in LIST_HEADERS}
            if {'date', 'organization'} <= candidate.keys():
                header = candidate; recognized = True; continue
            if header is None or not any(values):
                continue
            parsed += 1
            if len(values) <= max(header.values()):
                rejected += 1; continue
            organization = values[header['organization']]
            links = [a for a in row.find_all('a', href=True) if re.search(r'\.pdf(?:\?|$)|/agviewer/|breach|notification', a['href'], re.I)]
            if not organization or not links:
                rejected += 1; continue
            url = official_url(page_url, links[0]['href'])
            flags = []
            reported = parse_date(values[header['date']], flags, 'Source notification date', today=today)
            # Document paths are stable evidence identities, unlike row positions.
            native = sha256(url.encode()).hexdigest()[:24]
            reports.append(Report(source, native, organization, url, reported_date=reported,
                                  notice_url=url if urlsplit(url).path.lower().endswith('.pdf') else None,
                                  quality_flags=flags, parser_version=PARSER_VERSION))
    if not recognized:
        raise SourceError(f'{SOURCES[source]["label"]}: expected organization/date notification columns were not found')
    return checked(source, reports, parsed, rejected, message='Public notice listing; document details and unvisited archives are outside this collection.', complete=False)


def detect_maine_unavailable(html):
    text = clean(BeautifulSoup(html, 'html.parser').get_text(' ')).lower()
    if re.search(r'public[- ]facing database.{0,50}(?:remain|is|be).{0,15}offline', text):
        raise SourceError('Maine has taken its public-facing breach database offline while it reviews reporting abuse. No current public records can be collected; retain earlier observations.')


def parse_north_dakota_notices(html, page_url, *, today=None):
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.find('main') or soup.find(class_='entry-content') or soup
    heading = ' '.join(h.get_text(' ', strip=True) for h in main.find_all(['h1', 'h2']))
    if not re.search(r'(?:data|security)\s+breach\s+notices', heading, re.I):
        raise SourceError('North Dakota: the response is not a public breach-notice directory')
    reports = []
    for anchor in main.find_all('a', href=True):
        href = anchor['href']
        filename = unquote(urlsplit(href).path.rsplit('/', 1)[-1])
        match = re.fullmatch(r'(20\d{2}-\d{2}-\d{2})-(.+)\.pdf', filename, re.I)
        if not match:
            continue
        url = official_url(page_url, href)
        label = clean(anchor.get_text(' '))
        organization = label if label and not re.fullmatch(r'(?:download|notice|pdf|view)(?:\s+pdf)?', label, re.I) else match[2].replace('-', ' ')
        flags = []
        document_date = parse_date(match[1], flags, 'Document date', today=today)
        _flag(flags, 'document_date_only', 'The dated document path does not establish a publication or attorney-general receipt date.')
        reports.append(Report('north_dakota', filename[:-4], organization, url, notice_url=url,
                              summary=f'Document dated {document_date or match[1]}; affected count and source publication date are not established by the directory.',
                              quality_flags=flags, parser_version=PARSER_VERSION))
    return checked('north_dakota', reports, len(reports), message='Linked public notice documents only; no current directory completeness total is available.', complete=False)


MD_FIELDS = ('Title', 'Date_x0020_Received', 'Case_x0020_No_x002e_', 'No_x0020_of_x0020_Maryland_x0020', 'Information_x0020_Breached', 'How_x0020_Breach_x0020_Occurred')


def discover_maryland_lists(html, *, today=None):
    year = (today or date.today()).year
    names = sorted(set(re.findall(r'Security-Breach-Notices-(20\d{2})', html)), reverse=True)
    names = [int(y) for y in names if int(y) <= year]
    if not names:
        raise SourceError('Maryland: the public page no longer declares its annual notice lists')
    return names


def maryland_endpoint(year):
    return ("https://oag.maryland.gov/resources-info/_api/web/lists/getbytitle("
            f"'Security-Breach-Notices-{year}')/items?$top=200&$select=" + ','.join(MD_FIELDS) + '&$orderby=Date_x0020_Received%20desc')


def parse_maryland_page(data, year, *, today=None):
    if not isinstance(data, dict) or not isinstance(data.get('d'), dict) or not isinstance(data['d'].get('results'), list):
        raise SourceError('Maryland: unexpected public-list JSON schema')
    rows = data['d']['results']
    reports, rejected = [], 0
    for row in rows:
        if not isinstance(row, dict) or not all(k in row for k in MD_FIELDS):
            raise SourceError('Maryland: public-list fields have changed')
        organization, case = clean(row['Title']), clean(row['Case_x0020_No_x002e_'])
        if not organization or not case:
            rejected += 1; continue
        case = unquote(case)
        if '/' in case or '\\' in case or case in {'.', '..'}:
            raise SourceError('Maryland: unsafe document filename')
        flags = []
        reported = parse_date(row['Date_x0020_Received'], flags, 'Date received', today=today)
        count, qualifier = parse_count(row['No_x0020_of_x0020_Maryland_x0020'], flags, 'Maryland residents affected')
        metadata = row.get('__metadata') or {}
        item = re.search(r'/Items\((\d+)\)$', str(metadata.get('uri', '')), re.I)
        native = f'{year}:item-{item[1]}' if item else f'{year}:{case.casefold()}'
        notice = f'https://oag.maryland.gov/resources-info/SBN%20Documents/{year}/{quote(case, safe="")}'
        information = clean(row['Information_x0020_Breached'])
        summary = clean(row['How_x0020_Breach_x0020_Occurred'])[:1500]
        reports.append(Report('maryland', native, organization, SOURCES['maryland']['homepage'],
                              reported_date=reported, affected_count=count, affected_scope='state',
                              affected_jurisdiction='MD', affected_qualifier=qualifier,
                              data_types=[information] if information else [], notice_url=notice,
                              summary=summary, quality_flags=flags, parser_version=PARSER_VERSION))
    next_url = data['d'].get('__next')
    if next_url is not None:
        next_url = official_url(maryland_endpoint(year), next_url)
        expected = urlsplit(maryland_endpoint(year)).path
        if unquote(urlsplit(next_url).path) != unquote(expected):
            raise SourceError('Maryland: pagination left the declared public notice list')
        top = parse_qs(urlsplit(next_url).query).get('$top', ['200'])
        if len(top) != 1 or not top[0].isdigit() or not 1 <= int(top[0]) <= 200:
            raise SourceError('Maryland: pagination exceeded its per-page row budget')
    return reports, len(rows), rejected, next_url


def discover_oklahoma_feed(html, page_url):
    feeds = BeautifulSoup(html, 'html.parser').select('[data-newsfeedapiurl]')
    if len(feeds) != 1:
        raise SourceError('Oklahoma: expected one official breach newsfeed component')
    return official_url(page_url, feeds[0]['data-newsfeedapiurl'])


def parse_oklahoma_feed(data, page_url, *, today=None):
    if not isinstance(data, list) or not data:
        raise SourceError('Oklahoma: official government-incident feed is empty or changed')
    reports = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get('newsUrl'), str) or not isinstance(item.get('title'), str):
            raise SourceError('Oklahoma: government-incident feed fields have changed')
        title = clean(item['title'])
        if ':' not in title:
            raise SourceError('Oklahoma: notice title no longer identifies the affected agency')
        organization = title.split(':', 1)[1].strip()
        if not organization:
            raise SourceError('Oklahoma: notice omitted the affected agency')
        url = official_url(page_url, item['newsUrl'])
        if '/cybersecurity-breaches/' not in urlsplit(url).path:
            raise SourceError('Oklahoma: feed linked outside the government-incident directory')
        flags = []
        raw_incident = re.sub(r'\s*Incident\s*$', '', title.split(':', 1)[0], flags=re.I).strip(' ,')
        raw_incident = raw_incident.replace('Dec.', 'Dec').replace('Sept.', 'Sep')
        breach = None
        if re.search(r'\b\d{1,2},?\s+20\d{2}\b', raw_incident):
            breach = parse_date(raw_incident, flags, 'Incident date', today=today)
        reports.append(Report('oklahoma', urlsplit(url).path, organization, url, breach_start=breach,
                              summary=f'{title}. This source covers Oklahoma state-government incidents, not all private-sector breach notifications.',
                              quality_flags=flags, parser_version=PARSER_VERSION))
    return reports


def enrich_oklahoma_detail(report, html, *, today=None):
    soup = BeautifulSoup(html, 'html.parser')
    created = soup.select_one('[aria-label="created-date"]')
    if created:
        report.published_date = parse_date(created.get_text(' '), report.quality_flags, 'Notice publication date', today=today)
    # lastModified is deliberately not treated as a publication/incident date.
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows:
            continue
        header = [key(c.get_text(' ')) for c in rows[0].find_all(['th', 'td'])]
        if 'agency' not in header or 'typeofdata' not in header:
            continue
        for row in rows[1:]:
            cells = row.find_all(['th', 'td'])
            if len(cells) != len(header):
                continue
            if clean(cells[header.index('agency')].get_text(' ')).casefold() == report.organization.casefold():
                text = clean(cells[header.index('typeofdata')].get_text(' '))
                report.data_types = [text] if text else []
    if report.published_date is None:
        _flag(report.quality_flags, 'publication_date_unavailable', 'No valid explicit creation date was found on the official notice page.')
    return report


def _json(response, source):
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError(f'{source}: response was not valid JSON') from exc


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown state portal: {source_id}')
    limit = DEFAULT_LIMITS[source_id] if max_pages is None else max_pages
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise SourceError('max_pages must be an integer between 1 and 200')
    today = date.today()
    client = PublicClient(max_requests=min(limit + 4, 40), max_bytes=15_000_000, deadline_seconds=180)
    homepage = SOURCES[source_id]['homepage']
    try:
        first = client.request(homepage)
        if source_id == 'indiana':
            year, document_url = discover_year_links(first.text, first.url, pdf=True, today=today)[0]
            return parse_indiana_pdf(client.request(document_url).content, document_url, year, max_pages=limit, today=today)
        if source_id == 'maine':
            detect_maine_unavailable(first.text)
            return parse_notice_table(first.text, source_id, first.url, today=today)
        if source_id == 'north_dakota':
            return parse_north_dakota_notices(first.text, first.url, today=today)
        if source_id == 'iowa':
            years = discover_year_links(first.text, first.url, today=today)
            reports, parsed, rejected = [], 0, 0
            for year, url in years[:limit]:
                response = client.request(url)
                result = parse_notice_table(response.text, source_id, response.url, today=today)
                reports.extend(result.reports); parsed += result.parsed; rejected += result.rejected
            return checked(source_id, reports, parsed, rejected, message=f'Linked current/prior-year archives only ({len(years[:limit])} archive pages); publication coverage and notice-document details remain unverified.', complete=False)
        if source_id == 'maryland':
            years = discover_maryland_lists(first.text, today=today)
            year = years[0]
            url = maryland_endpoint(year)
            visited, reports, parsed, rejected, pages = set(), [], 0, 0, 0
            stop = ''
            while url and pages < limit:
                if url in visited:
                    raise SourceError('Maryland: pagination repeated a page')
                visited.add(url)
                try:
                    response = client.request(url, headers={'Accept': 'application/json;odata=verbose'})
                    current, count, bad, url = parse_maryland_page(_json(response, 'Maryland'), year, today=today)
                except SourceError as exc:
                    if not reports:
                        raise
                    stop = f' Collection stopped: {exc}'
                    break
                reports.extend(current); parsed += count; rejected += bad; pages += 1
            missing = f' No {today.year} list is currently declared by the official page.' if year < today.year else ''
            remaining = ' More API pages remain.' if url else ''
            return checked(source_id, reports, parsed, rejected,
                           message=f'Collected {pages} API pages from the latest declared {year} list. Other annual lists and notice PDFs are outside this collection.{missing}{remaining}{stop}',
                           complete=False, evidence={'pages': pages, 'year': year, 'coverage': 'latest_declared_annual_list'})
        feed_url = discover_oklahoma_feed(first.text, first.url)
        reports = parse_oklahoma_feed(_json(client.request(feed_url), 'Oklahoma'), first.url, today=today)
        enriched = 0
        stop = ''
        for report in reports[:limit]:
            try:
                enrich_oklahoma_detail(report, client.request(report.source_url).text, today=today)
                enriched += 1
            except SourceError as exc:
                _flag(report.quality_flags, 'detail_unavailable', str(exc)[:250])
                stop = f' Detail checks stopped: {exc}'
                break
        complete = enriched == len(reports) and not stop and all(r.published_date for r in reports)
        return checked(source_id, reports, len(reports),
                       message=f'Official Oklahoma state-government incident feed only: {len(reports)} listed notices, {enriched} detail pages checked. This is not a comprehensive private-sector breach register.{stop}',
                       complete=complete, evidence={'pages': enriched + 2, 'coverage': 'state_government_incidents'})
    except SourceError as exc:
        if source_id == 'north_dakota' and '404' in str(exc):
            raise SourceError('North Dakota: the public breach directory returns HTTP 404; a current official replacement has not been verified. Retain earlier observations.') from exc
        raise
    finally:
        client.close()
