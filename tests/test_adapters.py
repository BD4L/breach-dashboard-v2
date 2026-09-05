"""Offline parser and transport contracts; fixtures disclose their provenance."""
from datetime import date
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests

from ingestion.adapters import (collect, discover_ma_reports, hhs_navigation, hhs_page_html,
    hhs_page_request, hhs_partial_response, parse_ca_listing, parse_count, parse_date,
    parse_hhs_table, parse_ma_pdf, parse_ma_tables)
from ingestion.models import SourceError
from ingestion.network import PublicClient, Response

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


def fixture(name):
    return (FIXTURES / name).read_text()


class AdapterTests(unittest.TestCase):
    def test_ca_live_fixture_native_ids_dates_and_missing_counts(self):
        result, next_url = parse_ca_listing(fixture('ca-list.html'), today=TODAY)
        self.assertEqual(result.parsed, 3)
        first = result.reports[0]
        self.assertEqual(first.native_id, 'sb24-629314')
        self.assertEqual(first.organization, 'Catalyst Brands LLC')
        self.assertEqual(first.reported_date, '2026-09-04')
        self.assertEqual(first.breach_start, '2026-05-20')
        self.assertIsNone(first.published_date)
        self.assertIsNone(first.affected_count)
        self.assertEqual(first.affected_scope, 'unknown')
        self.assertEqual(next_url, 'https://oag.ca.gov/privacy/databreach/list?page=1')
        third = result.reports[2]
        self.assertIsNone(third.breach_start)
        self.assertIn('04/11/2026', third.quality_flags[0]['message'])
        self.assertIn('04/13/2026', third.quality_flags[0]['message'])

    def test_ca_uses_headers_with_other_tables_and_rejects_missing_ids(self):
        html = fixture('ca-list.html').replace('sb24-629314', 'missing-id')
        result, _ = parse_ca_listing('<table><tr><td>Layout only</td></tr></table>' + html, today=TODAY)
        self.assertEqual((result.parsed, result.rejected, len(result.reports)), (3, 1, 2))

    def test_ca_empty_or_challenge_is_failure(self):
        for html in ['<html>Access denied</html>', '<table><tr><th>Organization Name</th><th>Date(s) of Breach</th><th>Reported Date</th></tr></table>']:
            with self.assertRaises(SourceError):
                parse_ca_listing(html)

    def test_ca_window_is_partial_and_does_not_invent_rejections(self):
        class FakeClient:
            requests, bytes = 0, 0
            def __init__(self, **kwargs): pass
            def request(self, url, **kwargs):
                self.requests += 1
                text = fixture('ca-list.html').replace('sb24-629', f'sb24-{self.requests}629')
                text = text.replace('page=1\"', f'page={self.requests}\"')
                text = text.replace('<li class="active"><span>1</span></li>', f'<li class="active"><span>{self.requests}</span></li>')
                return Response(url, text.encode(), 'text/html')
            def close(self): pass
        with patch('ingestion.adapters.PublicClient', FakeClient):
            result = collect('california', max_pages=2)
        self.assertFalse(result.complete)
        self.assertEqual(len(result.reports), 6)
        self.assertEqual(result.rejected, 0)
        self.assertIn('older pages excluded', result.message)

    def test_ca_pagination_loops_fail(self):
        client = Mock()
        client.request.return_value = Response('https://oag.ca.gov/privacy/databreach/list', fixture('ca-list.html').encode(), 'text/html')
        with patch('ingestion.adapters.PublicClient', return_value=client):
            with self.assertRaisesRegex(SourceError, 'page'):
                collect('california')

    def test_ca_actual_final_pager_declares_complete_and_missing_pager_does_not(self):
        result, next_url = parse_ca_listing(fixture('ca-last.html'), 'https://oag.ca.gov/privacy/databreach/list?page=105', today=TODAY)
        self.assertTrue(result.complete)
        self.assertIsNone(next_url)
        self.assertEqual(result.evidence['totalPages'], 106)
        html = fixture('ca-list.html').split('<ul class="pagination">')[0]
        result, next_url = parse_ca_listing(html, today=TODAY)
        self.assertFalse(result.complete)
        self.assertIsNone(next_url)

    def test_ca_actual_blank_organization_is_withheld_with_native_evidence(self):
        result, _ = parse_ca_listing(fixture('ca-missing-organization.html'),
                                     'https://oag.ca.gov/privacy/databreach/list?page=64', today=TODAY)
        self.assertEqual((result.parsed, result.rejected, len(result.reports)), (2, 1, 1))
        self.assertIn('sb24-194945', result.message)
        self.assertIn('organization name missing', result.message)

    def test_ca_missing_next_link_cannot_claim_complete_while_later_pages_exist(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(fixture('ca-list.html'), 'html.parser')
        soup.select_one('li.next').decompose()
        with self.assertRaisesRegex(SourceError, 'next-page control missing'):
            parse_ca_listing(str(soup), today=TODAY)

    def test_invalid_page_limits_fail_before_network(self):
        with patch('ingestion.adapters.PublicClient') as client:
            for value in (0, -1, True, 1.5, 201):
                with self.assertRaisesRegex(SourceError, 'max_pages'):
                    collect('california', max_pages=value)
            client.assert_not_called()

    def test_hhs_configurable_page_limit_reports_truncation_and_selected_scope(self):
        front = Response('https://ocrportal.hhs.gov/ocr/breach/breach_frontpage.jsf', fixture('hhs-navigation.html').encode(), 'text/html')
        initial = ('<form id="ocrForm"><input type="hidden" name="javax.faces.ViewState" value="fixture">'
                   '<ul class="ui-tabs-nav"><li aria-selected="true">Under Investigation</li></ul>'
                   + fixture('hhs-reports.html') + '</form>')
        client = Mock(requests=2, bytes=1000)
        client.request.side_effect = [front, Response('https://ocrportal.hhs.gov/ocr/breach/breach_report_hip.jsf', initial.encode(), 'text/html')]
        with patch('ingestion.adapters.PublicClient', return_value=client):
            result = collect('hhs', max_pages=1)
        self.assertFalse(result.complete)
        self.assertEqual(result.parsed, 3)
        self.assertIn('3 of 733', result.message)
        self.assertIn('Page cap reached', result.message)
        self.assertEqual(client.request.call_count, 2)
        client.request.side_effect = [front, Response('https://ocrportal.hhs.gov/ocr/breach/breach_report_hip.jsf', initial.replace('Under Investigation', 'Archive').encode(), 'text/html')]
        with patch('ingestion.adapters.PublicClient', return_value=client):
            with self.assertRaisesRegex(SourceError, 'Under Investigation view is not selected'):
                collect('hhs', max_pages=1)

    def test_ma_current_official_indexed_date_format(self):
        # Actual date spelling seen in the official 2026 PDF search-index excerpt;
        # downloaded PDF bytes remain unavailable due HTTP403.
        flags = []
        self.assertEqual(parse_date('15-Jul-26', flags, 'Date reported to OCA', today=TODAY), '2026-07-15')
        self.assertEqual(flags, [])

    def test_ma_discovers_current_and_previous_year_no_hardcoded_year(self):
        html = '''<a href="/doc/data-breach-report-2025/download">2025</a>
        <a href="/doc/data-breach-report-2026/download">2026</a>
        <a href="/doc/data-breach-report-2027/download">2027</a>'''
        self.assertEqual([x[0] for x in discover_ma_reports(html, today=date(2027, 1, 10))], [2027, 2026])
        self.assertEqual([x[0] for x in discover_ma_reports(html, today=date(2026, 12, 31))], [2026, 2025])
        with self.assertRaises(SourceError):
            discover_ma_reports(html, today=date(2030, 1, 1))

    def test_ma_synthetic_reordered_headers_continuation_and_rollover(self):
        tables = json.loads(fixture('ma-tables-synthetic.json'))['tables']
        result = parse_ma_tables(tables, 'https://www.mass.gov/doc/data-breach-report-2027/download', today=date(2027, 1, 10))
        self.assertEqual(len(result.reports), 4)
        self.assertEqual(result.reports[0].native_id, '2027-0001')
        self.assertEqual(result.reports[1].native_id, '2026-9000')
        self.assertEqual(result.reports[0].affected_count, 1204)
        self.assertEqual(result.reports[0].affected_scope, 'state')
        self.assertEqual(result.reports[0].affected_jurisdiction, 'MA')
        self.assertEqual(result.reports[0].data_types, ['Social Security numbers'])
        self.assertIsNone(result.reports[0].breach_start)
        self.assertIn('bad-date', result.reports[-1].quality_flags[0]['message'])
        self.assertEqual(len(set(r.native_id for r in result.reports)), 4)

    def test_ma_missing_header_and_non_pdf_fail(self):
        with self.assertRaises(SourceError):
            parse_ma_tables([[['2026-42', 'Acme', '30']]], 'https://www.mass.gov/example')
        with self.assertRaisesRegex(SourceError, 'not a PDF'):
            parse_ma_pdf(b'<html>Forbidden</html>', 'https://www.mass.gov/example')

    def test_ma_unheaded_report_rows_cannot_be_silently_omitted(self):
        tables = json.loads(fixture('ma-tables-synthetic.json'))['tables']
        tables.insert(0, [['2027-0099', 'Unheaded missing report', '01/01/2027']])
        with self.assertRaisesRegex(SourceError, 'before a validated report header'):
            parse_ma_tables(tables, 'https://www.mass.gov/example', today=date(2027, 1, 10))

    def test_ma_pdf_page_without_tables_fails_even_when_other_page_parses(self):
        tables = json.loads(fixture('ma-tables-synthetic.json'))['tables']
        page = Mock()
        page.extract_tables.return_value = [tables[0]]
        page.extract_text.return_value = '2027-0001'
        missing = Mock()
        missing.extract_tables.return_value = []
        pdf = Mock(pages=[page, missing])
        pdf.__enter__ = Mock(return_value=pdf)
        pdf.__exit__ = Mock(return_value=False)
        with patch('ingestion.adapters.pdfplumber.open', return_value=pdf):
            with self.assertRaisesRegex(SourceError, 'page 2 has no validated table'):
                parse_ma_pdf(b'%PDF-fixture', 'https://www.mass.gov/example', today=date(2027, 1, 10))

    def test_ma_pdf_missing_report_id_is_failure_and_text_agreement_stays_partial(self):
        tables = json.loads(fixture('ma-tables-synthetic.json'))['tables']
        page = Mock()
        page.extract_tables.return_value = [tables[0]]
        pdf = Mock(pages=[page])
        pdf.__enter__ = Mock(return_value=pdf)
        pdf.__exit__ = Mock(return_value=False)
        with patch('ingestion.adapters.pdfplumber.open', return_value=pdf):
            page.extract_text.return_value = '2027-0001 2027-0099'
            with self.assertRaisesRegex(SourceError, 'text/table report IDs disagree'):
                parse_ma_pdf(b'%PDF-fixture', 'https://www.mass.gov/example', today=date(2027, 1, 10))
            page.extract_text.return_value = '2027-0001'
            result = parse_ma_pdf(b'%PDF-fixture', 'https://www.mass.gov/example', today=date(2027, 1, 10))
            self.assertFalse(result.complete)
            self.assertIn('no independent annual source count', result.message)
            result = parse_ma_pdf(b'%PDF-fixture', 'https://www.mass.gov/example', today=date(2027, 1, 10), expected_count=1)
            self.assertTrue(result.complete)
            with self.assertRaisesRegex(SourceError, 'independent annual source count'):
                parse_ma_pdf(b'%PDF-fixture', 'https://www.mass.gov/example', today=date(2027, 1, 10), expected_count=2)

    def test_ma_collector_preserves_unverified_pdf_coverage(self):
        client = Mock(requests=2, bytes=1000)
        client.request.side_effect = [Response('https://www.mass.gov/list', b'<html/>', 'text/html'),
                                     Response('https://www.mass.gov/report', b'%PDF-fixture', 'application/pdf')]
        batch = parse_ma_tables(json.loads(fixture('ma-tables-synthetic.json'))['tables'],
                                'https://www.mass.gov/report', today=date(2027, 1, 10))
        batch.complete = False
        with patch('ingestion.adapters.PublicClient', return_value=client), \
             patch('ingestion.adapters.discover_ma_reports', return_value=[(date.today().year, 'https://www.mass.gov/report')]), \
             patch('ingestion.adapters.parse_ma_pdf', return_value=batch):
            result = collect('massachusetts')
        self.assertFalse(result.complete)
        self.assertIn('coverage remains unverified', result.message)
        self.assertNotIn('Current-year report not linked', result.message)

    def test_hhs_real_fixture_uses_native_id_and_named_columns(self):
        html = '<table><tr><td>Layout table</td></tr></table>' + fixture('hhs-reports.html')
        page = parse_hhs_table(html, today=TODAY)
        self.assertEqual((page.first, page.last, page.total), (1, 3, 733))
        report = page.collection.reports[0]
        self.assertEqual(report.native_id, '1480915')
        self.assertEqual(report.organization, 'AnMed Health')
        self.assertEqual(report.affected_count, 501)
        self.assertEqual(report.affected_scope, 'reported')
        self.assertIsNone(report.affected_jurisdiction)  # SC is the entity's address.
        self.assertEqual(report.reported_date, '2026-08-27')
        self.assertIsNone(report.published_date)
        self.assertIsNone(report.breach_start)
        self.assertEqual(report.data_types, [])  # Network Server is a location, not a data type.

    def test_hhs_navigation_discovers_action_and_preserves_state(self):
        url, data = hhs_navigation(fixture('hhs-navigation.html'), 'https://ocrportal.hhs.gov/ocr/breach/breach_frontpage.jsf')
        self.assertEqual(data['ocrForm:j_idt39'], 'ocrForm:j_idt39')
        self.assertEqual(data['javax.faces.ViewState'], 'fixture-only')
        self.assertTrue(url.endswith('/breach_frontpage.jsf'))
        request = hhs_page_request('ocrForm:reportResultTable', 100, 100, data)
        self.assertEqual(request['ocrForm:reportResultTable_first'], '100')
        self.assertEqual(request['javax.faces.behavior.event'], 'page')

    def test_hhs_captured_pagination_fragments_preserve_header_mapping(self):
        fragment, state = hhs_partial_response(fixture('hhs-page2.xml'), 'ocrForm:reportResultTable')
        html = hhs_page_html(fragment, fixture('hhs-reports.html'), 'ocrForm:reportResultTable', 100, 733)
        page = parse_hhs_table(html, today=TODAY)
        self.assertEqual((page.first, page.last, page.total), (101, 102, 733))
        self.assertEqual(page.collection.reports[0].native_id, '1463956')
        self.assertEqual(state, 'fixture-state')
        with self.assertRaisesRegex(SourceError, 'noncontiguous'):
            hhs_page_html(fragment, fixture('hhs-reports.html'), 'ocrForm:reportResultTable', 200, 733)

    def test_hhs_missing_native_ids_are_accounted_for(self):
        html = fixture('hhs-reports.html').replace('data-rk="1480915"', '')
        page = parse_hhs_table(html, today=TODAY)
        self.assertEqual(page.collection.parsed, 3)
        self.assertEqual(page.collection.rejected, 1)
        self.assertEqual(len(page.collection.reports), 2)

    def test_hhs_duplicate_native_ids_and_wrong_counts_fail(self):
        for html in [fixture('hhs-reports.html').replace('data-rk="1480871"', 'data-rk="1480915"'),
                     fixture('hhs-reports.html').replace('1 - 3 of 733', '1 - 4 of 733')]:
            with self.assertRaises(SourceError):
                parse_hhs_table(html)
        with self.assertRaises(SourceError):
            hhs_partial_response('<partial-response><redirect url="login"/></partial-response>', 'table')

    def test_future_dates_and_unclear_counts_stay_unknown_with_raw_flags(self):
        flags = []
        self.assertIsNone(parse_date('01/01/2029', flags, 'Reported date', today=TODAY))
        self.assertIn('01/01/2029', flags[0]['message'])
        self.assertEqual(parse_count('<500', []), (500, 'less_than'))
        self.assertEqual(parse_count('at least 1,200', []), (1200, 'at_least'))
        self.assertEqual(parse_count('0', []), (0, 'exact'))
        flags = []
        self.assertEqual(parse_count('about 500', flags), (None, 'unknown'))
        self.assertIn('about 500', flags[0]['message'])


class NetworkTests(unittest.TestCase):
    @staticmethod
    def response(status, *, content=b'hello', headers=None):
        response = Mock(status_code=status, headers=headers or {})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [content]
        return response

    def test_public_auth_blocks_netrc_but_preserves_jsf_cookies_and_ca_environment(self):
        session = requests.Session()
        session.cookies.set('JSESSIONID', 'fixture-session', domain='ocrportal.hhs.gov', path='/')
        client = PublicClient(session=session)
        with patch('requests.sessions.get_netrc_auth', return_value=('ambient-user', 'ambient-password')) as netrc:
            prepared = session.prepare_request(requests.Request('POST', 'https://ocrportal.hhs.gov/ocr/breach/front.jsf',
                                                                data={'javax.faces.ViewState': 'fixture-state'}))
        netrc.assert_not_called()
        self.assertNotIn('Authorization', prepared.headers)
        self.assertIn('JSESSIONID=fixture-session', prepared.headers['Cookie'])
        self.assertIn('javax.faces.ViewState=fixture-state', prepared.body)
        self.assertTrue(session.trust_env)
        with patch.dict(os.environ, {'REQUESTS_CA_BUNDLE': '/fixture/trusted-ca.pem'}):
            settings = session.merge_environment_settings(prepared.url, {}, None, None, None)
        self.assertEqual(settings['verify'], '/fixture/trusted-ca.pem')
        client.close()

    def test_403_429_stop_without_retry(self):
        for status in (403, 429):
            session = Mock()
            session.request.return_value = self.response(status)
            client = PublicClient(session=session)
            with self.assertRaisesRegex(SourceError, f'HTTP {status}'):
                client.request('https://www.mass.gov/lists/data-breach-notification-reports')
            self.assertEqual(session.request.call_count, 1)

    def test_transient_failure_retries_once_and_preserves_tls_verification(self):
        session = Mock()
        session.request.side_effect = [self.response(503), self.response(200)]
        client = PublicClient(session=session)
        with patch('ingestion.network.time.sleep'):
            result = client.request('https://oag.ca.gov/privacy/databreach/list')
        self.assertEqual(result.content, b'hello')
        self.assertEqual(session.request.call_count, 2)
        self.assertNotIn('verify', session.request.call_args.kwargs)

    def test_request_byte_and_redirect_budgets(self):
        session = Mock()
        session.request.return_value = self.response(200)
        with self.assertRaisesRegex(SourceError, 'request/time budget'):
            PublicClient(session=session, max_requests=0).request('https://oag.ca.gov/')
        with self.assertRaisesRegex(SourceError, 'byte/time budget'):
            PublicClient(session=session, max_bytes=2).request('https://oag.ca.gov/')
        session.request.return_value = self.response(302, headers={'Location': 'https://unrelated.example/'})
        with self.assertRaisesRegex(SourceError, 'outside'):
            PublicClient(session=session).request('https://oag.ca.gov/')


if __name__ == '__main__':
    unittest.main()
