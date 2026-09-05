"""One production listing request per source through the local Chrome transport.

Read-only diagnostics: no collection, retries, pagination, state merge or publish.
Only fixed metadata and parser counts leave each bounded worker, never bodies,
headers, cookies, addresses or raw exception messages.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ingestion.local_browser import LOCAL_SOURCES, LocalBrowserClient
from ingestion.models import SourceError
from ingestion.rediscovered_nj import HOMEPAGE, parse_page
from ingestion.rediscovered_northeast import nh_api_url, parse_nh_api
from ingestion.rediscovered_sec import parse_search_page, search_url
from ingestion.runner import atomic_json, supervise
from ingestion.validation import timestamp

MAX_BYTES = 6_000_000
SOURCE_DEADLINE = 60
OVERALL_DEADLINE = 195
TRANSPORT = 'ingestion.local_browser.LocalBrowserClient:headed_chrome_javascript_disabled'
DESCRIPTIONS = {
    'new_hampshire': 'Production breach category 2146; first page; 25 rows',
    'new_jersey': 'Production canonical public data breach listing; first current page',
    'sec': 'Production full 8-K search; UTC 30-day window; offset 0; no keyword filter',
}


def endpoints(today):
    if type(today) is not date:
        raise ValueError('A UTC calendar date is required')
    return {'new_hampshire': nh_api_url(1, page_size=25), 'new_jersey': HOMEPAGE,
            'sec': search_url(today - timedelta(days=30), today, 0)}


def runtime_metadata():
    try:
        playwright_version = version('playwright')
    except PackageNotFoundError:
        playwright_version = None
    return {'python': platform.python_version(), 'platform': platform.system(),
            'architecture': platform.machine(), 'playwright': playwright_version}


def base_result(source, today):
    if source not in LOCAL_SOURCES:
        raise ValueError('Unknown fixed diagnostic source')
    return {'sourceId': source, 'url': endpoints(today)[source],
            'description': DESCRIPTIONS[source], 'transport': TRANSPORT,
            'utcDate': today.isoformat(),
            'windowStart': (today - timedelta(days=30)).isoformat() if source == 'sec' else None,
            'windowEnd': today.isoformat() if source == 'sec' else None,
            'requestLimit': 1, 'requests': 0, 'bytes': 0, 'httpStatus': None,
            'expectedShape': False, 'success': False, 'errorCode': None,
            'challenge': False, 'durationSeconds': 0, 'chromeVersion': None,
            'workerCompleted': False}


def classify_error(error):
    """Return only fixed classifications; upstream errors may contain payloads."""
    text = str(error).lower()
    match = re.search(r'\bhttp ([1-5]\d\d)\b', text)
    status = int(match[1]) if match else None
    if status in (401, 403, 429):
        code = 'access_denied'
    elif 'access challenge' in text:
        code = 'access_challenge'
    elif 'redirect' in text:
        code = 'redirect_blocked'
    elif 'authentication request' in text:
        code = 'authentication_blocked'
    elif 'deadline' in text or 'time budget' in text or 'timeout' in text:
        code = 'timeout'
    elif 'byte budget' in text or 'oversized' in text:
        code = 'byte_budget'
    elif 'could not start' in text or 'dependencies are missing' in text:
        code = 'browser_unavailable'
    elif status is not None:
        code = 'http_error'
    else:
        code = 'network_or_schema_error'
    return {'httpStatus': status, 'errorCode': code, 'challenge': code == 'access_challenge'}


def shape_metadata(source, content, today):
    if source == 'new_hampshire':
        result, total, pages = parse_nh_api(json.loads(content), page=1, page_size=25, today=today)
        return {'expectedShape': True, 'rowCount': result.parsed, 'acceptedCount': len(result.reports),
                'rejectedCount': result.rejected, 'sourceTotal': total, 'sourcePages': pages}
    if source == 'new_jersey':
        result = parse_page(content.decode('utf-8-sig'), HOMEPAGE, today=today)
        return {'expectedShape': True, 'rowCount': result.parsed, 'acceptedCount': len(result.reports),
                'rejectedCount': result.rejected, 'sourceTotal': result.total}
    if source == 'sec':
        reports, hits, total, relation = parse_search_page(content, start=today-timedelta(days=30), end=today)
        return {'expectedShape': True, 'rowCount': len(hits), 'acceptedCount': len(reports),
                'sourceTotal': total, 'totalExact': relation == 'eq'}
    raise ValueError('Unknown fixed diagnostic source')


def probe_source(source, today):
    result = base_result(source, today)
    started = time.monotonic()
    client = None
    try:
        client = LocalBrowserClient(source, max_requests=1, max_bytes=MAX_BYTES,
                                    deadline_seconds=50, max_response_bytes=MAX_BYTES)
        response = client.request(result['url'])
        result['httpStatus'] = 200  # This client returns only verified HTTP 200 responses.
        result.update(shape_metadata(source, response.content, today))
        result['success'] = True
    except Exception as error:
        failure = classify_error(error)
        if result['httpStatus'] == 200:
            failure['httpStatus'] = 200  # A parser failure does not erase transport evidence.
        result.update(failure)
    finally:
        if client is not None:
            result.update(requests=client.requests, bytes=client.bytes)
            browser = getattr(client, '_browser', None)
            chrome = getattr(browser, 'version', None)
            if isinstance(chrome, str) and re.fullmatch(r'\d+(?:\.\d+){1,4}', chrome):
                result['chromeVersion'] = chrome
            client.close()
        result['durationSeconds'] = round(time.monotonic()-started, 3)
        result['workerCompleted'] = True
    return result


def run(output):
    today = datetime.now(timezone.utc).date()
    started = time.monotonic()
    results = []
    report = {'schemaVersion': 1, 'mode': 'matched-browser', 'startedAt': timestamp(),
              'runtime': runtime_metadata(), 'sourceDeadlineSeconds': SOURCE_DEADLINE,
              'overallDeadlineSeconds': OVERALL_DEADLINE, 'results': results}
    with tempfile.TemporaryDirectory(prefix='breach-matched-browser-') as directory:
        for source in LOCAL_SOURCES:
            result = base_result(source, today)
            source_started = time.monotonic()
            remaining = OVERALL_DEADLINE - (source_started - started)
            try:
                if remaining <= 0:
                    raise SourceError('Overall diagnostic deadline exceeded')
                path = Path(directory)/f'{source}.json'
                command = [sys.executable, str(Path(__file__).resolve()), '_worker',
                           '--source', source, '--utc-date', today.isoformat(), '--output', str(path)]
                status = supervise(command, timeout=min(SOURCE_DEADLINE, remaining))
                if status != 0 or not path.is_file() or path.stat().st_size > 16_384:
                    raise SourceError('Worker did not return bounded diagnostic metadata')
                value = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or value.get('sourceId') != source or value.get('url') != result['url']:
                    raise SourceError('Worker returned mismatched diagnostic metadata')
                result = value
            except Exception as error:
                result.update(classify_error(error))
                # A killed or missing worker may have made its single request;
                # unknown counts must not be reported as measured zeroes.
                result.update(requests=None, bytes=None)
                result['durationSeconds'] = round(time.monotonic()-source_started, 3)
            results.append(result)
            # Preserve completed source diagnostics if a later source cannot finish.
            report['completedAt'] = timestamp()
            atomic_json(output, report)
    # A denied endpoint is an observed diagnostic result, not a failed workflow.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', '_worker'), nargs='?', default='run')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', choices=LOCAL_SOURCES)
    parser.add_argument('--utc-date', type=date.fromisoformat)
    args = parser.parse_args(argv)
    if args.command == 'run':
        if args.source is not None or args.utc_date is not None:
            parser.error('The public diagnostic always probes the three fixed sources using the current UTC date')
        return run(args.output)
    if args.source is None or args.utc_date is None:
        parser.error('Internal worker requires its fixed source and UTC date')
    today = datetime.now(timezone.utc).date()
    if not today-timedelta(days=1) <= args.utc_date <= today:
        parser.error('Internal worker date must be the current UTC day or preceding day across midnight')
    atomic_json(args.output, probe_source(args.source, args.utc_date))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
