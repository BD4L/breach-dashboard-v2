"""The verified NJCCIC public-breach HTML listing and its published pagination.

The source remains on /threat-landscape/public-data-breaches: the newer route
redirects there in normal Chrome. Requests/headless access can be denied even
while the normal browser works. This parser never substitutes an RSS guess,
solves a challenge, or claims that browser capture proves hosted-runner access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .models import Collection, Report, SourceError
from .network import PublicClient

HOMEPAGE = 'https://www.cyber.nj.gov/threat-landscape/public-data-breaches'
SOURCES = {'new_jersey': {'id': 'new_jersey', 'label': 'New Jersey', 'jurisdiction': 'NJ',
                           'method': 'Official public HTML notices', 'homepage': HOMEPAGE}}
PARSER_VERSION = 'rediscovered-nj-1'


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def official_url(base, href, *, allow_return_context=False):
    url = urljoin(base, str(href))
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == 'https' and parts.hostname == 'www.cyber.nj.gov'
                 and not parts.username and not parts.password and parts.port in (None, 443)
                 and not parts.fragment)
        context = parse_qs(parts.query, keep_blank_values=True)
        if parts.query:
            valid = valid and allow_return_context and set(context) <= {'npage', 'arch'}
            valid = valid and all(len(values) == 1 for values in context.values())
            if 'npage' in context:
                valid = valid and context['npage'][0].isdigit() and 1 <= int(context['npage'][0]) <= 200
            if 'arch' in context:
                valid = valid and context['arch'] == ['1']
    except ValueError:
        valid = False
    if not valid or any(ord(ch) < 33 for ch in url):
        raise SourceError('New Jersey: source link is outside its official HTTPS publication paths')
    return url


def listing_identity(url):
    parts = urlsplit(official_url(HOMEPAGE, url))
    base = urlsplit(HOMEPAGE).path
    if not parts.path.startswith(base):
        raise SourceError('New Jersey: pagination left the public data breach listing')
    tail = parts.path[len(base):].rstrip('/')
    segments = tail.split('/')[1:] if tail else []
    page, archive, seen = 1, False, set()
    for segment in segments:
        if segment == '-arch-1' and 'archive' not in seen:
            archive = True; seen.add('archive')
        elif re.fullmatch(r'-npage-[1-9]\d*', segment) and 'page' not in seen:
            page = int(segment.removeprefix('-npage-')); seen.add('page')
        else:
            raise SourceError('New Jersey: unsupported publication pagination path')
    if page > 200:
        raise SourceError('New Jersey: publication page number exceeded its budget')
    return page, archive


@dataclass
class Page:
    reports: list[Report]
    parsed: int
    rejected: int
    start: int
    end: int
    total: int
    page_number: int
    archived: bool
    next_url: str | None
    archive_url: str | None


def parse_page(html, page_url=HOMEPAGE, *, today=None):
    if len(html.encode('utf-8')) > 5_000_000:
        raise SourceError('New Jersey: rendered listing exceeded its page-size budget')
    page_number, archived = listing_identity(page_url)
    soup = BeautifulSoup(html, 'html.parser')
    if not any(clean(h.get_text(' ')).lower() == 'public data breaches' for h in soup.find_all('h1')):
        raise SourceError('New Jersey: response is not the public data breach listing; access or page structure changed')
    widgets = soup.select('section.news_widget[aria-label="News List"]')
    if len(widgets) != 1:
        raise SourceError('New Jersey: expected one public breach news-list widget')
    widget = widgets[0]
    lists = widget.select('ul.list-main')
    pagers = widget.select('.list-pager')
    if len(lists) != 1 or len(pagers) != 1:
        raise SourceError('New Jersey: public list or pagination metadata is missing')
    rows = lists[0].find_all('li', recursive=False)
    pager = pagers[0]
    info = pager.select_one('.pager-info')
    match = re.fullmatch(r'(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\s+items', clean(info.get_text(' ')) if info else '', re.I)
    if not match:
        raise SourceError('New Jersey: source pagination counts are unavailable')
    start, end, total = map(int, match.groups())
    if total > 20_000 or (total == 0 and (start != 0 or end != 0 or rows)) or (total > 0 and not 1 <= start <= end <= total):
        raise SourceError('New Jersey: invalid public-list pagination range')
    if len(rows) != (end - start + 1 if total else 0):
        raise SourceError('New Jersey: extracted list rows disagree with the published page count')
    selected = pager.select_one('[aria-current="page"]')
    if not selected or clean(selected.get_text(' ')) != str(page_number):
        raise SourceError('New Jersey: selected page does not match the requested pagination URL')
    next_nodes = pager.select('a[aria-label="Next page"]')
    if len(next_nodes) != 1:
        raise SourceError('New Jersey: next-page control changed')
    next_node = next_nodes[0]
    disabled = next_node.get('aria-disabled') == 'true' or 'disabled' in next_node.get('class', [])
    next_url = None
    if not disabled and next_node.get('href'):
        next_url = official_url(page_url, next_node['href'])
        if listing_identity(next_url) != (page_number + 1, archived):
            raise SourceError('New Jersey: next link skipped a page or changed archive scope')
    if bool(next_url) != (end < total):
        raise SourceError('New Jersey: terminal-page link disagrees with the published total')
    archive_url = None
    for a in widget.select('a.filter-archive[href]'):
        label = clean(a.get_text(' ')).lower()
        if label == 'archived news':
            candidate = official_url(page_url, a['href'])
            if listing_identity(candidate) != (1, True):
                raise SourceError('New Jersey: archive link is not the first published archive page')
            archive_url = candidate
    reports, rejected = [], 0
    for row in rows:
        links, dates = row.select('a.item-title[href]'), row.select('.item-date')
        if len(links) != 1 or len(dates) != 1:
            rejected += 1; continue
        title = clean(links[0].get_text(' '))
        if not title:
            rejected += 1; continue
        url = official_url(page_url, links[0]['href'], allow_return_context=True)
        parts = urlsplit(url)
        context = parse_qs(parts.query)
        if ('npage' in context and int(context['npage'][0]) != page_number) or ('arch' in context and not archived):
            raise SourceError('New Jersey: notice return context disagrees with the source page')
        # The optional query only restores the list's navigation context. It is
        # not part of the notice identity and is omitted from canonical links.
        url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
        identity = re.fullmatch(r'/Home/Components/News/News/(\d+)/(\d+)/?', urlsplit(url).path, re.I)
        if not identity or identity[2] != '216':
            raise SourceError('New Jersey: notice link left the verified public breach component')
        raw_date = clean(dates[0].get_text(' '))
        aria_date = re.search(r'published on\s+(\d{2}/\d{2}/\d{4}(?:\s+\d{1,2}:\d{2}\s+[AP]M)?)', links[0].get('aria-label', ''), re.I)
        if aria_date and aria_date[1] != raw_date:
            rejected += 1; continue
        flags = [{'code': 'listing_fields_only', 'message': 'The official listing supplies the notice title and publication date. Incident dates and affected counts require separate notice review.'}]
        published = None
        for fmt in ('%m/%d/%Y', '%m/%d/%Y %I:%M %p'):
            try:
                value = datetime.strptime(raw_date, fmt).date()
                if value <= (today or date.today()):
                    published = value.isoformat()
                break
            except ValueError:
                continue
        if published is None:
            flags.append({'code': 'unparsed_date', 'message': f'Official notice publication date unavailable or invalid: {raw_date[:120]}'})
        reports.append(Report('new_jersey', 'news-' + identity[1], title, url,
                              published_date=published,
                              summary='Official NJCCIC public data breach notice. The displayed organization is the source notice title; linked details and documents were not enriched.',
                              quality_flags=flags, parser_version=PARSER_VERSION))
    return Page(reports, len(rows), rejected, start, end, total, page_number, archived, next_url, archive_url)


def finalize(reports, parsed, rejected, *, complete, message, evidence):
    groups = {}
    for report in reports:
        groups.setdefault(report.native_id, []).append(report)
    unique = []
    for group in groups.values():
        if any(r != group[0] for r in group[1:]):
            rejected += len(group)
        else:
            unique.append(group[0]); rejected += len(group) - 1
    if not unique and parsed:
        raise SourceError('New Jersey: all source rows failed validation')
    if parsed != len(unique) + rejected:
        raise SourceError('New Jersey: source-row accounting does not reconcile')
    return Collection('new_jersey', unique, parsed, rejected, message,
                      complete and not rejected, evidence,
                      empty_is_valid=complete and parsed == 0)


def collect(source_id='new_jersey', *, max_pages=None, client_factory=None, today=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown NJCCIC source: {source_id}')
    limit = 40 if max_pages is None else max_pages
    if type(limit) is not int or not 1 <= limit <= 200:
        raise SourceError('max_pages must be an integer between 1 and 200')
    client = (client_factory or PublicClient)(max_requests=limit + 4, max_bytes=20_000_000, deadline_seconds=240)
    reports, parsed, rejected, pages = [], 0, 0, 0
    scope_totals, scope_ends, finished = {}, {}, set()
    archive_url = None
    url = HOMEPAGE
    visited = set()
    stop = ''
    try:
        while url and pages < limit:
            if url in visited:
                raise SourceError('New Jersey: pagination cycle detected')
            visited.add(url)
            try:
                response = client.request(url)
                page = parse_page(response.text, response.url, today=today)
                if listing_identity(response.url) != listing_identity(url):
                    raise SourceError('New Jersey: navigation changed requested page or archive scope')
                scope = 'archive' if page.archived else 'current'
                if scope in scope_totals and scope_totals[scope] != page.total:
                    raise SourceError('New Jersey: source total changed during pagination')
                if page.start != (scope_ends.get(scope, 0) + 1 if page.total else 0):
                    raise SourceError('New Jersey: page ranges overlap or omit source rows')
            except SourceError as exc:
                if not reports:
                    raise
                stop = f' Collection stopped: {exc}'
                break
            scope_totals[scope] = page.total; scope_ends[scope] = page.end
            reports.extend(page.reports); parsed += page.parsed; rejected += page.rejected; pages += 1
            archive_url = archive_url or page.archive_url
            url = page.next_url
            if url is None:
                finished.add(scope)
                if scope == 'current' and archive_url:
                    url = archive_url
        complete = finished == {'current', 'archive'} and not url and not stop
        pending = ' More published pages remain.' if url and not stop else ''
        archive_note = '' if archive_url else ' No verified public archive switch was found.'
        return finalize(reports, parsed, rejected, complete=complete,
                        message=f'Parsed {pages} official public-breach listing pages. Current and archive totals observed: {scope_totals}. Notice details and attached documents are outside routine collection.{pending}{archive_note}{stop}',
                        evidence={'pages': pages, 'scope_totals': scope_totals, 'finished_scopes': sorted(finished), 'coverage': 'official_public_breach_news_list'})
    finally:
        client.close()
