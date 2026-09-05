"""Rediscovered official publishing surfaces, without credential or proxy fallbacks.

Maryland's anonymous SharePoint catalog is a separate public resource from its
large landing page. Wisconsin's linked archive uses an older prose schema. New
Jersey publishes an RSS endpoint linked from its official archived navigation.
"""
from __future__ import annotations

from datetime import date, timezone
from email.utils import parsedate_to_datetime
from html import escape
import json
import re
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from ingestion.models import Report, SourceError
from ingestion.network import PublicClient
from ingestion.other_portals import (SOURCES as OTHER_SOURCES, _checked, clean, key,
                                     parse_wisconsin, WI_FIELD)
from ingestion.state_portals import (SOURCES as STATE_SOURCES, checked, maryland_endpoint,
                                     parse_maryland_page)

SOURCES = {
    'maryland': dict(STATE_SOURCES['maryland'], method='Official public JSON'),
    'wisconsin': dict(OTHER_SOURCES['wisconsin']),
    'new_jersey': dict(OTHER_SOURCES['new_jersey'], homepage='https://www.cyber.nj.gov/threat-center/public-data-breaches', method='Official public RSS'),
}
MD_CATALOG = ("https://oag.maryland.gov/resources-info/_api/web/lists?"
              "$select=Title,Hidden,ItemCount&$filter=startswith(Title,'Security-Breach-Notices')%20and%20Hidden%20eq%20false")
NJ_RSS = 'https://www.cyber.nj.gov/rss.xml'
JSON_HEADERS = {'Accept': 'application/json;odata=verbose'}


def json_response(response, source):
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError(f'{source}: public endpoint returned invalid JSON') from exc


def maryland_catalog(data, *, today=None):
    """Discover actually published non-hidden lists; never guess next year's URL."""
    year = (today or date.today()).year
    if not isinstance(data, dict) or not isinstance(data.get('d'), dict) or not isinstance(data['d'].get('results'), list):
        raise SourceError('Maryland: public list catalog schema changed')
    if data['d'].get('__next'):
        raise SourceError('Maryland: public list catalog is unexpectedly paginated; discovery incomplete')
    found = {}
    for item in data['d']['results']:
        if not isinstance(item, dict):
            raise SourceError('Maryland: invalid public list metadata')
        match = re.fullmatch(r'Security-Breach-Notices-(20\d{2})', str(item.get('Title', '')))
        if not match or item.get('Hidden') is not False:
            continue
        found_year, count = int(match[1]), item.get('ItemCount')
        if found_year > year:
            continue
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SourceError('Maryland: invalid independently published list count')
        if found_year in found:
            raise SourceError('Maryland: duplicate annual list declaration')
        found[found_year] = count
    if not found:
        raise SourceError('Maryland: no published annual security-breach lists found')
    return sorted(found.items(), reverse=True)


def collect_maryland(client, limit, *, today=None):
    today = today or date.today()
    catalog = maryland_catalog(json_response(client.request(MD_CATALOG, headers=JSON_HEADERS), 'Maryland'), today=today)
    selected = catalog[:2]
    reports, parsed, rejected, pages, validated = [], 0, 0, 0, []
    stop = ''
    for year, expected in selected:
        url = maryland_endpoint(year).replace('$orderby=Date_x0020_Received%20desc', '$orderby=Id%20asc')
        seen, actual = set(), 0
        while url and pages < limit:
            if url in seen:
                raise SourceError('Maryland: pagination repeated a public-list page')
            seen.add(url)
            try:
                response = client.request(url, headers=JSON_HEADERS)
                current, count, bad, next_url = parse_maryland_page(json_response(response, 'Maryland'), year, today=today)
            except SourceError as exc:
                if not reports:
                    raise
                stop = f' Collection stopped: {exc}'
                break
            reports.extend(current)
            parsed += count
            actual += count
            rejected += bad
            pages += 1
            url = next_url
        if stop:
            break
        if url:
            stop = ' More API pages remain because the page budget was reached.'
            break
        if actual != expected:
            stop = f' {year} parsed row count {actual} disagrees with the published list count {expected}; coverage is unverified.'
            break
        validated.append(year)
    result = checked('maryland', reports, parsed, rejected, complete=False,
                      message=f'Collected {pages} API pages from published lists {", ".join(str(y) for y, _ in selected)}. '
                              f'Independent row counts matched for {", ".join(map(str, validated)) or "no complete list"}. '
                              'Other annual archives and notice PDFs are outside this collection.' +
                              (f' No {today.year} annual list is published in the official catalog.' if selected[0][0] < today.year else '') + stop)
    if result.parsed != parsed:
        raise SourceError('Maryland: parsed-row accounting changed unexpectedly')
    result.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': pages + 1}
    return result


def discover_wisconsin_archive(html):
    urls = set()
    for link in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
        if 'data breach archive' not in clean(link.get_text(' ', strip=True)).lower():
            continue
        url = urljoin(SOURCES['wisconsin']['homepage'], link['href'])
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'datcp.wi.gov' or parts.username or parts.password:
            raise SourceError('Wisconsin: archive link left the official source')
        if parts.path.lower() != '/pages/programs_services/databreacharchive.aspx' or parts.query or parts.fragment:
            raise SourceError('Wisconsin: linked archive schema has changed')
        urls.add(url)
    if len(urls) != 1:
        raise SourceError('Wisconsin: exactly one linked public breach archive was expected')
    return next(iter(urls))


def parse_wisconsin_archive(html, url):
    """Older notices lack a dedicated WI count; keep it unknown, not a rejection.

    Reuse the current parser's identity/date rules so moving an entry into the
    archive does not manufacture a new record or relabel its notification date.
    """
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(['script', 'style']):
        element.decompose()
    text = clean(soup.get_text(' ', strip=True))
    chunks = re.split(r'Company\s+Name\s*:', text, flags=re.I)[1:]
    if not chunks:
        raise SourceError('Wisconsin: archive no longer contains labeled breach records')
    reports, rejected = [], 0
    for chunk in chunks:
        chunk = 'Company Name: ' + chunk
        fields = {key(match[1]) for match in WI_FIELD.finditer(chunk)}
        if not {'companyname', 'dateofincident', 'datepublicnotified'} <= fields:
            rejected += 1
            continue
        missing_count = 'numberofwisconsinresidentsaffected' not in fields
        if missing_count:
            chunk += ' Number of Wisconsin Residents Affected: Unknown'
        current = parse_wisconsin('<p>' + escape(chunk) + '</p>')
        if len(current.reports) != 1:
            raise SourceError('Wisconsin: archive notice segmentation was ambiguous')
        report = current.reports[0]
        report.source_url = url
        if missing_count:
            report.quality_flags.append({'code': 'state_count_unavailable', 'message': 'Archived notice has no dedicated Wisconsin count field; any nationwide count was not substituted.'})
        reports.append(report)
    return _checked('wisconsin', reports, rejected, complete=False,
                    message='Linked Wisconsin archive parsed; no independent annual total establishes completeness.')


def collect_wisconsin(client, limit):
    first = client.request(SOURCES['wisconsin']['homepage'])
    current = parse_wisconsin(first.text)
    if limit < 2:
        current.message = 'Current Wisconsin listing collected; linked historical archive excluded by the page budget.'
        current.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': 1}
        return current
    try:
        archive_url = discover_wisconsin_archive(first.text)
        response = client.request(archive_url)
        archived = parse_wisconsin_archive(response.text, archive_url)
    except SourceError as exc:
        current.message = f'Current Wisconsin listing collected. Historical archive unavailable: {exc}'
        current.complete = False
        current.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': 1}
        return current
    result = _checked('wisconsin', current.reports + archived.reports, current.rejected + archived.rejected, complete=False,
                      message='Current Wisconsin listing and its linked 2012–2023 archive collected. '
                              'The source does not publish an independent completeness total; consumer notification dates are retained separately from publication dates.')
    result.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': 2}
    return result


def parse_new_jersey_rss(content, *, today=None):
    """Strict public-breach subset only; the full feed also contains threat news.

    The official feed endpoint is verified in archived state navigation. Live
    response access remains blocked; fixtures are explicit synthetic contracts.
    """
    if len(content) > 10_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise SourceError('New Jersey: RSS contains unsupported entity declarations or exceeds size budget')
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceError('New Jersey: public RSS returned a challenge or invalid XML') from exc
    channel = root.find('channel') if root.tag == 'rss' else None
    if channel is None:
        raise SourceError('New Jersey: expected an RSS channel')
    reports, rejected = [], 0
    today = today or date.today()
    for item in channel.findall('item'):
        url = clean(item.findtext('link'))
        parts = urlsplit(url)
        if parts.hostname != 'www.cyber.nj.gov' or parts.scheme != 'https' or parts.username or parts.password:
            continue
        if not (parts.path.startswith('/public-data-breaches/') or parts.path.startswith('/threat-center/public-data-breaches/')):
            continue
        title = clean(item.findtext('title'))
        if not title or parts.path.rstrip('/').endswith('public-data-breaches'):
            rejected += 1
            continue
        # No incident date/count or organization extraction from a news headline.
        # A feed title is acceptable only where it names the public breach entry.
        flags = [{'code': 'feed_scope', 'message': 'Official feed entry; detailed breach fields and complete archive coverage are not established.'}]
        published = None
        raw_date = clean(item.findtext('pubDate'))
        if raw_date:
            try:
                value = parsedate_to_datetime(raw_date)
                if value.tzinfo is None:
                    raise ValueError('Feed publication date lacks timezone')
                candidate = value.astimezone(timezone.utc).date()
                if candidate > today:
                    raise ValueError('Future feed publication date')
                published = candidate.isoformat()
            except (ValueError, TypeError, OverflowError):
                flags.append({'code': 'unparsed_date', 'message': f'RSS publication date: {raw_date[:200]}'})
        reports.append(Report('new_jersey', parts.path.rstrip('/'), title, url,
                              published_date=published,
                              summary='Official NJCCIC public data breach feed entry.', quality_flags=flags,
                              parser_version='rediscovered-midatlantic-1'))
    return _checked('new_jersey', reports, rejected, complete=False,
                    message='Official RSS public-breach subset only; the full archive and detailed reports are outside feed coverage.')


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown rediscovered source: {source_id}')
    limit = 24 if max_pages is None else max_pages
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise SourceError('max_pages must be an integer between 1 and 200')
    client = PublicClient(max_requests=min(2 * limit + 4, 100), deadline_seconds=240)
    try:
        if source_id == 'maryland':
            return collect_maryland(client, limit)
        if source_id == 'wisconsin':
            return collect_wisconsin(client, limit)
        response = client.request(NJ_RSS, headers={'Accept': 'application/rss+xml,application/xml,text/xml'})
        result = parse_new_jersey_rss(response.content)
        result.evidence = {'requests': client.requests, 'bytes': client.bytes, 'pageCount': 1}
        return result
    finally:
        client.close()
