"""Public Texas JSON and SEC filing discovery without browser/PDF enrichment."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .adapters import clean, flag, parse_count, parse_date
from .models import Collection, Report, SourceError
from .network import PublicClient

SOURCES = {
    'texas': {'id': 'texas', 'label': 'Texas', 'jurisdiction': 'TX', 'method': 'Official public JSON',
              'homepage': 'https://oag.my.site.com/datasecuritybreachreport/apex/DataSecurityReportsPage'},
    'sec': {'id': 'sec', 'label': 'SEC EDGAR', 'jurisdiction': 'US', 'method': '8-K Item 1.05 filings',
            'homepage': 'https://www.sec.gov/edgar/search/'},
}
VERSION = 'special-1'
SEC_DEFAULT_AGENT = 'BreachWatch/1.0 (+https://github.com/BD4L/breach-dashboard-v2)'
SEC_FEED_SIZE = 100
SEC_MAX_FILINGS = 200
ATOM = '{http://www.w3.org/2005/Atom}'


def source_link(base, value, host):
    url = urljoin(base, value)
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != host or parts.username or parts.password or parts.port not in (None, 443):
        raise SourceError('Official portal supplied an unexpected source link')
    return url


def texas_request(landing_html, landing_url):
    """Use only the read action and false/latest parameter invoked by the public page."""
    match = re.search(r'new \$VFRM\.RemotingProviderImpl\((\{.*?\})\)\)', landing_html)
    if not match or "'DataSecurityReports.getDatareports'" not in landing_html or 'getDatareports(false)' not in landing_html:
        raise SourceError('Texas: public report read action has changed')
    try:
        config = json.loads(match[1])
        methods = config['actions']['DataSecurityReports']['ms']
        method = next(method for method in methods if method['name'] == 'getDatareports' and method['len'] == 1)
        context = {key: method[key] for key in ('csrf', 'authorization', 'ns', 'ver')}
        context['vid'] = config['vf']['vid']
        endpoint = source_link(landing_url, '/' + config['service'].lstrip('/'), 'oag.my.site.com')
        if urlsplit(endpoint).path != '/datasecuritybreachreport/apexremote':
            raise SourceError('Texas: unsupported public report service path')
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise SourceError('Texas: public report navigation configuration is incomplete') from exc
    # Transient page-issued state is used only in this request, never stored/exported.
    body = [{'action': 'DataSecurityReports', 'method': 'getDatareports', 'data': [False],
             'type': 'rpc', 'tid': 1, 'ctx': context}]
    return endpoint, json.dumps(body)


def parse_texas_response(text, *, today=None):
    try:
        events = json.loads(text)
    except ValueError as exc:
        raise SourceError('Texas: report action did not return JSON') from exc
    if not isinstance(events, list) or len(events) != 1 or not isinstance(events[0], dict):
        raise SourceError('Texas: unexpected report response envelope')
    event = events[0]
    if event.get('type') != 'rpc' or event.get('statusCode') != 200 or event.get('method') != 'getDatareports':
        raise SourceError(f"Texas: public report action failed (status {event.get('statusCode', 'unknown')}); no data saved")
    rows = event.get('result')
    if not isinstance(rows, list) or not rows:
        raise SourceError('Texas: no report records returned by public action')
    reports, rejected, seen = [], 0, set()
    for row in rows:
        if not isinstance(row, dict):
            rejected += 1
            continue
        native = row.get('Id', '')
        organization = clean(html.unescape(str(row.get('Business_Name__c') or '')))
        if not re.fullmatch(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?', str(native)) or not organization:
            rejected += 1
            continue
        if native in seen:
            raise SourceError('Texas: duplicate native report identifiers')
        seen.add(native)
        flags = []
        raw_date = row.get('Published_at_AG_website_Date__c')
        published = None
        if isinstance(raw_date, (int, float)) and not isinstance(raw_date, bool):
            try:
                published = parse_date(datetime.fromtimestamp(raw_date / 1000, timezone.utc).date().isoformat(), flags,
                                       'Date published at OAG website', today=today)
            except (ValueError, OverflowError, OSError):
                flag(flags, 'unparsed_date', 'Invalid Texas publication timestamp')
        elif raw_date is not None:
            flag(flags, 'unparsed_date', f'Date published at OAG website: {clean(raw_date)}')
        count, qualifier = parse_count(str(row.get('Number_of_Texans_affected_by_the_breach__c', '')), flags)
        data_types = [clean(html.unescape(value)) for value in str(row.get('Types_of_Personal_Information_Involved__c') or '').split(';') if clean(value)]
        summary = '; '.join(value for value in [
            f"Portal report {clean(row.get('Name'))}" if row.get('Name') else '',
            f"Notice provided to consumers: {clean(row.get('Notice_of_Breach_provided_to_consumers__c'))}" if row.get('Notice_of_Breach_provided_to_consumers__c') else '',
            f"Notice methods: {clean(row.get('Method_of_Noticee__c'))}" if row.get('Method_of_Noticee__c') else '',
        ] if value)
        reports.append(Report('texas', native, organization, SOURCES['texas']['homepage'],
                              published_date=published, affected_count=count, affected_scope='state',
                              affected_jurisdiction='TX', affected_qualifier=qualifier,
                              data_types=data_types, summary=summary, quality_flags=flags, parser_version=VERSION))
    if not reports:
        raise SourceError('Texas: all returned reports lacked valid public identities')
    return Collection('texas', reports, len(rows), rejected,
                      f'{len(rows)} reports returned by the official current-version public view; all client-table records processed. Historical versions excluded.',
                      complete=rejected == 0)


def parse_sec_feed(text, *, today=None):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceError('SEC: recent filings did not return an Atom feed') from exc
    if root.tag != ATOM + 'feed':
        raise SourceError('SEC: unexpected feed root')
    entries = root.findall(ATOM + 'entry')
    if not entries:
        raise SourceError('SEC: no filing entries returned; cannot establish feed coverage')
    filings = []
    for entry in entries:
        title = clean(entry.findtext(ATOM + 'title'))
        match = re.match(r'^(8-K(?:/A)?)\s*-\s*(.+?)\s*\(\d+\)\s*\(Filer\)\s*$', title, re.I)
        if not match:
            raise SourceError('SEC: unexpected 8-K filing title; feed schema changed')
        links = entry.findall(ATOM + 'link')
        link = next((link for link in links if link.get('rel', 'alternate') == 'alternate'), None)
        if link is None:
            raise SourceError('SEC: filing entry is missing its official index link')
        url = source_link('https://www.sec.gov', link.get('href', ''), 'www.sec.gov')
        identity = clean(entry.findtext(ATOM + 'id')) + ' ' + url
        accession = re.search(r'\b\d{10}-\d{2}-\d{6}\b', identity)
        if not accession or not re.search(r'/Archives/edgar/data/\d+/', urlsplit(url).path):
            raise SourceError('SEC: filing entry has no stable accession/index URL')
        flags = []
        summary = BeautifulSoup(entry.findtext(ATOM + 'summary') or '', 'html.parser').get_text(' ')
        filed = re.search(r'Filed:\s*(\d{4}-\d{2}-\d{2})', summary)
        raw_date = filed[1] if filed else (entry.findtext(ATOM + 'updated') or '')[:10]
        published = parse_date(raw_date, flags, 'SEC filing date', today=today)
        filings.append({'native_id': accession[0], 'organization': match[2], 'source_url': url,
                        'published_date': published, 'quality_flags': flags})
    if len({f['native_id'] for f in filings}) != len(filings):
        raise SourceError('SEC: duplicate accession numbers in recent filings feed')
    return filings


def sec_filing_index(text, url):
    """Return item decision where the index declares Items, and actual primary link."""
    soup = BeautifulSoup(text, 'html.parser')
    item_text = None
    for heading in soup.select('.infoHead'):
        if clean(heading.get_text(' ')).lower().rstrip(':') in {'items', 'item information'}:
            value = heading.find_next_sibling(class_='info')
            if value is not None:
                item_text = clean(value.get_text(' '))
    primary = None
    for table in soup.find_all('table'):
        headers = [clean(th.get_text(' ')).lower() for th in table.find_all('th')]
        if not {'document', 'type'} <= set(headers):
            continue
        for row in table.find_all('tr'):
            cells = row.find_all('td', recursive=False)
            if len(cells) <= max(headers.index('document'), headers.index('type')):
                continue
            if clean(cells[headers.index('type')].get_text(' ')) in {'8-K', '8-K/A'}:
                anchor = cells[headers.index('document')].find('a', href=True)
                if anchor:
                    primary = source_link(url, anchor['href'], 'www.sec.gov')
                    inline_document = parse_qs(urlsplit(primary).query).get('doc')
                    if inline_document:
                        if len(inline_document) != 1 or not inline_document[0].startswith('/Archives/edgar/data/'):
                            raise SourceError('SEC: unexpected inline-viewer document link')
                        primary = source_link(primary, inline_document[0], 'www.sec.gov')
                    break
    if not primary:
        raise SourceError('SEC: filing index omitted its actual primary 8-K document')
    decision = bool(re.search(r'\b1\.05\b', item_text)) if item_text is not None else None
    return decision, primary


def sec_document_has_item_105(text):
    soup = BeautifulSoup(text, 'html.parser')
    for element in soup(['script', 'style']):
        element.decompose()
    visible = clean(soup.get_text(' '))
    if not re.search(r'\b(?:FORM\s+8-K|CURRENT\s+REPORT)\b', visible, re.I):
        raise SourceError('SEC: primary document is not a recognizable current report')
    # Identify the actual disclosure heading, not broad generic cybersecurity words.
    return bool(re.search(r'\bItem\s+1\.05\s*[.\-:–—]?\s*Material\s+Cybersecurity\s+Incidents?\b', visible, re.I))


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown special source: {source_id}')
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 200):
        raise SourceError('max_pages must be an integer from 1 to 200')
    client = PublicClient(max_requests=410 if source_id == 'sec' else 6, max_bytes=30_000_000,
                          deadline_seconds=540 if source_id == 'sec' else 120)
    try:
        if source_id == 'texas':
            landing = client.request(SOURCES['texas']['homepage'])
            endpoint, body = texas_request(landing.text, landing.url)
            response = client.request(endpoint, data=body, headers={'Content-Type': 'application/json',
                                      'X-Requested-With': 'XMLHttpRequest', 'Referer': landing.url})
            result = parse_texas_response(response.text)
        else:
            user_agent = os.environ.get('SEC_USER_AGENT', SEC_DEFAULT_AGENT).strip()
            if not user_agent or '\n' in user_agent or '\r' in user_agent:
                raise SourceError('SEC_USER_AGENT must be a nonempty single-line operator identity')
            headers = {'User-Agent': user_agent}
            reports, seen = [], set()
            scanned = 0
            for page in range(max_pages or 2):
                query = urlencode({'action': 'getcurrent', 'type': '8-K', 'owner': 'include',
                                   'count': SEC_FEED_SIZE, 'start': page * SEC_FEED_SIZE, 'output': 'atom'})
                response = client.request('https://www.sec.gov/cgi-bin/browse-edgar?' + query, headers=headers)
                filings = parse_sec_feed(response.text)
                for filing in filings:
                    if filing['native_id'] in seen:
                        raise SourceError('SEC: overlapping recent-filing pages; snapshot changed during collection')
                    if scanned >= SEC_MAX_FILINGS:
                        break
                    seen.add(filing['native_id'])
                    index = client.request(filing['source_url'], headers=headers)
                    decision, primary = sec_filing_index(index.text, index.url)
                    if decision is None:
                        document = client.request(primary, headers=headers)
                        decision = sec_document_has_item_105(document.text)
                    scanned += 1
                    if decision:
                        reports.append(Report('sec', **filing, notice_url=primary,
                            summary='SEC Form 8-K Item 1.05 material cybersecurity incident disclosure. Other filing items and nonmaterial incidents are outside this source view.',
                            parser_version=VERSION))
                if scanned >= SEC_MAX_FILINGS or len(filings) < SEC_FEED_SIZE:
                    break
            result = Collection('sec', reports, len(reports), message=
                f'Examined {scanned} recent 8-K filings; {len(reports)} Item 1.05 disclosures. Bounded current-feed window (maximum {SEC_MAX_FILINGS} filings); older filings and other disclosure items excluded.',
                complete=False, empty_is_valid=not reports)
        result.evidence = {'requests': client.requests, 'bytes': client.bytes}
        return result
    finally:
        client.close()
