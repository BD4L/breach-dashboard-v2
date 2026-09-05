"""Read-only fixed-endpoint diagnostic. Outputs metadata, never response bodies.

Each endpoint runs in its own process with a 60-second hard wall-clock deadline.
The diagnostic is deliberately separate from collection, durable state and Pages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# Running this file directly also works on Windows runners.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bs4 import BeautifulSoup
import requests
from ingestion.models import SourceError
from ingestion.network import OFFICIAL_HOSTS, PublicClient

USER_AGENT = 'BreachDashboard/2.0 (+https://github.com/BD4L/breach-dashboard-v2)'
MAX_BYTES = 6_000_000
DEADLINE = 60
# Probe-only: this documented public SEC sample endpoint is not added to the
# production collector allowlist until the independent probe is reviewed.
OFFICIAL_HOSTS.add('data.sec.gov')
MD_CATALOG = ("https://oag.maryland.gov/resources-info/_api/web/lists?"
              "$select=Title,Hidden,ItemCount&$filter=startswith(Title,'Security-Breach-Notices')%20and%20Hidden%20eq%20false")
MD_ITEMS = ("https://oag.maryland.gov/resources-info/_api/web/lists/getbytitle('Security-Breach-Notices-2025')/items?"
            "$top=1&$select=Title,Date_x0020_Received,Case_x0020_No_x002e_,No_x0020_of_x0020_Maryland_x0020,Information_x0020_Breached,How_x0020_Breach_x0020_Occurred&$orderby=Id%20asc")
NJ_RSS = 'https://www.cyber.nj.gov/rss.xml'
ENDPOINTS = {
    'maryland-catalog': (MD_CATALOG, 'md_catalog'),
    'maryland-2025': (MD_ITEMS, 'md_items'),
    'wisconsin-current': ('https://datcp.wi.gov/Pages/Programs_Services/DataBreaches.aspx', 'wi'),
    'wisconsin-archive': ('https://datcp.wi.gov/Pages/Programs_Services/DataBreachArchive.aspx', 'wi'),
    'new-jersey-current': ('https://www.cyber.nj.gov/threat-center/public-data-breaches', 'nj'),
    'new-jersey-rss': (NJ_RSS, 'rss'),
    'massachusetts-annual': ('https://www.mass.gov/doc/data-breach-report-2026/download', 'pdf'),
    'massachusetts-archive': ('https://www.mass.gov/archive/data-breach-notification-letters', 'ma_archive'),
    'massachusetts-september': ('https://www.mass.gov/lists/data-breach-notification-letters-september-2026', 'ma_month'),
    'iowa-2026': ('https://www.iowaattorneygeneral.gov/for-consumers/security-breach-notifications/2026-security-breach-notification', 'ia'),
    'maine-archives': ('https://www.maine.gov/ag/news-and-library/archives', 'me'),
    'new-hampshire-current': ('https://www.doj.nh.gov/citizens/consumer-protection-antitrust-bureau/security-breach-notifications', 'nh'),
    'new-hampshire-api': ('https://www.doj.nh.gov/content/api/documents?iterate_nodes=true&q=%40field_document_category%7C%3D%7C2146&textsearch=&sort=field_date_posted%7Cdesc%7CALLOW_NULLS&filter_mode=inclusive&type=document&page=1&size=15', 'nh_json'),
    'sec-search-html': ('https://www.sec.gov/edgar/search/', 'sec_html'),
    'sec-company-submissions': ('https://data.sec.gov/submissions/CIK0000320193.json', 'sec_submissions'),
    'sec-full-text-query': ('https://efts.sec.gov/LATEST/search-index?q=%22material%20cybersecurity%20incidents%22&dateRange=30d&startdt=2026-08-06&enddt=2026-09-05', 'sec_efts'),
    'sec-current-atom': ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&owner=include&count=10&output=atom', 'atom'),
}
BROWSER_ENDPOINTS = ('massachusetts-september', 'new-hampshire-current', 'new-jersey-current', 'sec-search-html', 'new-hampshire-api', 'sec-full-text-query')
CHALLENGE = re.compile(r'_Incapsula_Resource|captcha|Request unsuccessful|Access Denied|Your Request Originates from an Undeclared Automated Tool', re.I)


def timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def shape_metadata(content: bytes, expected: str):
    """Only counts and booleans leave this function; no source record payloads."""
    result = {'expectedShape': False, 'reportLinkCount': 0, 'challenge': False}
    text = content.decode('utf-8-sig', errors='replace')
    result['challenge'] = bool(CHALLENGE.search(text)) if expected != 'pdf' else False
    if result['challenge']:
        return result
    if expected == 'pdf':
        result['expectedShape'] = content.startswith(b'%PDF-')
        return result
    if expected in ('md_catalog', 'md_items', 'sec_submissions', 'sec_efts', 'nh_json'):
        try:
            data = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            return result
        if expected.startswith('md_'):
            rows = data.get('d', {}).get('results') if isinstance(data, dict) else None
            fields = {'Title', 'Hidden', 'ItemCount'} if expected == 'md_catalog' else {'Title', 'Date_x0020_Received', 'Case_x0020_No_x002e_'}
            result['expectedShape'] = isinstance(rows, list) and bool(rows) and all(isinstance(r, dict) and fields <= r.keys() for r in rows)
            result['rowCount'] = len(rows) if isinstance(rows, list) else 0
        elif expected == 'nh_json':
            rows = data.get('data') if isinstance(data, dict) else None
            result['expectedShape'] = isinstance(rows, list) and isinstance(data.get('total'), int) and isinstance(data.get('last_page'), int)
            result['rowCount'] = len(rows) if isinstance(rows, list) else 0
            if isinstance(data, dict) and isinstance(data.get('total'), int):
                result['sourceTotal'] = data['total']
        elif expected == 'sec_submissions':
            recent = data.get('filings', {}).get('recent', {}) if isinstance(data, dict) else {}
            result['expectedShape'] = isinstance(recent.get('accessionNumber'), list) and isinstance(recent.get('form'), list)
            result['rowCount'] = len(recent.get('accessionNumber', []))
        else:
            hits = data.get('hits', {}).get('hits') if isinstance(data, dict) else None
            result['expectedShape'] = isinstance(hits, list)
            result['rowCount'] = len(hits) if isinstance(hits, list) else 0
        return result
    if expected in ('rss', 'atom'):
        if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
            return result
        try:
            root = ET.fromstring(content)
            entries = root.findall('./channel/item') if expected == 'rss' else root.findall('{http://www.w3.org/2005/Atom}entry')
            result['expectedShape'] = root.tag == ('rss' if expected == 'rss' else '{http://www.w3.org/2005/Atom}feed')
            result['rowCount'] = len(entries)
        except ET.ParseError:
            pass
        return result
    soup = BeautifulSoup(text, 'html.parser')
    links = [a.get('href', '') for a in soup.find_all('a', href=True)]
    visible = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True).replace('\u200b', ''))
    if expected == 'wi':
        count = len(re.findall(r'Company\s+Name\s*:', visible, re.I))
        result.update(expectedShape=count > 0 and 'Date Public Notified' in visible, rowCount=count)
    elif expected == 'ma_archive':
        result['reportLinkCount'] = sum('/lists/data-breach-notification-letters-' in href for href in links)
        result['expectedShape'] = result['reportLinkCount'] > 0
    elif expected == 'ma_month':
        result['reportLinkCount'] = sum('/doc/' in href and '/download' in href for href in links)
        result['expectedShape'] = result['reportLinkCount'] > 0
    elif expected == 'ia':
        result['rowCount'] = len(soup.select('.sby-record-grid, .sby-related-grid'))
        result['reportLinkCount'] = len(soup.select('a.sby-file-link[href]'))
        result['expectedShape'] = result['rowCount'] > 0 and result['reportLinkCount'] > 0
    elif expected == 'me':
        result['reportLinkCount'] = sum('breach' in href.lower() or 'id=' in href.lower() for href in links)
        result['expectedShape'] = 'archive' in visible.lower() and result['reportLinkCount'] > 0
    elif expected == 'nh':
        result['reportLinkCount'] = sum('remote-docs/' in href or href.lower().endswith('.pdf') and ('breach' in href.lower() or 'security' in href.lower()) for href in links)
        result['expectedShape'] = result['reportLinkCount'] > 0
    elif expected == 'nj':
        result['reportLinkCount'] = sum('/public-data-breaches/' in href for href in links)
        result['expectedShape'] = result['reportLinkCount'] > 0
    elif expected == 'sec_html':
        result['reportLinkCount'] = sum('/Archives/edgar/data/' in href for href in links)
        result['expectedShape'] = bool(soup.select('input#keywords, input#entity, input[name="q"], form#search-form')) or 'EDGAR full text search' in visible
    return result


class MetadataSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.status = None
        self.content_type = None

    def request(self, *args, **kwargs):
        response = super().request(*args, **kwargs)
        self.status = response.status_code
        self.content_type = response.headers.get('Content-Type', '')[:100]
        return response


def error_code(error, status=None):
    if status in (401, 403, 429):
        return 'access_denied'
    value = str(error).lower()
    if 'tls' in value or 'certificate' in value:
        return 'tls_failure'
    if 'budget' in value:
        return 'byte_or_time_budget'
    if 'timeout' in value or isinstance(error, subprocess.TimeoutExpired):
        return 'timeout'
    return 'network_or_schema_error'


def http_probe(endpoint):
    url, expected = ENDPOINTS[endpoint]
    session = MetadataSession()
    client = PublicClient(session=session, max_requests=8, max_bytes=MAX_BYTES, deadline_seconds=55)
    client.session.headers['User-Agent'] = USER_AGENT
    result = {'endpoint': endpoint, 'mode': 'http', 'status': None, 'contentType': None, 'bytes': 0, 'sha256': None}
    try:
        accept = 'application/json;odata=verbose' if expected.startswith('md_') else 'application/json' if expected.startswith('sec_') and expected != 'sec_html' else 'application/rss+xml,application/atom+xml,text/html,application/pdf,*/*'
        response = client.request(url, headers={'Accept': accept})
        result.update(status=session.status, contentType=response.content_type, bytes=len(response.content),
                      sha256=hashlib.sha256(response.content).hexdigest(), **shape_metadata(response.content, expected))
    except Exception as exc:
        result.update(status=session.status, contentType=session.content_type, bytes=client.bytes,
                      error=error_code(exc, session.status), expectedShape=False)
    finally:
        client.close()
    return result


def browser_probe(endpoint):
    """Fresh ordinary Chromium, no cookies, proxy, stealth or challenge solving."""
    from playwright.sync_api import sync_playwright
    url, expected = ENDPOINTS[endpoint]
    result = {'endpoint': endpoint, 'mode': 'browser', 'status': None, 'contentType': None,
              'bytes': 0, 'sha256': None, 'pageTitle': None}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, timeout=15_000)
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()
        # Keep Chromium's real User-Agent and append the truthful operator identity.
        agent = page.evaluate('navigator.userAgent')
        context.set_extra_http_headers({'User-Agent': agent + ' ' + USER_AGENT})
        # Images/fonts/media do not affect report-link or data-schema inspection.
        page.route('**/*', lambda route: route.abort() if route.request.resource_type in ('image', 'media', 'font') else route.continue_())
        session = context.new_cdp_session(page)
        session.send('Network.enable')
        usage = {'bytes': 0, 'exceeded': False}
        def received(event):
            usage['bytes'] += int(event.get('dataLength', 0))
            if usage['bytes'] > MAX_BYTES and not usage['exceeded']:
                usage['exceeded'] = True
                session.send('Page.stopLoading')
        session.on('Network.dataReceived', received)
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=35_000)
            if response:
                result['status'] = response.status
                result['contentType'] = response.headers.get('content-type', '')[:100]
            json_mode = expected in ('sec_efts', 'nh_json')
            content = response.body() if json_mode and response else page.content().encode()
            shape = shape_metadata(content, expected)
            if not json_mode and result['status'] not in (401, 403, 429) and not shape.get('challenge') and not shape['expectedShape']:
                selectors = {'ma_month': 'a[href*="/doc/"][href*="/download"]', 'nh': 'a[href*="/remote-docs/"]',
                             'nj': 'a[href*="/public-data-breaches/"]', 'sec_html': 'input#keywords'}
                try:
                    page.wait_for_selector(selectors[expected], state='attached', timeout=5_000)
                except Exception:
                    pass
                content = page.content().encode()
            if usage['exceeded'] or len(content) > MAX_BYTES:
                raise SourceError('Browser byte budget exhausted')
            title = re.sub(r'\s+', ' ', page.title()).strip()[:160]
            result.update(bytes=len(content), receivedBytes=usage['bytes'], sha256=hashlib.sha256(content).hexdigest(),
                          pageTitle=title, **shape_metadata(content, expected))
            if result['status'] in (401, 403, 429):
                result['error'] = 'access_denied'
        except Exception as exc:
            result.update(bytes=usage['bytes'], error=error_code(exc, result['status']), expectedShape=False)
        finally:
            context.close()
            browser.close()
    return result


def bounded_probe(endpoint, mode):
    command = [sys.executable, str(Path(__file__).resolve()), '--endpoint', endpoint, '--mode', mode]
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=REPO, start_new_session=os.name != 'nt')
    try:
        stdout, _ = process.communicate(timeout=DEADLINE)
        if process.returncode != 0:
            result = {'endpoint': endpoint, 'mode': mode, 'expectedShape': False, 'error': 'probe_process_failed'}
        else:
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise ValueError('Unexpected probe output')
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=5)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        result = {'endpoint': endpoint, 'mode': mode, 'expectedShape': False, 'error': 'hard_deadline'}
    except (ValueError, OSError):
        result = {'endpoint': endpoint, 'mode': mode, 'expectedShape': False, 'error': 'invalid_probe_output'}
    result['elapsedSeconds'] = round(time.monotonic() - started, 2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--browsers', action='store_true')
    parser.add_argument('--endpoint', choices=tuple(ENDPOINTS))
    parser.add_argument('--mode', choices=('http', 'browser'), default='http')
    args = parser.parse_args(argv)
    if args.endpoint:
        if args.mode == 'browser' and args.endpoint not in BROWSER_ENDPOINTS:
            parser.error('Browser mode is limited to the six declared endpoints')
        try:
            result = http_probe(args.endpoint) if args.mode == 'http' else browser_probe(args.endpoint)
        except Exception:
            result = {'endpoint': args.endpoint, 'mode': args.mode, 'expectedShape': False, 'error': 'probe_initialization_failed'}
        print(json.dumps(result, separators=(',', ':')))
        return 0
    if not args.output:
        parser.error('--output is required for the complete diagnostic')
    report = {'schemaVersion': 1, 'observedAt': timestamp(), 'system': platform.system(),
              'runnerOS': os.environ.get('RUNNER_OS', ''), 'python': platform.python_version(),
              'identity': USER_AGENT, 'maxBytesPerEndpoint': MAX_BYTES, 'hardDeadlineSeconds': DEADLINE, 'results': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for mode, endpoints in [('http', ENDPOINTS), ('browser', BROWSER_ENDPOINTS if args.browsers else ())]:
        for endpoint in endpoints:
            result = bounded_probe(endpoint, mode)
            report['results'].append(result)
            args.output.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(result, separators=(',', ':')), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
