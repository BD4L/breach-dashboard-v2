"""Recent RSS/Atom headlines and bounded company-page discovery.

Only titles, dates and original links are persisted. Source prose is never
executed, and missing article dates are never replaced with a feed build time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from .additional_sources import COMPANY_PAGES, FEEDS
from .models import Report, SourceError
from .network import PublicClient
from .restored_sources import clean, finish
from .validation import safe_url, timestamp, utc_now

VERSION = 'syndicated-metadata-1'
BREACH_TERMS = re.compile(
    r'\b(?:(?:data[ -]+|security )?breach(?:es|ed)?|ransomware|cyber[ -]?attack|'
    r'data[ -]+(?:leak|theft)|breached accounts|stolen (?:data|records|credentials)|'
    r'(?:expos\w+|leak\w+)\s+(?:\w+\s+){0,5}(?:records|personal data|customer data)|'
    r'unauthori[sz]ed access|hackers? (?:stole|steal|leak|access))\b', re.I)


def plain(value: str) -> str:
    return clean(BeautifulSoup(value or '', 'html.parser').get_text(' '))


def instant(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    for parser in (lambda text: datetime.fromisoformat(text.replace('Z', '+00:00')), parsedate_to_datetime):
        try:
            parsed = parser(value.strip())
            if parsed.tzinfo is not None:
                return utc_now(parsed)
        except (ValueError, TypeError, IndexError, OverflowError):
            pass
    return None


def article_date(html: str) -> datetime | date | None:
    soup = BeautifulSoup(html, 'html.parser')
    for selector, attribute in [('meta[property="article:published_time"]', 'content'),
                                ('meta[itemprop="datePublished"]', 'content'), ('time[itemprop="datePublished"]', 'datetime')]:
        node = soup.select_one(selector)
        if node and (value := instant(node.get(attribute, ''))):
            return value
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (TypeError, ValueError):
            continue
        entries = value if isinstance(value, list) else [value]
        for entry in list(entries):
            if isinstance(entry, dict):
                graph = entry.get('@graph')
                if isinstance(graph, list):
                    entries.extend(graph)
        for entry in entries:
            if isinstance(entry, dict) and (value := instant(entry.get('datePublished', ''))):
                return value
    # ISMG publishes a calendar date in the article byline, without a time zone.
    # Never take dates from navigation cards or turn this into an exact timestamp.
    byline = soup.select_one('article#generic-article > .article-byline .text-nowrap')
    if byline:
        try:
            return datetime.strptime(clean(byline.get_text(' ')), '%B %d, %Y').date()
        except ValueError:
            pass
    return None


def calendar_day(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value


def parse_feed(source: str, content: bytes, *, now=None, date_lookup=None):
    now = utc_now(now)
    if len(content) > 6_000_000 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', content, re.I):
        raise SourceError('Feed exceeds bounds or contains a document/entity declaration')
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise SourceError('Source did not return valid RSS/Atom XML') from error
    tag = lambda node: node.tag.rsplit('}', 1)[-1]
    if tag(root) not in {'rss', 'feed', 'RDF'}:
        raise SourceError('Response is not a recognized RSS/Atom feed')
    entries = [node for node in root.iter() if tag(node) in {'item', 'entry'}]
    if not entries or len(entries) > 2000:
        raise SourceError('Feed entries are absent or exceed the bounded item limit')
    reports, rejected, outside, unmatched, undated = [], 0, 0, 0, 0
    dates = []
    cutoff = now - timedelta(days=30)
    for entry in entries:
        fields = {tag(node): node.text or '' for node in entry}
        dated = instant(fields.get('pubDate') or fields.get('published') or fields.get('date') or '')
        if dated and dated <= now:
            dates.append(dated.date())
        title = plain(fields.get('title', ''))
        description = plain(fields.get('description') or fields.get('summary') or fields.get('content') or '')[:1500]
        if source != 'hibp_feed' and not BREACH_TERMS.search(title + ' ' + description):
            unmatched += 1
            continue
        link_nodes = [node for node in entry if tag(node) == 'link' and node.get('rel', 'alternate') == 'alternate']
        link = (link_nodes[0].get('href') or link_nodes[0].text or '').strip() if link_nodes else fields.get('link', '').strip()
        if not title or len(title) > 500 or not safe_url(link) or urlsplit(link).scheme != 'https':
            rejected += 1
            continue
        if not dated and date_lookup:
            dated = date_lookup(link)
            if dated and calendar_day(dated) <= now.date():
                dates.append(calendar_day(dated))
        if dated and (dated > now if isinstance(dated, datetime) else dated > now.date()):
            rejected += 1
            continue
        if dated and (dated < cutoff if isinstance(dated, datetime) else dated < cutoff.date()):
            outside += 1
            continue
        flags = [{'code': 'secondary_report', 'message': 'Keyword-selected third-party headline; not an official notice or independently confirmed incident.'}]
        if not dated:
            undated += 1
            flags.append({'code': 'missing_publication_date', 'message': 'No usable article publication timestamp; feed build time was not substituted.'})
        native = fields.get('guid') or fields.get('id') or link
        reports.append(Report(source, sha256(native.encode()).hexdigest()[:32], title, link,
                              published_date=calendar_day(dated).isoformat() if dated else None,
                              source_observed_at=timestamp(dated) if isinstance(dated, datetime) else None,
                              summary=f'{FEEDS[source][0]} headline. Follow the original link to verify the incident and its publication context. This is a secondary report, not an official breach filing.',
                              quality_flags=flags, signal_type='secondary_report', parser_version=VERSION))
    latest = max(dates).isoformat() if dates else None
    stale = bool(dates and max(dates) < cutoff.date())
    message = (f'Checked {len(entries)} feed entries; {unmatched} without breach-related terms and {outside} older than 30 days excluded. '
               f'{undated} matching headlines have no usable publication date. Latest dated feed entry: {latest or "unavailable"}. '
               'Current feed window only; keyword filtering is not comprehensive incident coverage. Headlines and original links only.')
    if stale:
        message += ' The feed is outdated; this does not provide current monitoring.'
    return finish(source, reports, rejected, message, complete=not stale and not undated,
                  empty_is_valid=True, evidence={'feedEntries': len(entries), 'unmatched': unmatched,
                    'outsideWindow': outside, 'undated': undated, 'latestSourceDate': latest, 'metadataOnly': True})


def parse_cybernews(html: str, *, now=None):
    """The discontinued RSS URL is replaced by the publisher's dated news cards."""
    now = utc_now(now)
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('article')
    if not soup.title or 'cybernews' not in soup.title.get_text().casefold() or not 0 < len(cards) <= 500:
        raise SourceError('Expected Cybernews public news cards; current listing is unverified')
    reports, rejected = [], 0
    for card in cards:
        heading, link = card.select_one('h2, h3'), card.select_one('a[href]')
        headline = clean(heading.get_text(' ')) if heading else ''
        if not BREACH_TERMS.search(headline):
            continue
        original = link['href'] if link else ''
        dated = None
        for node in card.select('.category-block__meta-item, .meta-item'):
            try:
                dated = datetime.strptime(clean(node.get_text(' ')), '%B %d, %Y').date()
                break
            except ValueError:
                pass
        if not dated or dated > now.date() or not safe_url(original) or urlsplit(original).hostname != 'cybernews.com':
            rejected += 1
            continue
        if dated < (now - timedelta(days=30)).date():
            continue
        reports.append(Report('news_cybernews', sha256(original.encode()).hexdigest()[:32], headline, original,
                              published_date=dated.isoformat(), signal_type='secondary_report',
                              summary='Cybernews headline from its public dated news cards. Follow the original link to verify the incident; this is a secondary report, not an official notice.',
                              quality_flags=[{'code': 'secondary_report', 'message': 'Publisher reporting may describe an unverified claim or an older incident.'}],
                              parser_version=VERSION))
    return finish('news_cybernews', reports, rejected,
                  f'Checked {len(cards)} current public news cards; the old RSS path returns 404. Homepage window only, filtered for breach-related headlines from the last 30 days. Full news archive excluded.',
                  complete=False, empty_is_valid=True, evidence={'listingCards': len(cards), 'metadataOnly': True})


def parse_company_page(source: str, html: str, url: str, *, now=None):
    now = utc_now(now)
    soup = BeautifulSoup(html, 'html.parser')
    title = clean(soup.title.get_text(' ')) if soup.title else ''
    company = COMPANY_PAGES[source][0].removesuffix(' IR')
    if company.casefold() not in (title + clean(soup.get_text(' '))[:6000]).casefold() or re.search(r'access denied|just a moment|captcha', title, re.I):
        raise SourceError('Expected the public company investor-relations page; access or page identity failed')
    reports = []
    for link in soup.select('main a[href], [role="main"] a[href]'):
        headline = clean(link.get_text(' '))
        if not BREACH_TERMS.search(headline):
            continue
        original = urljoin(url, link['href'])
        if not safe_url(original) or urlsplit(original).scheme != 'https':
            continue
        reports.append(Report(source, sha256(original.encode()).hexdigest()[:32], headline, original,
                              summary=f'Link from {company} investor relations. Publication date and incident details need verification.',
                              quality_flags=[{'code': 'secondary_report', 'message': 'Announcement-link discovery only; a breach has not been independently verified.'}],
                              signal_type='secondary_report', parser_version=VERSION))
    return finish(source, reports, 0,
                  f'Checked the configured {company} IR page. Found {len(reports)} breach-related links. '
                  'This shallow page scan does not establish complete company coverage; dated security announcements may be published elsewhere. SEC remains a separate source.',
                  complete=False, empty_is_valid=True, evidence={'metadataOnly': True, 'pageTitle': title[:150]})


def collect(source_id: str, *, max_pages=None, now=None):
    client = PublicClient(max_requests=7, max_bytes=6_000_000, deadline_seconds=60)
    lookups = 0
    try:
        if source_id in FEEDS:
            url = FEEDS[source_id][1]
            def lookup(link):
                nonlocal lookups
                if lookups >= 3 or urlsplit(link).hostname != urlsplit(url).hostname:
                    return None
                lookups += 1
                try:
                    return article_date(client.request(link).text)
                except SourceError:
                    lookups = 3
                    return None
            response = client.request(url)
            result = parse_cybernews(response.text, now=now) if source_id == 'news_cybernews' else parse_feed(source_id, response.content, now=now, date_lookup=lookup)
        elif source_id in COMPANY_PAGES:
            response = client.request(COMPANY_PAGES[source_id][1])
            result = parse_company_page(source_id, response.text, response.url, now=now)
        else:
            raise SourceError('Unknown syndicated source')
        result.evidence.update({'requests': client.requests, 'responseBytes': client.bytes})
        return result
    finally:
        client.close()
