"""Fixed transport/endpoint diagnostic contracts; no external requests."""
from datetime import date, datetime, timezone
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from ingestion.models import SourceError
from ingestion.network import Response
from scripts import matched_browser_probe as p

FIXTURES = Path(__file__).parent/'fixtures'
TODAY = date(2026, 9, 5)


class MatchedBrowserProbeTests(unittest.TestCase):
    def test_exact_production_first_page_queries(self):
        urls = p.endpoints(TODAY)
        self.assertEqual(urls['new_jersey'], 'https://www.cyber.nj.gov/threat-landscape/public-data-breaches')
        self.assertEqual(parse_qs(urlsplit(urls['new_hampshire']).query, keep_blank_values=True), {
            'iterate_nodes': ['true'], 'q': ['@field_document_category|=|2146'], 'textsearch': [''],
            'sort': ['field_date_posted|desc|ALLOW_NULLS'], 'filter_mode': ['inclusive'],
            'type': ['document'], 'page': ['1'], 'size': ['25']})
        self.assertEqual(parse_qs(urlsplit(urls['sec']).query), {
            'dateRange': ['custom'], 'category': ['custom'], 'forms': ['8-K'],
            'startdt': ['2026-08-06'], 'enddt': ['2026-09-05'], 'from': ['0']})
        self.assertEqual(p.base_result('sec', TODAY)['windowStart'], '2026-08-06')

    def test_unknown_source_and_arbitrary_url_or_page_input_fail_without_browser(self):
        with patch.object(p, 'LocalBrowserClient') as client:
            with self.assertRaises(ValueError):
                p.probe_source('https://example.invalid', TODAY)
            for extra in (['--url', 'https://example.invalid'], ['--max-pages', '10'],
                          ['--source', 'sec'], ['--utc-date', '2020-01-01']):
                with self.subTest(extra=extra), patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                    p.main(['--output', 'unused.json', *extra])
            client.assert_not_called()

    def test_production_parsers_return_counts_only(self):
        nh = json.loads((FIXTURES/'rediscovered_nh_api.json').read_text())
        nh.update(total=len(nh['data']), last_page=1)
        content = {'new_hampshire': json.dumps(nh).encode(),
                   'new_jersey': (FIXTURES/'rediscovered_nj_current.html').read_bytes(),
                   'sec': (FIXTURES/'rediscovered_sec_search.json').read_bytes()}
        for source, body in content.items():
            with self.subTest(source=source):
                result = p.shape_metadata(source, body, TODAY)
                self.assertTrue(result['expectedShape'])
                self.assertGreater(result['rowCount'], 0)
                self.assertTrue(all(type(value) in (int, bool) for value in result.values()))
                with self.assertRaises((SourceError, ValueError)):
                    p.shape_metadata(source, b'<html>Access denied</html>', TODAY)

    def test_one_plain_request_per_source_and_bounded_transport(self):
        for source in p.LOCAL_SOURCES:
            with self.subTest(source=source):
                client = Mock(requests=1, bytes=100)
                client._browser.version = '140.0.1.2'
                client.request.return_value = Response(p.endpoints(TODAY)[source], b'{}', 'application/json')
                with patch.object(p, 'LocalBrowserClient', return_value=client) as factory, \
                        patch.object(p, 'shape_metadata', return_value={'expectedShape': True, 'rowCount': 2}):
                    result = p.probe_source(source, TODAY)
                factory.assert_called_once_with(source, max_requests=1, max_bytes=6_000_000,
                                                deadline_seconds=50, max_response_bytes=6_000_000)
                client.request.assert_called_once_with(p.endpoints(TODAY)[source])
                client.close.assert_called_once()
                self.assertTrue(result['success'])
                self.assertEqual(result['httpStatus'], 200)
                self.assertEqual(result['chromeVersion'], '140.0.1.2')

    def test_denial_status_and_error_classification_do_not_emit_raw_errors(self):
        cases = [('HTTP 403; local browser stopped without retry', 403, 'access_denied'),
                 ('Local browser received an access challenge', None, 'access_challenge'),
                 ('Local browser blocked a redirect', None, 'redirect_blocked'),
                 ('Source exceeded its 60-second hard deadline; worker stopped', None, 'timeout'),
                 ('secret payload 192.0.2.1 cookie=secret', None, 'network_or_schema_error')]
        for message, status, code in cases:
            with self.subTest(code=code):
                value = p.classify_error(SourceError(message))
                self.assertEqual(value['httpStatus'], status)
                self.assertEqual(value['errorCode'], code)
                self.assertNotIn(message, json.dumps(value))

    def test_schema_failure_keeps_http_200_but_does_not_claim_success(self):
        client = Mock(requests=1, bytes=12)
        client._browser = None
        client.request.return_value = Response(p.HOMEPAGE, b'<html></html>', 'text/html')
        with patch.object(p, 'LocalBrowserClient', return_value=client):
            result = p.probe_source('new_jersey', TODAY)
        self.assertEqual(result['httpStatus'], 200)
        self.assertFalse(result['expectedShape'])
        self.assertFalse(result['success'])
        self.assertEqual(result['errorCode'], 'network_or_schema_error')
        client.close.assert_called_once()

    def test_supervised_children_share_utc_date_and_failures_preserve_other_results(self):
        def worker(command, *, timeout):
            self.assertLessEqual(timeout, 60)
            self.assertEqual(command[command.index('--utc-date')+1], TODAY.isoformat())
            source = command[command.index('--source')+1]
            if source == 'new_jersey':
                raise SourceError('Source exceeded its 60-second hard deadline; worker stopped')
            path = Path(command[command.index('--output')+1])
            result = p.base_result(source, TODAY)
            result.update(success=True, expectedShape=True, httpStatus=200, requests=1)
            path.write_text(json.dumps(result))
            return 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'diagnostic.json'
            with patch.object(p, 'supervise', side_effect=worker) as supervise, patch.object(p, 'datetime') as clock:
                clock.now.return_value = datetime(2026, 9, 5, 0, 30, tzinfo=timezone.utc)
                self.assertEqual(p.run(output), 0)
            report = json.loads(output.read_text())
            clock.now.assert_called_once_with(timezone.utc)
            self.assertEqual(supervise.call_count, 3)
            self.assertEqual([r['success'] for r in report['results']], [True, False, True])
            self.assertEqual(report['results'][1]['errorCode'], 'timeout')
            self.assertIsNone(report['results'][1]['requests'])
            self.assertIsNone(report['results'][1]['bytes'])
            self.assertFalse(report['results'][1]['workerCompleted'])
            self.assertNotIn('collection', report)


if __name__ == '__main__':
    unittest.main()
