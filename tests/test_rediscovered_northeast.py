"""Real public navigation fixtures; no network/browser access in tests."""
from datetime import date
import copy
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import Mock, patch
import pdfplumber

from ingestion.models import Collection, SourceError
from ingestion.network import Response
from ingestion.rediscovered_northeast import (ARCHIVE_URL, MA_REPORT_INDEX, collect, collect_annual, collect_ma_letters,
                                             collect_nh_documents, discover_ma_months,
                                             ma_page_tables, nh_api_url, parse_ma_annual, parse_ma_letters, parse_nh_api)

FIXTURES = Path(__file__).parent / 'fixtures'
MONTH_URL = 'https://www.mass.gov/lists/data-breach-notification-letters-september-2026'
TODAY = date(2026, 9, 5)


def fixture(name):
    return (FIXTURES / f'rediscovered_ma_{name}.html').read_text()


def nh_fixture():
    return json.loads((FIXTURES / 'rediscovered_nh_api.json').read_text())


def nh_page(page, total=30):
    """Synthetic pagination envelope around the captured public row schema."""
    original = nh_fixture()['data'][0]
    rows = []
    for i in range((page - 1) * 25, min(page * 25, total)):
        row = copy.deepcopy(original)
        row['id'] = str(80000 + i)
        row['fields']['nid'] = [row['id']]
        rows.append(row)
    return {'item_count': len(rows), 'total': total, 'last_page': (total + 24) // 25, 'data': rows}


def nh_client(pages):
    client = Mock()
    client.request.side_effect = [Response(nh_api_url(page), json.dumps(data).encode(), 'application/json')
                                  for page, data in enumerate(pages, 1)]
    return client


class NortheastRediscoveryTests(unittest.TestCase):
    def test_actual_archive_discovers_21_months_latest_first(self):
        months = discover_ma_months(fixture('archive'), today=TODAY)
        self.assertEqual(len(months), 21)
        self.assertEqual(months[0], (2026, 9, MONTH_URL))
        self.assertEqual(months[-1][:2], (2025, 1))

    def test_archive_rollover_uses_only_linked_prior_year(self):
        months = discover_ma_months(fixture('archive'), today=date(2027, 1, 3))
        self.assertEqual(len(months), 9)
        self.assertTrue(all(year == 2026 for year, _, _ in months))
        self.assertFalse(any('2027' in url for _, _, url in months))

    def test_future_months_and_unexpected_navigation_are_not_followed(self):
        self.assertEqual(len(discover_ma_months(fixture('archive'), today=date(2026, 1, 1))), 13)
        with self.assertRaisesRegex(SourceError, 'unexpected official URL'):
            discover_ma_months(fixture('archive').replace('href="/lists/', 'href="https://example.com/lists/'), today=TODAY)
        with self.assertRaises(SourceError):
            discover_ma_months('<h1>Access Denied</h1>', today=TODAY)

    def test_actual_september_has_35_stable_ids_and_no_inferred_dates_counts(self):
        result = parse_ma_letters(fixture('september_2026'), MONTH_URL)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (35, 35, 0))
        first = result.reports[0]
        self.assertEqual(first.native_id, '2026-1471')
        self.assertEqual(first.organization, 'Jackson National Life Insurance Company')
        self.assertEqual(first.notice_url, 'https://www.mass.gov/doc/2026-1471-jackson-national-life-insurance-company/download')
        self.assertTrue(all(r.published_date is None and r.reported_date is None and r.affected_count is None for r in result.reports))
        self.assertFalse(result.complete)
        self.assertTrue(result.new_records_only)
        self.assertNotIn('2026-1474', [r.native_id for r in result.reports])  # Real source gap, not a fabricated record.

    def test_placeholder_and_non_report_pdf_do_not_become_records(self):
        extras = '<a class="ma__download-link__file-link" href="/doc/placeholder/download">2026-0000 - PLACEHOLDER</a><a class="ma__download-link__file-link" href="/doc/label/download">OCABR September 2026 Label</a>'
        result = parse_ma_letters(fixture('september_2026').replace('</body>', extras + '</body>'), MONTH_URL)
        self.assertEqual((result.parsed, result.rejected, result.evidence['skippedPlaceholders']), (35, 0, 1))

    def test_wrong_page_empty_schema_and_unsafe_document_fail(self):
        with self.assertRaisesRegex(SourceError, 'differs'):
            parse_ma_letters(fixture('september_2026'), MONTH_URL.replace('september', 'august'))
        with self.assertRaisesRegex(SourceError, 'no identified'):
            parse_ma_letters('<h1>Data Breach Notification Letters September 2026</h1>', MONTH_URL)
        with self.assertRaisesRegex(SourceError, 'unexpected official URL'):
            parse_ma_letters(fixture('september_2026').replace('https://www.mass.gov/doc/', 'https://example.com/doc/'), MONTH_URL)

    def test_duplicate_native_identity_is_not_arbitrarily_selected(self):
        html = fixture('september_2026').replace('2026-1472-', '2026-1471-')
        with self.assertRaisesRegex(SourceError, 'duplicate native'):
            parse_ma_letters(html, MONTH_URL)

    def test_actual_annual_bottom_border_recovers_previously_omitted_record(self):
        result = parse_ma_annual((FIXTURES / 'rediscovered_ma_pdf_geometry.pdf').read_bytes(),
                                'https://www.mass.gov/doc/data-breach-report-2026/download', today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (20, 20, 0))
        self.assertEqual(result.evidence['repairedBottomBorderPages'], [1])
        self.assertIn('2026-694', [report.native_id for report in result.reports])
        self.assertIn('2026-1009', [report.native_id for report in result.reports])
        self.assertIn('2026-1018', [report.native_id for report in result.reports])
        self.assertFalse(result.complete)
        self.assertTrue(all(report.affected_scope == 'state' and report.affected_jurisdiction == 'MA'
                            for report in result.reports))
        self.assertTrue(all(report.parser_version == 'northeast-annual-1' for report in result.reports))

    def test_annual_missing_row_is_not_repaired_without_source_border_markers(self):
        with pdfplumber.open(BytesIO((FIXTURES / 'rediscovered_ma_pdf_geometry.pdf').read_bytes())) as pdf:
            page = Mock(wraps=pdf.pages[0])
            page.width, page.height = pdf.pages[0].width, pdf.pages[0].height
            page.edges = [edge for edge in pdf.pages[0].edges if edge.get('orientation') != 'h']
            with self.assertRaisesRegex(SourceError, 'no source bottom-border markers'):
                ma_page_tables(page, 1)

    def test_annual_document_cap_and_later_failure_preserve_current_year(self):
        url = 'https://www.mass.gov/doc/data-breach-report-2026/download'
        index = '<a href="/doc/data-breach-report-2026/download">Data Breach Report 2026</a><a href="/doc/data-breach-report-2025/download">Data Breach Report 2025</a>'
        annual = parse_ma_annual((FIXTURES / 'rediscovered_ma_pdf_geometry.pdf').read_bytes(), url, today=TODAY)
        links = [(2026, url), (2025, url.replace('2026', '2025'))]
        for limit, failure in ((1, False), (2, True)):
            client = Mock(requests=2, bytes=1000)
            responses = [Response(MA_REPORT_INDEX, index.encode(), 'text/html'), Response(url, b'%PDF-mocked', 'application/pdf')]
            if failure:
                responses.append(SourceError('HTTP 403; stopped'))
            client.request.side_effect = responses
            with patch('ingestion.rediscovered_northeast.PublicClient', return_value=client), patch('ingestion.rediscovered_northeast.discover_ma_reports', return_value=links), patch('ingestion.rediscovered_northeast.parse_ma_annual', return_value=annual):
                result = collect_annual('massachusetts', max_pages=limit)
            self.assertEqual(len(result.reports), 20)
            self.assertEqual(result.evidence['years'], [2026])
            self.assertEqual(result.evidence['unvisitedYears'], [2025])
            self.assertFalse(result.complete)
            self.assertEqual(client.request.call_count, 3 if failure else 2)
            client.close.assert_called_once()
            if failure:
                self.assertIn('403', result.message)

    def test_bounded_month_collection_is_always_partial_and_new_records_only(self):
        client = Mock(requests=2, bytes=1000)
        client.request.side_effect = [Response(ARCHIVE_URL, fixture('archive').encode(), 'text/html'),
                                      Response(MONTH_URL, fixture('september_2026').encode(), 'text/html')]
        result = collect_ma_letters(client, max_pages=1, today=TODAY)
        self.assertEqual(len(result.reports), 35)
        self.assertEqual(result.evidence['linkedMonthCount'], 21)
        self.assertIn('1 of 21', result.message)
        self.assertTrue(result.new_records_only)
        self.assertFalse(result.complete)
        self.assertEqual(client.request.call_count, 2)

    def test_later_access_denial_keeps_collected_letters_and_stops(self):
        client = Mock()
        client.request.side_effect = [Response(ARCHIVE_URL, fixture('archive').encode(), 'text/html'),
                                      Response(MONTH_URL, fixture('september_2026').encode(), 'text/html'),
                                      SourceError('HTTP 403; stopped')]
        result = collect_ma_letters(client, max_pages=3, today=TODAY)
        self.assertEqual(len(result.reports), 35)
        self.assertIn('403', result.message)
        self.assertEqual(client.request.call_count, 3)
        self.assertFalse(result.complete)

    def test_annual_collection_is_preferred_without_opening_fallback(self):
        annual = Collection('massachusetts', [], 0, message='annual result')
        with patch('ingestion.rediscovered_northeast.collect_annual', return_value=annual), patch('ingestion.rediscovered_northeast.CLIENT_FACTORY') as factory:
            self.assertIs(collect('massachusetts'), annual)
            factory.assert_not_called()

    def test_invalid_limit_and_unknown_source_fail_before_requests(self):
        for limit in (0, -1, True, 201, 1.5):
            with patch('ingestion.rediscovered_northeast.collect_annual') as annual:
                with self.assertRaises(SourceError):
                    collect('massachusetts', max_pages=limit)
                annual.assert_not_called()
        with self.assertRaises(SourceError):
            collect('vermont')

    def test_actual_nh_public_api_maps_native_id_posted_date_and_document(self):
        result, total, last = parse_nh_api(nh_fixture(), page_size=15, today=TODAY)
        self.assertEqual((len(result.reports), total, last), (15, 9937, 663))
        self.assertEqual(result.reports[0].native_id, '71956')
        self.assertEqual(result.reports[0].published_date, '2026-08-20')
        self.assertEqual(result.reports[0].notice_url,
                         'https://mm.nh.gov/files/uploads/doj/remote-docs/monmouth-university-20260820.pdf')
        self.assertTrue(all(report.affected_count is None and report.reported_date is None for report in result.reports))
        self.assertNotIn('revision_log', vars(result.reports[0]))

    def test_nh_count_disagreement_and_wrong_category_fail(self):
        data = nh_fixture()
        data['item_count'] -= 1
        with self.assertRaisesRegex(SourceError, 'pagination counts disagree'):
            parse_nh_api(data, page_size=15)
        data = nh_fixture()
        data['data'][0]['fields']['field_document_category'] = [{'id': '99'}]
        with self.assertRaisesRegex(SourceError, 'outside the breach category'):
            parse_nh_api(data, page_size=15)

    def test_nh_invalid_dates_are_unknown_and_document_urls_are_checked(self):
        data = nh_fixture()
        data['data'][0]['fields']['field_date_posted'] = ['2099-01-01']
        result, _, _ = parse_nh_api(data, page_size=15, today=TODAY)
        self.assertIsNone(result.reports[0].published_date)
        self.assertTrue(result.reports[0].quality_flags)
        data['data'][0]['fields']['field_document_file']['uri'] = 'https://example.com/notice.pdf'
        with self.assertRaisesRegex(SourceError, 'unexpected official document link'):
            parse_nh_api(data, page_size=15)

    def test_nh_complete_pagination_reconciles_source_total(self):
        client = Mock()
        client.request.side_effect = [Response(nh_api_url(page), json.dumps(nh_page(page)).encode(), 'application/json') for page in (1, 2)]
        result = collect_nh_documents(client, max_pages=3, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed), (30, 30))
        self.assertTrue(result.complete)
        self.assertEqual(client.request.call_count, 2)
        query = parse_qs(urlsplit(client.request.call_args_list[1].args[0]).query)
        self.assertEqual((query['page'], query['size']), (['2'], ['25']))

    def test_nh_page_limit_retains_partial_coverage(self):
        client = Mock()
        client.request.return_value = Response(nh_api_url(1), json.dumps(nh_page(1)).encode(), 'application/json')
        result = collect_nh_documents(client, max_pages=1, today=TODAY)
        self.assertEqual(len(result.reports), 25)
        self.assertFalse(result.complete)
        self.assertIn('25 unique usable', result.message)
        self.assertIn('30 declared', result.message)

    def test_nh_later_access_failure_does_not_erase_first_page(self):
        client = Mock()
        client.request.side_effect = [Response(nh_api_url(1), json.dumps(nh_page(1)).encode(), 'application/json'),
                                      SourceError('HTTP 403')]
        result = collect_nh_documents(client, max_pages=2, today=TODAY)
        self.assertEqual(len(result.reports), 25)
        self.assertFalse(result.complete)
        self.assertIn('stopped', result.message)

    def test_nh_partial_overlap_continues_later_pages_without_false_completeness(self):
        pages = [nh_page(page, 75) for page in (1, 2, 3)]
        pages[1]['data'][0] = copy.deepcopy(pages[0]['data'][-1])
        client = nh_client(pages)
        result = collect_nh_documents(client, max_pages=3, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (74, 75, 1))
        self.assertEqual(client.request.call_count, 3)
        self.assertEqual(result.evidence['duplicateRows'], 1)
        self.assertEqual(result.evidence['uniqueAcceptedCount'], 74)
        self.assertIn('80074', [report.native_id for report in result.reports])
        self.assertFalse(result.complete)

    def test_nh_conflicting_overlap_withholds_every_version_even_if_old_value_reappears(self):
        pages = [nh_page(page, 75) for page in (1, 2, 3)]
        original = copy.deepcopy(pages[0]['data'][-1])
        changed = copy.deepcopy(original)
        changed['title'] = 'Conflicting source title'
        changed['fields']['title'] = [changed['title']]
        pages[1]['data'][0] = changed
        pages[2]['data'][0] = original
        result = collect_nh_documents(nh_client(pages), max_pages=3, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (72, 75, 3))
        self.assertNotIn(original['id'], [report.native_id for report in result.reports])
        self.assertEqual(result.evidence['conflictingIds'], 1)
        self.assertFalse(result.complete)

    def test_nh_fully_repeated_page_or_cycle_stops_before_more_requests(self):
        pages = [nh_page(page, 100) for page in (1, 2, 3, 4)]
        pages[1] = copy.deepcopy(pages[0])
        client = nh_client(pages)
        result = collect_nh_documents(client, max_pages=4, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (25, 50, 25))
        self.assertEqual(client.request.call_count, 2)
        self.assertFalse(result.complete)
        self.assertIn('cycled', result.message)
        pages = [nh_page(page, 100) for page in (1, 2, 3, 4)]
        pages[2]['data'] = copy.deepcopy(pages[0]['data'][:12] + pages[1]['data'][:13])
        client = nh_client(pages)
        result = collect_nh_documents(client, max_pages=4, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (50, 75, 25))
        self.assertEqual(client.request.call_count, 3)
        self.assertFalse(result.complete)

    def test_nh_total_change_stops_before_merging_unstable_page(self):
        client = nh_client([nh_page(1, 75), nh_page(2, 100)])
        result = collect_nh_documents(client, max_pages=3, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (25, 25, 0))
        self.assertEqual(client.request.call_count, 2)
        self.assertFalse(result.complete)
        self.assertIn('count changed', result.message)

    def test_nh_live_observed_overlap_and_unresolved_uri_pattern_retains_746_of_750_rows(self):
        # Synthetic pagination mirrors the real 30-page capture's four anomalies.
        pages = [nh_page(page, 9937) for page in range(1, 31)]
        pages[1]['data'][0] = copy.deepcopy(pages[0]['data'][-1])
        for index in (8, 13, 24):
            pages[index]['data'][0]['fields']['field_document_file']['uri'] = 'public://remote-docs/example.pdf'
        client = nh_client(pages)
        result = collect_nh_documents(client, max_pages=30, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (746, 750, 4))
        self.assertEqual(client.request.call_count, 30)
        self.assertEqual(result.evidence['unresolvedDocumentRows'], 3)
        self.assertEqual(result.evidence['duplicateRows'], 1)
        self.assertTrue(all(report.notice_url.startswith('https://') for report in result.reports))
        self.assertFalse(result.complete)

    def test_nh_empty_or_changed_response_is_not_success(self):
        for payload in ({'item_count': 0, 'total': 0, 'last_page': 0, 'data': []}, {'error': 'denied'}):
            with self.assertRaises(SourceError):
                parse_nh_api(payload)

    def test_nh_malformed_document_field_is_rejected_without_poisoning_other_rows(self):
        data = nh_fixture()
        data['data'][0]['fields']['field_document_file'] = ['unexpected shape']
        result, _, _ = parse_nh_api(data, page_size=15, today=TODAY)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (14, 15, 1))
        self.assertFalse(result.complete)


if __name__ == '__main__':
    unittest.main()
