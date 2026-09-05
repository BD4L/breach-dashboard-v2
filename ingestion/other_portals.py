"""Public state listings: cheap collection is independent of PDF enrichment.

No database clients, search services, guessed PDF URLs, or credentials are used.
New Jersey and New Hampshire remain explicit failures when their public listing
blocks anonymous access; an HTTP200 challenge is never an empty success.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
import hashlib
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ingestion.models import Collection, Report, SourceError
from ingestion.network import PublicClient

PARSER_VERSION = 'other-portals-1'
SOURCES = {
    'new_jersey': {'id': 'new_jersey', 'label': 'New Jersey', 'jurisdiction': 'NJ', 'method': 'Public notices', 'homepage': 'https://www.cyber.nj.gov/threat-landscape/public-data-breaches'},
    'wisconsin': {'id': 'wisconsin', 'label': 'Wisconsin', 'jurisdiction': 'WI', 'method': 'Public notices', 'homepage': 'https://datcp.wi.gov/Pages/Programs_Services/DataBreaches.aspx'},
    'montana': {'id': 'montana', 'label': 'Montana', 'jurisdiction': 'MT', 'method': 'Public notices', 'homepage': 'https://dojmt.gov/office-of-consumer-protection/reported-data-breaches/'},
    'washington': {'id': 'washington', 'label': 'Washington', 'jurisdiction': 'WA', 'method': 'Public notices', 'homepage': 'https://www.atg.wa.gov/data-breach-notifications'},
    'south_carolina': {'id': 'south_carolina', 'label': 'South Carolina', 'jurisdiction': 'SC', 'method': 'Public notices', 'homepage': 'https://consumer.sc.gov/identity-theft-unit/security-breach-notices'},
    'delaware': {'id': 'delaware', 'label': 'Delaware', 'jurisdiction': 'DE', 'method': 'Public notices', 'homepage': 'https://attorneygeneral.delaware.gov/fraud/cpu/securitybreachnotification/database/'},
    'new_hampshire': {'id': 'new_hampshire', 'label': 'New Hampshire', 'jurisdiction': 'NH', 'method': 'Public notices', 'homepage': 'https://www.doj.nh.gov/citizens/consumer-protection-antitrust-bureau/security-breach-notifications'},
}


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '').replace('\u200b', '').replace('\ufeff', '')).strip()


def key(value):
    return re.sub(r'[^a-z0-9]', '', clean(value).lower())


def flag(flags, code, message):
    flags.append({'code': code, 'message': clean(message)[:500]})


UNKNOWN = {'', 'n/a', 'na', 'unknown', 'pending', 'various', 'not provided', 'none', 'tbd'}
DATE_TOKEN = r'\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'


def _exact_date(raw, today):
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%B %d, %Y', '%B %d %Y', '%b %d, %Y'):
        try:
            value = datetime.strptime(raw, fmt).date()
            return value.isoformat() if value <= today else None
        except ValueError:
            pass
    return None


def parse_date(value, flags, field='Date', *, today=None):
    """Preserve ambiguous dates as unknown, never replace one with collection time."""
    raw = clean(value)
    if raw.lower() in UNKNOWN:
        return None
    today = today or date.today()
    # Observed South Carolina typo, with the original spelling retained in evidence.
    normalized = re.sub(r'^(\d{1,2}/\d{1,2}),\s*(\d{4})$', r'\1/\2', raw)
    exact = _exact_date(normalized, today)
    if exact:
        if normalized != raw:
            flag(flags, 'normalized_date_separator', f'{field}: {raw}')
        return exact
    # Delaware appends this annotation to an otherwise unambiguous reported date.
    stripped = re.sub(r'\s*[-–]?\s*\(\s*Addendum notices?\s*\)\s*$', '', normalized, flags=re.I).strip()
    annotated = _exact_date(stripped, today)
    if annotated:
        flag(flags, 'date_annotation', f'{field}: {raw}')
        return annotated
    flag(flags, 'unparsed_date', f'{field}: {raw}')
    return None


def date_range(value, flags, *, today=None):
    raw = clean(value)
    if raw.lower() in UNKNOWN:
        return None, None
    today = today or date.today()
    exact = _exact_date(raw, today)
    if exact:
        return exact, None
    match = re.fullmatch(rf'(?:between\s+)?({DATE_TOKEN})\s*(?:-|–|—|to|through)\s*({DATE_TOKEN})', raw, re.I)
    if match is None:
        match = re.fullmatch(rf'between\s+({DATE_TOKEN})\s+and\s+({DATE_TOKEN})', raw, re.I)
    if match:
        start, end = (_exact_date(match[i], today) for i in (1, 2))
        if start and end and start <= end:
            return start, end
    flag(flags, 'unparsed_date', f'Date of breach: {raw}')
    return None, None


def parse_count(value, flags):
    raw = clean(value)
    if raw.lower() in UNKNOWN or raw.lower().startswith('unknown'):
        return None, 'unknown'
    match = re.fullmatch(r'(?P<qual><|>=|≥|at least)?\s*(?P<count>\d+(?:,\d{3})*)(?P<plus>\+)?', raw, re.I)
    if match:
        qualifier = 'less_than' if match['qual'] == '<' else 'at_least' if match['qual'] or match['plus'] else 'exact'
        return int(match['count'].replace(',', '')), qualifier
    flag(flags, 'unparsed_count', f'Affected residents: {raw}')
    return None, 'unknown'


def evidence_url(base, value, flags):
    """Links are stored as evidence, never fetched by these listing collectors."""
    if not value:
        return None
    url = urljoin(base, clean(value))
    try:
        parts = urlsplit(url)
        safe = parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password and parts.port in (None, 443)
    except ValueError:
        safe = False
    if not safe:
        flag(flags, 'invalid_notice_url', 'Source notice link is not a safe HTTPS URL.')
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
                       quote(parts.query, safe="%=&?/:@!$'()*+,;~-._"), ''))


def stable_id(*parts):
    value = '\n'.join(clean(part).casefold() for part in parts)
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def document_key(url):
    parts = urlsplit(url or '')
    return unquote(urlunsplit((parts.scheme, parts.netloc, parts.path, '', '')))


def _table(soup, required, source):
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            headings = row.find_all('th', recursive=False)
            headers = {key(h.get_text(' ', strip=True)): i for i, h in enumerate(headings)}
            if required <= headers.keys():
                return table, headers
    raise SourceError(f'{SOURCES[source]["label"]}: expected named listing headers not found; source may be blocked or changed')


def _checked(source, reports, rejected=0, *, complete=True, message=''):
    unique, conflicts, duplicate_count = {}, {}, 0
    # Exact duplicates may occur at page boundaries and are counted as rejected
    # rows so coverage cannot appear complete after pagination overlap. Ambiguous
    # duplicates are rejected together rather than choosing an arbitrary count.
    for report in reports:
        if report.native_id in conflicts:
            conflicts[report.native_id] += 1
            continue
        existing = unique.get(report.native_id)
        if existing is not None and asdict(existing) != asdict(report):
            conflicts[report.native_id] = 2
            del unique[report.native_id]
            continue
        if existing is not None:
            duplicate_count += 1
            continue
        unique[report.native_id] = report
    if duplicate_count:
        rejected += duplicate_count
        message += f' Rejected {duplicate_count} repeated source rows; listing overlap makes coverage partial.'
    if conflicts:
        rejected += sum(conflicts.values())
        message += f' Rejected {sum(conflicts.values())} ambiguous rows sharing source identities; no arbitrary count was chosen.'
    if not unique:
        raise SourceError(f'{SOURCES[source]["label"]}: no valid public records parsed')
    return Collection(source, list(unique.values()), len(unique) + rejected, rejected,
                      message, complete=complete and rejected == 0)


TABLE_COLUMNS = {
    'montana': {'organization': 'businessname', 'reported': 'datereported', 'start': 'startofbreach', 'end': 'endofbreach', 'count': 'montanansaffected', 'notice': 'notificationdocuments'},
    'washington': {'organization': 'organizationname', 'reported': 'datereported', 'breach': 'dateofbreach', 'count': 'numberofwashingtoniansaffected', 'types': 'informationcompromised'},
    'south_carolina': {'organization': 'organizationname', 'reported': 'datereported', 'count': 'affectedscresidents'},
    'delaware': {'organization': 'organizationname', 'reported': 'reporteddate', 'breach': 'datesofbreach', 'count': 'numberofpotentiallyaffecteddelawareresidents', 'notice': 'sampleofnotice'},
}


def parse_table(source, html, url=None, *, today=None):
    url = url or SOURCES[source]['homepage']
    soup = BeautifulSoup(html, 'html.parser')
    columns = TABLE_COLUMNS[source]
    table, headers = _table(soup, set(columns.values()), source)
    reports, rejected = [], 0
    for row in table.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if not cells:
            continue
        if not any(clean(c.get_text(' ', strip=True)) for c in cells):
            continue  # Observed blank Delaware formatting row, not a report.
        if len(cells) != len(headers):
            rejected += 1
            continue
        def cell(name):
            return cells[headers[columns[name]]]
        def text(name):
            return clean(cell(name).get_text(' ', strip=True))
        organization = text('organization')
        if not organization:
            rejected += 1
            continue
        flags = []
        reported_raw = text('reported')
        reported = parse_date(reported_raw, flags, 'Date reported', today=today)
        count, qualifier = parse_count(text('count'), flags)
        notice_cell = cell('notice') if 'notice' in columns else cell('organization')
        notice_link = notice_cell.find('a', href=True)
        notice = evidence_url(url, notice_link['href'] if notice_link else None, flags)
        if source == 'montana':
            row_id = row.get('data-row_id', '')
            if not re.fullmatch(r'\d+', row_id):
                rejected += 1
                continue
            native_id = 'row-' + row_id
            start = parse_date(text('start'), flags, 'Breach start', today=today)
            end = parse_date(text('end'), flags, 'Breach end', today=today)
        else:
            # One document can cover several organizations or several notices;
            # a notice URL alone caused collisions in the old collectors.
            identity_date = reported or clean(reported_raw).casefold()
            native_id = stable_id(document_key(notice), organization, identity_date)
            start, end = date_range(text('breach'), flags, today=today) if 'breach' in columns else (None, None)
            if not notice:
                flag(flags, 'natural_source_identity', 'Listing has no stable record ID or notice link; identity uses organization and reported date.')
        if start and end and end < start:
            flag(flags, 'inverted_breach_dates', 'Source breach end precedes its start; occurrence dates left unknown.')
            start, end = None, None
        types = [clean(item) for item in text('types').split(';') if clean(item)] if 'types' in columns else []
        reports.append(Report(source, native_id, organization, SOURCES[source]['homepage'],
                              reported_date=reported, breach_start=start, breach_end=end,
                              affected_count=count, affected_scope='state',
                              affected_jurisdiction=SOURCES[source]['jurisdiction'],
                              affected_qualifier=qualifier, notice_url=notice,
                              data_types=types, quality_flags=flags,
                              summary='Public state notification listing. Counts cover residents of this state.',
                              parser_version=PARSER_VERSION))
    complete = True
    message = 'All records in the public listing were parsed; linked documents were not downloaded.'
    if source == 'montana':
        # The current Ninja Tables source embeds every row, with no deferred rows.
        complete = bool(re.search(r'"defer_row_limit"\s*:\s*false', html))
        if not complete:
            message = 'Montana table parsed, but full embedded-row coverage could not be validated.'
    result = _checked(source, reports, rejected, complete=complete, message=message)
    if source != 'washington':
        return result, None
    # Follow only the observed Drupal pager, validating offsets and final-page
    # controls. A missing pager does not silently declare full coverage.
    pager = soup.select_one('nav.pager')
    if pager is None:
        result.complete = False
        result.message = 'Washington listing parsed, but pagination controls are missing; coverage unverified.'
        return result, None
    current = int(parse_qs(urlsplit(url).query).get('page', ['0'])[0])
    next_link = pager.select_one('a[rel="next"]')
    linked_pages = []
    for link in pager.find_all('a', href=True):
        target = urljoin(url, link['href'])
        parts = urlsplit(target)
        if parts.hostname != 'www.atg.wa.gov' or parts.path != urlsplit(SOURCES[source]['homepage']).path or parts.scheme != 'https':
            raise SourceError('Washington: unexpected pagination target')
        try:
            linked_pages.append(int(parse_qs(parts.query)['page'][0]))
        except (KeyError, ValueError):
            raise SourceError('Washington: invalid pagination offset')
    active = pager.select_one('a[aria-current="page"]')
    if not active or int(parse_qs(urlsplit(urljoin(url, active['href'])).query).get('page', ['-1'])[0]) != current:
        raise SourceError('Washington: pagination did not advance to requested page')
    if next_link:
        target = urljoin(url, next_link['href'])
        if parse_qs(urlsplit(target).query).get('page') != [str(current + 1)]:
            raise SourceError('Washington: next-page offset is not sequential')
        return result, target
    if any(page > current for page in linked_pages):
        raise SourceError('Washington: next-page control missing before terminal page')
    return result, None


WI_LABELS = ('Company Name', 'Date of Incident', 'Date Public Notified', 'Data Accessed',
             'Who is Affected', 'Number of Individuals Affected', 'Number of Wisconsin Residents Affected')
WI_FIELD = re.compile(r'(' + '|'.join(re.escape(label) for label in WI_LABELS) + r')\s*:', re.I)


def parse_wisconsin(html, *, today=None):
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(['script', 'style']):
        element.decompose()
    text = clean(soup.get_text(' ', strip=True))
    # The real site is labeled prose, not a table. Segment only by Company Name
    # and named fields; links, contact details and prose are not report records.
    chunks = re.split(r'Company\s+Name\s*:', text, flags=re.I)[1:]
    reports, rejected = [], 0
    for chunk in chunks:
        chunk = 'Company Name: ' + chunk
        matches = list(WI_FIELD.finditer(chunk))
        values = {key(match[1]): clean(chunk[match.end():matches[i+1].start() if i + 1 < len(matches) else len(chunk)])
                  for i, match in enumerate(matches)}
        if not {'companyname', 'dateofincident', 'datepublicnotified', 'numberofwisconsinresidentsaffected'} <= values.keys():
            rejected += 1
            continue
        # The final resident-count field is followed by consumer contact prose.
        raw_count = re.split(r'Who\s+and\s+how\s+to\s+contact', values['numberofwisconsinresidentsaffected'], flags=re.I)[0].strip()
        flags = []
        notified = parse_date(values['datepublicnotified'], flags, 'Date public notified', today=today)
        start, end = date_range(values['dateofincident'], flags, today=today)
        count, qualifier = parse_count(raw_count, flags)
        organization = values['companyname']
        native_id = stable_id(organization, notified or values['datepublicnotified'], values['dateofincident'])
        flag(flags, 'natural_source_identity', 'Wisconsin prose listing has no native record ID; identity uses organization and source dates.')
        flag(flags, 'notification_date_only', 'Date Public Notified describes public/consumer notification; it does not establish the state listing publication or receipt date.')
        reports.append(Report('wisconsin', native_id, organization, SOURCES['wisconsin']['homepage'],
                              breach_start=start, breach_end=end,
                              affected_count=count, affected_scope='state', affected_jurisdiction='WI',
                              affected_qualifier=qualifier, quality_flags=flags,
                              summary=f'Public/consumer notification date: {notified or values["datepublicnotified"] or "not reported"}. Wisconsin public consumer notice. Count covers Wisconsin residents.',
                              parser_version=PARSER_VERSION))
    return _checked('wisconsin', reports, rejected, complete=False,
                    message='Current public Wisconsin page collected. Separate historical archive is outside this listing; coverage is partial.')


def _blocked_listing(source, html):
    if re.search(r'_Incapsula_Resource|Access Denied|Request Rejected|Forbidden|captcha|enable javascript', html, re.I):
        raise SourceError(f'{SOURCES[source]["label"]}: public listing returned an access challenge; no workaround attempted')
    raise SourceError(f'{SOURCES[source]["label"]}: public listing schema is not verified; refusing guessed PDF records or an empty success')


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown public portal: {source_id}')
    page_limit = 60 if max_pages is None else max_pages
    if isinstance(page_limit, bool) or not isinstance(page_limit, int) or not 1 <= page_limit <= 200:
        raise SourceError('max_pages must be an integer between 1 and 200')
    client = PublicClient(max_requests=2 * page_limit + 5)
    try:
        url = SOURCES[source_id]['homepage']
        reports, rejected, visited, complete, message = [], 0, set(), True, ''
        for _ in range(page_limit):
            if url in visited:
                raise SourceError(f'{SOURCES[source_id]["label"]}: pagination loop')
            visited.add(url)
            response = client.request(url)
            if source_id in ('new_jersey', 'new_hampshire'):
                _blocked_listing(source_id, response.text)
            if source_id == 'wisconsin':
                result, next_url = parse_wisconsin(response.text), None
            else:
                result, next_url = parse_table(source_id, response.text, url)
            reports.extend(result.reports)
            rejected += result.rejected
            complete = complete and result.complete
            message = result.message
            if next_url is None:
                break
            url = next_url
        else:
            if next_url:
                complete = False
                message = f'Collected {page_limit} pages; older pages excluded by the page budget. Existing history is retained.'
        result = _checked(source_id, reports, rejected, complete=complete, message=message)
        result.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': len(visited)}
        return result
    finally:
        client.close()
