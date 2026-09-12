"""Bounded current source listings; public metadata only, no leak contents."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .additional_sources import SOURCES
from .models import Collection, Report, SourceError
from .network import PublicClient
from .validation import safe_url, timestamp, utc_now

VERSION = 'restored-listings-1'


def clean(value) -> str:
    return ' '.join(str(value or '').split())


def date_value(value: str) -> str | None:
    for pattern in ('%Y-%m-%d', '%m-%d-%Y', '%m/%d/%Y', '%Y/%m.%d', '%Y/%m/%d', '%b %d, %Y'):
        try:
            return datetime.strptime(clean(value), pattern).date().isoformat()
        except ValueError:
            pass
    return None


def count_value(value: str) -> int | None:
    text = clean(value).replace(',', '')
    return int(text) if re.fullmatch(r'\d{1,12}', text) else None


def finish(source: str, reports: list[Report], rejected: int, message: str, *, evidence=None,
           complete=True, empty_is_valid=False) -> Collection:
    """Withhold every conflicting identity; exact duplicates cannot inflate totals."""
    unique, conflicts = {}, set()
    parsed = len(reports) + rejected
    for report in reports:
        identifier = report.native_id
        if identifier in conflicts:
            rejected += 1
        elif identifier in unique:
            rejected += 1
            if asdict(unique[identifier]) != asdict(report):
                del unique[identifier]
                conflicts.add(identifier)
                rejected += 1
        else:
            unique[identifier] = report
    if rejected:
        message += f' Withheld {rejected} malformed, duplicate or conflicting rows.'
    return Collection(source, list(unique.values()), parsed, rejected, message,
                      complete=complete and rejected == 0, evidence=evidence or {},
                      empty_is_valid=empty_is_valid and parsed == 0)


def parse_state(source: str, html: str) -> Collection:
    soup = BeautifulSoup(html, 'html.parser')
    required = ('Date Reported to AGO', 'Reporting Organization Name', 'Number of VT Residents Affected') if source == 'vermont' else ('Date Notified', 'Case Number', 'Breached Entity Name', 'Hawaii Residents Impacted')
    tables = [table for table in soup.select('table') if all(text.casefold() in clean(table.get_text(' ')).casefold() for text in required)]
    if len(tables) != 1:
        raise SourceError('Expected exactly one official breach reporting table; page structure changed')
    rows = tables[0].select('tbody tr') or tables[0].select('tr')[1:]
    if not rows:
        raise SourceError('Official table has no data rows; empty coverage is unverified')
    reports, rejected = [], 0
    for row in rows:
        cells = row.find_all('td', recursive=False)
        if len(cells) < (5 if source == 'vermont' else 6):
            rejected += 1
            continue
        values = [clean(cell.get_text(' ')) for cell in cells]
        normalized_date = re.sub(r'-{2,}', '-', values[0])
        date = date_value(normalized_date)
        organization = values[1 if source == 'vermont' else 2]
        native = sha256(f'{date}|{organization.casefold()}'.encode()).hexdigest()[:24] if source == 'vermont' else values[1] + ':' + sha256(organization.casefold().encode()).hexdigest()[:12]
        if not date or not organization or not native:
            rejected += 1
            continue
        count = count_value(values[3 if source == 'vermont' else 4])
        link = cells[5].select_one('a[href]') if source == 'hawaii' else None
        notice = urljoin(SOURCES[source]['homepage'], link['href']) if link else None
        if notice and (not safe_url(notice) or urlsplit(notice).hostname != 'cca.hawaii.gov'):
            notice = None
        reports.append(Report(source, native, organization, SOURCES[source]['homepage'],
                              reported_date=date, affected_count=count, affected_scope='state',
                              affected_jurisdiction='VT' if source == 'vermont' else 'HI',
                              affected_qualifier='exact' if count is not None else 'unknown',
                              notice_url=notice,
                              data_types=[v.strip() for v in values[4].split(',') if v.strip()] if source == 'vermont' else [],
                              quality_flags=[{'code': 'source_date_typo', 'message': f'Duplicate date separator normalized from the source value: {values[0]}.'}] if normalized_date != values[0] else [],
                              summary=('Official Vermont report. Counts cover Vermont residents. Organization type: ' + values[2]) if source == 'vermont' else ('Official Hawaii OCP report. Counts cover Hawaii residents. Reported incident type: ' + values[3]),
                              parser_version=VERSION))
    dates = [r.reported_date for r in reports]
    scope = 'Current table begins April 17, 2026; earlier document archives are excluded.' if source == 'vermont' else 'Published Hawaii table only; the newest listed notification is from ' + (max(dates) if dates else 'an unknown date') + ', so this does not establish current statewide coverage.'
    return finish(source, reports, rejected, f'Checked all {len(rows)} rows in the official table. {scope}',
                  evidence={'tableRows': len(rows), 'latestSourceDate': max(dates) if dates else None, 'scope': scope})


def parse_hibp(value, *, now=None) -> Collection:
    now = utc_now(now)
    if not isinstance(value, list) or not value or len(value) > 10_000:
        raise SourceError('Expected the public HIBP breach catalog')
    reports, rejected, outside = [], 0, 0
    cutoff = now - timedelta(days=30)
    for entry in value:
        if not isinstance(entry, dict):
            rejected += 1
            continue
        try:
            added = datetime.fromisoformat(entry['AddedDate'].replace('Z', '+00:00'))
            if added.tzinfo is None:
                raise ValueError('Undated catalog entry')
            added = utc_now(added)
        except (KeyError, ValueError, AttributeError, TypeError):
            rejected += 1
            continue
        if added < cutoff:
            outside += 1
            continue
        name, title = entry.get('Name'), entry.get('Title')
        if added > now or not isinstance(name, str) or not name.strip() or not isinstance(title, str) or not title.strip():
            rejected += 1
            continue
        classes = entry.get('DataClasses')
        if not isinstance(classes, list) or not all(isinstance(v, str) for v in classes):
            rejected += 1
            continue
        count = entry.get('PwnCount')
        summary = 'Public breach catalog metadata attributed to Have I Been Pwned; not an official regulator filing.'
        if type(count) is int and count >= 0:
            summary += f' HIBP reports {count:,} compromised accounts; this is not necessarily a count of people.'
        flags = [{'code': 'secondary_report', 'message': 'Third-party breach catalog; verify the underlying incident evidence.'}]
        if entry.get('IsVerified') is not True:
            flags.append({'code': 'provider_unverified', 'message': 'HIBP does not mark this catalog entry verified.'})
        reports.append(Report('hibp', name, title, 'https://haveibeenpwned.com/PwnedWebsites#' + quote(name, safe=''),
                              published_date=added.date().isoformat(), source_observed_at=timestamp(added),
                              breach_start=date_value(entry.get('BreachDate', '')),
                              data_types=classes, summary=summary, quality_flags=flags,
                              signal_type='secondary_report', parser_version=VERSION))
    return finish('hibp', reports, rejected,
                  f'Public metadata API: inspected {len(value)} catalog entries; {outside} first published more than 30 days ago excluded. No email, password or domain lookup.',
                  evidence={'catalogEntries': len(value), 'outsideWindow': outside, 'metadataOnly': True}, empty_is_valid=True)


def parse_breachsense(html: str, url: str, *, now=None) -> Collection:
    now = utc_now(now)
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('article.blog-card')
    if not cards or len(cards) > 2000:
        raise SourceError('Expected Breachsense monthly report cards; empty page is not verified coverage')
    reports, rejected, outside = [], 0, 0
    for card in cards:
        link = card.select_one('h3 a[href]')
        body = clean(card.get_text(' '))
        match = re.search(r'Date Discovered\s+([A-Z][a-z]{2} \d{1,2}, \d{4})', body)
        dated = date_value(match[1]) if match else None
        if not link or not dated:
            rejected += 1
            continue
        if dated < (now - timedelta(days=30)).date().isoformat():
            outside += 1
            continue
        original = urljoin(url, link['href'])
        if dated > now.date().isoformat() or not safe_url(original) or urlsplit(original).hostname != 'www.breachsense.com':
            rejected += 1
            continue
        actor = re.search(r'Threat Actor\s+(.+?)\s+Date Discovered', body)
        reports.append(Report('breachsense', urlsplit(original).path, clean(link.get_text(' ')), original,
                              reported_date=dated, signal_type='ransomware_claim',
                              summary=f'Unverified ransomware claim indexed by Breachsense. Reported group: {actor[1] if actor else "not specified"}. Provider discovery date retained; no leak content collected.',
                              quality_flags=[{'code': 'unverified_claim', 'message': 'Provider claim metadata is not independent confirmation of a breach.'}],
                              parser_version=VERSION))
    return finish('breachsense', reports, rejected,
                  f'Public monthly claim index: checked {len(cards)} cards; {outside} outside 30 days excluded. Metadata only; claims are unverified. Other months and leak contents excluded.',
                  evidence={'listingCards': len(cards), 'metadataOnly': True}, complete=False, empty_is_valid=True)


def collect(source_id: str, *, max_pages=None, now=None) -> Collection:
    now = utc_now(now)
    client = PublicClient(max_requests=6, max_bytes=6_000_000, deadline_seconds=60)
    try:
        if source_id in {'vermont', 'hawaii'}:
            result = parse_state(source_id, client.request(SOURCES[source_id]['homepage']).text)
        elif source_id == 'hibp':
            result = parse_hibp(json.loads(client.request('https://haveibeenpwned.com/api/v3/breaches').text), now=now)
        elif source_id == 'breachsense':
            dates = [now, now - timedelta(days=30)]
            urls = list(dict.fromkeys(f'https://www.breachsense.com/breaches/{date.year}/{date.strftime("%B").lower()}/' for date in dates))
            parts, failures = [], []
            for url in urls:
                try:
                    parts.append(parse_breachsense(client.request(url).text, url, now=now))
                except SourceError as error:
                    if not parts:
                        raise
                    failures.append(str(error))
                    break
            result = finish(source_id, [r for part in parts for r in part.reports], sum(p.rejected for p in parts),
                            ' '.join(p.message for p in parts) + (' Additional month unavailable: ' + failures[0] if failures else ''),
                            complete=False, empty_is_valid=True,
                            evidence={'monthlyPages': len(parts), 'unavailablePages': len(failures), 'metadataOnly': True})
        else:
            raise SourceError('Unknown restored source')
        result.evidence.update({'requests': client.requests, 'responseBytes': client.bytes})
        return result
    finally:
        client.close()
