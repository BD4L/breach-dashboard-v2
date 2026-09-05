"""Rediscovered official publications: Iowa cards and Maine's retained archives.

These sources remain independent of the retired live database. Discovery follows
published links/inline navigation data; source HTML is never executed. Maine's
archive recovery does not imply that its withdrawn current database is available.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile, ZIP_STORED, ZIP_DEFLATED

from bs4 import BeautifulSoup

from .models import Collection, Report, SourceError
from .network import PublicClient
from .state_portals import clean, key, official_url, parse_count, parse_date, checked, SOURCES as ORIGINAL

SOURCES = {source: dict(ORIGINAL[source]) for source in ('iowa', 'maine')}
PARSER_VERSION = 'rediscovered-states-3'
MAINE_ARCHIVES = 'https://www.maine.gov/ag/news-and-library/archives'
MAX_XLSX_BYTES = 20_000_000
MAX_XLSX_EXPANDED_BYTES = 40_000_000
MAX_XLSX_ROWS = 20_000
MAX_XLSX_CELLS = 1_000_000

# The legacy entity/information cells sometimes contain an additional retailer's
# contact block. Never export those free-form blocks as organization/data types.
_CONTACT_VALUE = re.compile(
    r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}'
    r'|(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)', re.I)
_CONTACT_ROLE = re.compile(
    r'\bc/o\b|\battn\b|\battention\s*:|\b(?:chief\s+)?(?:privacy|security)\s+officer\b'
    r'|\b(?:general|legal)\s+counsel\b|\bcontact\s+person\b'
    r'|\b(?:contact|telephone|phone|fax|e-?mail)\s*:', re.I)
_AMBIGUOUS_ADDRESS = re.compile(
    r'\bP\.?O\.?\s*(?:Box|Drawer)\b|\b\d{5}(?:-\d{4})?\b'
    r'|\b\d{1,6}\s+(?:[A-Z0-9.-]+\s+){0,5}(?:St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Hwy|Highway|Parkway|Suite)\b', re.I)
_DATA_TYPE_CATEGORIES = (
    ('Social Security number', r'\bsocial\s+security\s+numbers?\b|\bssns?\b'),
    ("Driver's license or state identification number", r"\bdriver.?s?\s+licen[cs]e|\bnon.driver\s+identification|\bstate\s+identification"),
    ('Financial account or payment-card information', r'\b(?:financial|bank)\s+account|\b(?:credit|debit|payment).?card'),
    ('Names', r'\bnames?\b'),
    ('Date of birth', r'\bdate[s]?\s+of\s+birth\b|\bbirth\s*dates?\b|\bdob\b'),
    ('Postal addresses', r'\b(?:postal|mailing|home|street)\s+addresses?\b'),
    ('Email addresses', r'\be-?mail\s+addresses?\b'),
    ('Telephone numbers', r'\b(?:telephone|phone|mobile)\s+numbers?\b'),
    ('Medical or health information', r'\b(?:medical|health|patient)\s+(?:information|records?|data)\b'),
    ('Health insurance information', r'\b(?:health\s+)?insurance\s+(?:information|identification|numbers?|data)\b'),
    ('Account credentials', r'\bpasswords?\b|\buser\s*names?\b|\blogin\s+credentials?\b'),
)


def maine_organization(value, *, legacy=False):
    """Return an entity only when no unresolved contact/address block remains."""
    organization = value
    split = False
    if legacy:
        parts = re.split(r',\s*(?=\d+\s|P\.?O\.?\s*Box\b)', value, maxsplit=1, flags=re.I)
        organization, split = parts[0], len(parts) > 1
    if (_CONTACT_VALUE.search(organization) or _CONTACT_ROLE.search(organization)
            or _AMBIGUOUS_ADDRESS.search(organization)):
        return None, split
    return organization, split


def maine_legacy_data_types(value, flags):
    """Export recognized labels only, never the source's arbitrary prose."""
    if not value:
        return []
    if _CONTACT_VALUE.search(value) or _CONTACT_ROLE.search(value) or _AMBIGUOUS_ADDRESS.search(value):
        flags.append({'code': 'contact_text_withheld', 'message': 'The legacy information cell contains a contact or address block. Its text was withheld and no information categories were inferred.'})
        return []
    categories = [label for label, pattern in _DATA_TYPE_CATEGORIES if re.search(pattern, value, re.I)]
    if not categories:
        flags.append({'code': 'unclassified_data_types', 'message': 'The legacy information cell did not identify a recognized information category. Its free-form text was not exported.'})
    return categories


def iowa_year_links(html, page_url, *, today=None):
    """The actual year selector is built from a published breachYears JS array."""
    soup = BeautifulSoup(html, 'html.parser')
    candidates = [a.get('href') or a.get('value') for a in soup.find_all(['a', 'option'])]
    for script in soup.find_all('script'):
        text = script.get_text()
        match = re.search(r'\b(?:breachYears|years)\s*=\s*\[([\s\S]*?)\]\s*;', text)
        if match:
            candidates += re.findall(r'\burl\s*:\s*[\"\']([^\"\']+)[\"\']', match[1])
    years = {}
    for href in filter(None, candidates):
        match = re.search(r'/security-breach-notifications/(20\d{2})(?:-security-breach-notifications?)?/?$', urlsplit(href).path)
        if match and int(match[1]) <= (today or date.today()).year:
            url = official_url(page_url, href, host='www.iowaattorneygeneral.gov')
            years[int(match[1])] = url.rstrip('/')
    if not years:
        raise SourceError('Iowa: no published annual navigation links were found')
    return sorted(years.items(), reverse=True)


def parse_iowa_cards(html, page_url, year, *, today=None):
    soup = BeautifulSoup(html, 'html.parser')
    headings = ' '.join(h.get_text(' ', strip=True) for h in soup.find_all(['h1', 'h2']))
    if not re.search(rf'\b{year}\s+Security Breach Notification', headings, re.I):
        raise SourceError('Iowa: response is not the requested annual notification page')
    cards = []
    for grid in soup.select('.sby-record-grid, .sby-related-grid'):
        related = grid.find_parent(class_='sby-related-breaches')
        if related and clean(related.get('data-related-breaches')).lower() == 'none':
            continue
        # The 2024 HTML also nests an otherwise empty record-grid wrapper around
        # individual grids. Only the grid owning the business field is a row.
        if grid.select('.sby-record-grid, .sby-related-grid'):
            names = grid.select('.sby-business-name')
            if names and all(name.find_parent(lambda tag: bool({'sby-record-grid', 'sby-related-grid'} & set(tag.get('class', [])))) is not grid for name in names):
                continue
        cards.append(grid)
    if not cards:
        # The literal pre-JS counter says zero even when records exist: never use it.
        raise SourceError('Iowa: no expected notice cards; empty annual coverage is unverified')
    reports, rejected = [], 0
    for card in cards:
        names, dates = card.select('.sby-business-name'), card.select('.sby-date-value')
        if len(names) != 1 or len(dates) != 1:
            raise SourceError('Iowa: notice card organization/date fields changed')
        organization = clean(names[0].get_text(' '))
        primary = card.select('a.sby-file-link.primary[href]')
        supplemental_only = not primary and len(card.select('a.sby-file-link.secondary[href]')) == 1
        if supplemental_only:
            primary = card.select('a.sby-file-link.secondary[href]')
        if not organization or len(primary) != 1:
            rejected += 1
            continue
        notice = official_url(page_url, primary[0]['href'], host='www.iowaattorneygeneral.gov')
        if not urlsplit(notice).path.lower().endswith('.pdf'):
            # The 2024 source publishes an actual href="=". Its receipt row
            # remains rejected rather than inventing an evidence identity or
            # discarding every other valid row from that annual archive.
            rejected += 1
            continue
        flags = []
        if supplemental_only:
            flags.append({'code': 'supplemental_notice_only', 'message': 'The source lists a supplemental notice without a separate initial document.'})
        reported = parse_date(dates[0].get_text(' '), flags, 'Date reported to the Iowa attorney general', today=today)
        if reported and not reported.startswith(str(year) + '-'):
            flags.append({'code': 'archive_year_mismatch', 'message': 'The source-reported receipt date differs from its annual archive.'})
        secondary = []
        for link in card.select('a.sby-file-link.secondary[href]'):
            if link is primary[0]:
                continue
            if not urlsplit(link['href']).path.lower().endswith('.pdf'):
                # Some links are external informational web pages, not notices.
                # Do not follow them or let them prevent collecting the public PDF.
                flags.append({'code': 'informational_link_not_collected', 'message': 'An additional informational web link is available on the annual page; it was not collected.'})
                continue
            official_url(page_url, link['href'], host='www.iowaattorneygeneral.gov')
            secondary.append(link)
        industry = card.select_one('.sby-industry-value')
        summary = f'Iowa annual notice archive {year}.'
        if industry:
            summary += f' Source industry: {clean(industry.get_text(" "))}.'
        if secondary:
            summary += f' {len(secondary)} supplemental notice link(s) are available on the annual source page.'
            flags.append({'code': 'supplements_not_enriched', 'message': 'Supplemental documents are linked from the annual page; their contents were not parsed.'})
        # Matches the prior adapter's document-URL hash identity convention.
        native = sha256(notice.encode()).hexdigest()[:24]
        reports.append(Report('iowa', native, organization, page_url, reported_date=reported,
                              notice_url=notice, summary=summary, quality_flags=flags, parser_version=PARSER_VERSION))
    return reports, len(cards), rejected


def maine_archive_links(html, page_url=MAINE_ARCHIVES):
    links = []
    for a in BeautifulSoup(html, 'html.parser').select('a[href]'):
        label = clean(a.get_text(' '))
        if 'data breach notices' in label.lower() and urlsplit(a['href']).path.lower().endswith('.xlsx'):
            links.append((label, official_url(page_url, a['href'], host='www.maine.gov')))
    if not links or len(links) > 8 or len({url for _, url in links}) != len(links):
        raise SourceError('Maine: public breach archive links are missing, duplicated, or unexpectedly expanded')
    return links


def _xml(content):
    declarations = content.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
        raise SourceError('Maine: spreadsheet XML declarations are unsupported')
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceError('Maine: malformed spreadsheet XML') from exc


def xlsx_rows(content):
    """Read bounded OOXML cell values without formulas, external links or macros.

    Iterate actual cells, never the enormous formatting dimensions in the older
    archive. Do not allocate its 3,665-column formatted rectangle.
    """
    try:
        if len(content) > MAX_XLSX_BYTES:
            raise SourceError('Maine: spreadsheet exceeds its compressed size budget')
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 100 or sum(m.file_size for m in members) > MAX_XLSX_EXPANDED_BYTES:
                raise SourceError('Maine: spreadsheet exceeds its decompressed size budget')
            if len({m.filename for m in members}) != len(members):
                raise SourceError('Maine: duplicated spreadsheet members')
            if any(m.flag_bits & 1 or m.compress_type not in (ZIP_STORED, ZIP_DEFLATED) for m in members):
                raise SourceError('Maine: encrypted or unsupported spreadsheet compression')
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                strings = [''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t'))
                           for si in _xml(archive.read('xl/sharedStrings.xml')).findall('{*}si')]
            workbook = _xml(archive.read('xl/workbook.xml'))
            props = workbook.find('{*}workbookPr')
            if props is not None and props.get('date1904', 'false').strip().lower() not in ('0', 'false'):
                raise SourceError('Maine: unsupported 1904 spreadsheet date system')
            sheets, count, cells_seen = [], 0, 0
            for name in archive.namelist():
                if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name):
                    continue
                rows = []
                for row in _xml(archive.read(name)).findall('.//{*}sheetData/{*}row'):
                    count += 1
                    if count > MAX_XLSX_ROWS:
                        raise SourceError('Maine: spreadsheet row budget exceeded')
                    values = {}
                    for cell in row.findall('{*}c'):
                        cells_seen += 1
                        if cells_seen > MAX_XLSX_CELLS:
                            raise SourceError('Maine: spreadsheet cell budget exceeded')
                        if cell.find('{*}f') is not None:
                            raise SourceError('Maine: formula cells cannot establish public report values')
                        ref = re.fullmatch(r'([A-Z]+)\d+', cell.get('r', ''))
                        if not ref:
                            raise SourceError('Maine: invalid spreadsheet cell reference')
                        v = cell.find('{*}v')
                        value = v.text or '' if v is not None else ''
                        kind = cell.get('t')
                        if kind == 's' and value:
                            if not value.isdigit() or int(value) >= len(strings):
                                raise SourceError('Maine: invalid shared-string cell')
                            value = strings[int(value)]
                        elif kind == 'inlineStr':
                            value = ''.join(t.text or '' for t in cell.findall('.//{*}t'))
                        elif kind == 'b':
                            if value not in ('0', '1'):
                                raise SourceError('Maine: invalid boolean spreadsheet cell')
                            value = 'true' if value == '1' else 'false'
                        elif kind == 'e':
                            raise SourceError('Maine: spreadsheet contains error cells')
                        elif kind not in (None, 'n', 'str', 'd', 's'):
                            raise SourceError('Maine: unsupported spreadsheet cell type')
                        if ref[1] in values:
                            raise SourceError('Maine: duplicated spreadsheet cell reference')
                        if clean(value):
                            values[ref[1]] = (clean(value), kind in (None, 'n'))
                    if values:
                        rows.append(values)
                if rows:
                    sheets.append(rows)
            if not sheets:
                raise SourceError('Maine: no populated public spreadsheet sheets')
            return sheets
    except SourceError:
        raise
    except (BadZipFile, KeyError, ValueError, RuntimeError) as exc:
        raise SourceError('Maine: invalid public spreadsheet structure') from exc


def _archive_date(cell, flags, label, *, today=None):
    raw, numeric = cell or ('', False)
    if numeric and re.fullmatch(r'\d+(?:\.\d+)?', raw):
        value = float(raw)
        if 1 <= value <= 100_000:
            parsed = (datetime(1899, 12, 30) + timedelta(days=value)).date()
            return parse_date(parsed.isoformat(), flags, label, today=today)
    # Completed Date is an explicit submission timestamp; retain its calendar day.
    match = re.fullmatch(r'(\d{1,2}/\d{1,2}/\d{4}) \d{1,2}:\d{2}:\d{2} [AP]M', raw)
    return parse_date(match[1] if match else raw, flags, label, today=today)


def parse_maine_archive(content, document_url, label, *, today=None):
    reports, parsed, rejected = [], 0, 0
    for rows in xlsx_rows(content):
        header, schema = None, None
        for row in rows:
            names = {key(value[0]): column for column, value in row.items()}
            if {'completeddate', 'entityname', 'totalnumberofmaineresidentsaffected'} <= names.keys():
                header, schema = names, 'submission'; continue
            if {'companywhosedatawasbreached', 'dateofnotification', 'numberofmaineresidentsaffected'} <= names.keys():
                header, schema = names, 'legacy'; continue
            if header is None:
                if len(row) == 1 and 'data breach notices' in next(iter(row.values()))[0].lower():
                    continue
                raise SourceError('Maine: archive named report columns changed')
            def cell(name): return row.get(header.get(name), ('', False))
            def value(name): return cell(name)[0]
            parsed += 1
            flags = [{'code': 'historical_archive_only', 'message': 'Historical archive through September 14, 2020. The current public database is offline.'},
                     {'code': 'derived_identity', 'message': 'The archive has no stable report ID. Identity uses organization and source dates; date/name corrections may appear as new reports.'}]
            if schema == 'submission':
                organization, _ = maine_organization(value('entityname'))
                if organization is None:
                    rejected += 1; continue
                received = _archive_date(cell('completeddate'), flags, 'Report completed', today=today)
                breach = _archive_date(cell('datesbreachoccurred'), flags, 'Breach occurred', today=today)
                discovered = _archive_date(cell('datebreachdiscovered'), flags, 'Breach discovered', today=today)
                count, qualifier = parse_count(value('totalnumberofmaineresidentsaffected'), flags, 'Maine residents affected')
                types = [name for name, col in header.items() if name in ('socialsecuritynumber', 'driverslicensenumberornondriveridentificationcardnumber', 'financialaccountnumberorcreditordebitcardnumberincombinationwiththesecuritycodeaccesscodepasswordorpinfortheaccount') and row.get(col, ('', False))[0].lower() == 'true']
                type_labels = {'socialsecuritynumber': 'Social Security number', 'driverslicensenumberornondriveridentificationcardnumber': "Driver's license or state identification number", 'financialaccountnumberorcreditordebitcardnumberincombinationwiththesecuritycodeaccesscodepasswordorpinfortheaccount': 'Financial account or payment-card credentials'}
                types = [type_labels[t] for t in types]
                identity_dates = [value('completeddate'), value('datesbreachoccurred')]
                summary = 'Historical Maine report archive. Report completion date is used as the reported date. '
                summary += f'Source-reported total persons affected: {value("totalnumberofpersonsaffectedincludingmaineresidents") or "not reported"}. '
            else:
                organization, split = maine_organization(value('companywhosedatawasbreached'), legacy=True)
                if organization is None:
                    rejected += 1; continue
                if split:
                    flags.append({'code': 'entity_address_split', 'message': 'The legacy archive combines organization and postal address; a clearly delimited postal-address suffix was omitted.'})
                received = None
                breach = _archive_date(cell('dateofbreach'), flags, 'Breach occurred', today=today)
                discovered = None
                count, qualifier = parse_count(value('numberofmaineresidentsaffected'), flags, 'Maine residents affected')
                types = maine_legacy_data_types(value('typeofinformation'), flags)
                identity_dates = [value('dateofnotification'), value('dateofbreach')]
                summary = 'Historical Maine report archive. Consumer-notification dates are not treated as publication or AG receipt dates. '
            if not organization or len(organization) > 500:
                rejected += 1; continue
            native = 'archive-' + sha256(json.dumps([schema, organization.casefold(), *identity_dates], ensure_ascii=False).encode()).hexdigest()[:24]
            summary += 'Displayed affected count is Maine residents only; notice documents and current reports are outside this collection.'
            reports.append(Report('maine', native, organization, document_url, reported_date=received,
                                  breach_start=breach, discovery_date=discovered, affected_count=count,
                                  affected_scope='state', affected_jurisdiction='ME', affected_qualifier=qualifier,
                                  data_types=types, summary=summary, quality_flags=flags, parser_version=PARSER_VERSION))
    return reports, parsed, rejected


def finish(source, reports, parsed, rejected, **kwargs):
    """Withhold every conflicting identity, rather than choose a count/version."""
    groups = {}
    for report in reports:
        groups.setdefault(report.native_id, []).append(report)
    retained = []
    conflicts = 0
    for group in groups.values():
        if any(r != group[0] for r in group[1:]):
            rejected += len(group); conflicts += len(group)
        else:
            retained.extend(group)
    if conflicts:
        kwargs['message'] += f' Withheld {conflicts} rows with conflicting derived identities.'
    return checked(source, retained, parsed, rejected, **kwargs)


def collect(source_id, *, max_pages=None):
    if source_id not in SOURCES:
        raise SourceError(f'Unknown rediscovered source: {source_id}')
    limit = (16 if source_id == 'iowa' else 2) if max_pages is None else max_pages
    if type(limit) is not int or not 1 <= limit <= 40:
        raise SourceError('max_pages must be an integer between 1 and 40')
    client = PublicClient(max_requests=limit + 3, max_bytes=20_000_000, deadline_seconds=180)
    reports, parsed, rejected = [], 0, 0
    stop = ''
    try:
        if source_id == 'iowa':
            response = client.request(SOURCES[source_id]['homepage'] + '/')
            links_by_year = dict(iowa_year_links(response.text, response.url))
            # The site's current sitemap contains the real older plural/bare-year
            # URLs. Several URLs in the year-selector script are stale and 404.
            sitemap_link = next((a['href'] for a in BeautifulSoup(response.text, 'html.parser').select('a[href]')
                                 if a.get_text(' ', strip=True).lower() == 'sitemap'), None)
            if sitemap_link:
                sitemap = client.request(official_url(response.url, sitemap_link, host='www.iowaattorneygeneral.gov'))
                links_by_year.update(iowa_year_links(sitemap.text, sitemap.url))
            links = sorted(links_by_year.items(), reverse=True)
            pages, collected_years = 0, []
            for year, url in links[:limit]:
                try:
                    page = client.request(url)
                    current, count, bad = parse_iowa_cards(page.text, page.url, year)
                except SourceError as exc:
                    if not reports: raise
                    stop = f' Collection stopped: {exc}'; break
                reports.extend(current); parsed += count; rejected += bad; pages += 1
                collected_years.append(year)
            complete = pages == len(links) and not stop
            return finish(source_id, reports, parsed, rejected, complete=complete,
                           message=f'Parsed {pages} of {len(links)} published annual card archives (years: {", ".join(map(str, collected_years))}). Receipt dates and original notice links retained; PDFs and supplemental contents were not enriched.{stop}',
                           evidence={'pages': pages, 'annual_archives': len(links), 'years': collected_years, 'coverage': 'official_annual_cards'})
        current = client.request(SOURCES[source_id]['homepage'])
        current_text = clean(BeautifulSoup(current.text, 'html.parser').get_text(' ')).lower()
        if not re.search(r'public[- ]facing database.{0,50}(?:remain|is|be).{0,15}offline', current_text):
            raise SourceError('Maine: current database status changed; rediscover current coverage before claiming archive-only availability')
        archive_link = next((a['href'] for a in BeautifulSoup(current.text, 'html.parser').select('a[href]') if a.get_text(' ', strip=True) == 'Archives' and '/ag/news-and-library/archives' in a['href']), None)
        if not archive_link:
            raise SourceError('Maine: current source no longer links its public archives; rediscovery required')
        archive = client.request(official_url(current.url, archive_link, host='www.maine.gov'))
        links = maine_archive_links(archive.text, archive.url)
        documents = 0
        for label, url in links[:limit]:
            try:
                current, count, bad = parse_maine_archive(client.request(url).content, url, label)
            except SourceError as exc:
                if not reports: raise
                stop = f' Archive collection stopped: {exc}'; break
            reports.extend(current); parsed += count; rejected += bad; documents += 1
        return finish(source_id, reports, parsed, rejected, complete=False,
                       message=f'Recovered {documents} of {len(links)} publicly linked historical Excel archives through September 14, 2020. Current database remains offline; these archives do not establish current coverage.{stop}',
                       evidence={'documents': documents, 'coverage': 'historical_archives', 'coverage_through': '2020-09-14'})
    finally:
        client.close()
