from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from ingestion.models import SourceError
from ingestion.network import Response
from ingestion import state_portals as p

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


def fixture(name):
    return (FIXTURES / ('state_portals_' + name)).read_text()


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls, self.closed = routes, [], False
    def request(self, url, **kwargs):
        self.calls.append(url)
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return Response(url, value if isinstance(value, bytes) else value.encode(), 'text/html')
    def close(self):
        self.closed = True


class StatePortalTests(unittest.TestCase):
    def test_indiana_discovers_current_year_from_source_link(self):
        links = p.discover_year_links(fixture('indiana_index.html'), p.SOURCES['indiana']['homepage'], pdf=True, today=TODAY)
        self.assertEqual([year for year, _ in links], [2026, 2025])
        self.assertIn('7_2026.pdf', links[0][1])

    def test_year_rollover_and_external_archive_rejected(self):
        html = '<a href="/2027-report.pdf">2027</a><a href="/2026-report.pdf">2026</a>'
        links = p.discover_year_links(html, 'https://www.in.gov/', pdf=True, today=date(2027, 1, 1))
        self.assertEqual([x[0] for x in links], [2027, 2026])
        with self.assertRaises(SourceError):
            p.discover_year_links('<a href="https://example.com/2026.pdf">2026</a>', 'https://www.in.gov/', pdf=True, today=TODAY)

    def test_indiana_scope_notification_semantics_and_stable_identity(self):
        tables = json.loads(fixture('indiana_tables.json'))
        reports, parsed, bad, numbers = p.parse_indiana_tables(tables, 'https://www.in.gov/2026.pdf', 2026, today=TODAY)
        self.assertEqual((parsed, bad, numbers), (3, 0, [1, 2, 3]))
        first = reports[0]
        self.assertEqual((first.affected_count, first.affected_scope, first.affected_jurisdiction), (34, 'state', 'IN'))
        self.assertEqual(first.breach_start, '2026-03-19')
        self.assertIsNone(first.reported_date)
        self.assertIsNone(first.published_date)
        self.assertIn('Consumer notification sent: 2026-06-11', first.summary)
        tables[0][1][0] = '99'
        tables[0][1][4] = '40'
        changed = p.parse_indiana_tables(tables, 'https://www.in.gov/updated.pdf', 2026, today=TODAY)[0][0]
        self.assertEqual(changed.native_id, first.native_id)
        self.assertEqual(changed.affected_count, 40)

    def test_indiana_rejects_missing_columns_and_duplicate_row_numbers(self):
        tables = json.loads(fixture('indiana_tables.json'))
        tables[0][0][4] = 'Unknown count'
        with self.assertRaises(SourceError):
            p.parse_indiana_tables(tables, 'https://www.in.gov/2026.pdf', 2026, today=TODAY)
        tables = json.loads(fixture('indiana_tables.json'))
        tables[0][2][0] = '1'
        with self.assertRaises(SourceError):
            p.parse_indiana_tables(tables, 'https://www.in.gov/2026.pdf', 2026, today=TODAY)

    def test_pdf_text_table_mismatch_fails(self):
        tables = json.loads(fixture('indiana_tables.json'))
        class Page:
            def extract_tables(self): return tables
            def extract_text(self): return '1 Organization\n2 Organization\n3 Organization\n4 Omitted organization\n1 of 1'
        class PDF:
            pages = [Page()]
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(p.pdfplumber, 'open', return_value=PDF()), self.assertRaisesRegex(SourceError, 'disagree'):
            p.parse_indiana_pdf(b'%PDF-fixture', 'https://www.in.gov/2026.pdf', 2026, today=TODAY)

    def test_indiana_html_disguised_as_pdf_fails(self):
        with self.assertRaises(SourceError):
            p.parse_indiana_pdf(b'<html>Access denied</html>', 'https://www.in.gov/2026.pdf', 2026)

    def test_maryland_discovers_declared_latest_year_without_guessing_current(self):
        self.assertEqual(p.discover_maryland_lists(fixture('maryland_index.html'), today=TODAY), [2025, 2024])

    def test_maryland_named_fields_scope_id_and_pagination(self):
        data = json.loads(fixture('maryland.json'))
        reports, count, bad, next_url = p.parse_maryland_page(data, 2025, today=TODAY)
        self.assertEqual((count, bad), (2, 0))
        self.assertEqual(reports[0].native_id, '2025:item-33')
        self.assertEqual(reports[0].reported_date, '2025-03-07')
        self.assertEqual((reports[0].affected_count, reports[0].affected_jurisdiction), (4, 'MD'))
        self.assertTrue(reports[0].notice_url.endswith('/2025/ITU-376516.pdf'))
        self.assertIn('skiptoken', next_url)

    def test_maryland_unsafe_next_or_document_fails(self):
        data = json.loads(fixture('maryland.json'))
        for next_url in ['https://example.com/list', "https://oag.maryland.gov/_api/other", p.maryland_endpoint(2025).replace('$top=200', '$top=5000')]:
            changed = deepcopy(data); changed['d']['__next'] = next_url
            with self.assertRaises(SourceError): p.parse_maryland_page(changed, 2025, today=TODAY)
        data['d']['results'][0]['Case_x0020_No_x002e_'] = '../outside.pdf'
        with self.assertRaises(SourceError): p.parse_maryland_page(data, 2025, today=TODAY)

    def test_maryland_bad_date_and_count_are_visible_uncertainty(self):
        data = json.loads(fixture('maryland.json'))
        data['d']['results'][0]['Date_x0020_Received'] = '2/30/25'
        data['d']['results'][0]['No_x0020_of_x0020_Maryland_x0020'] = 'awaiting reply'
        first = p.parse_maryland_page(data, 2025, today=TODAY)[0][0]
        self.assertIsNone(first.reported_date); self.assertIsNone(first.affected_count)
        self.assertEqual({f['code'] for f in first.quality_flags}, {'unparsed_date', 'unparsed_count'})

    def test_maryland_live_bound_is_partial_and_closes_client(self):
        home = p.SOURCES['maryland']['homepage']; endpoint = p.maryland_endpoint(2025)
        client = FakeClient({home: fixture('maryland_index.html'), endpoint: fixture('maryland.json')})
        with patch.object(p, 'PublicClient', return_value=client): result = p.collect('maryland', max_pages=1)
        self.assertEqual(len(result.reports), 2); self.assertFalse(result.complete)
        self.assertIn('More API pages remain', result.message)
        self.assertEqual(client.calls, [home, endpoint]); self.assertTrue(client.closed)

    def test_maryland_subsequent_failure_keeps_valid_page_partial(self):
        data = json.loads(fixture('maryland.json'))
        home = p.SOURCES['maryland']['homepage']; endpoint = p.maryland_endpoint(2025)
        client = FakeClient({home: fixture('maryland_index.html'), endpoint: json.dumps(data), data['d']['__next']: SourceError('HTTP 503')})
        with patch.object(p, 'PublicClient', return_value=client): result = p.collect('maryland', max_pages=2)
        self.assertEqual(len(result.reports), 2); self.assertFalse(result.complete); self.assertIn('503', result.message)

    def test_maryland_missing_fields_fail_schema(self):
        data = json.loads(fixture('maryland.json')); del data['d']['results'][0]['Title']
        with self.assertRaises(SourceError): p.parse_maryland_page(data, 2025, today=TODAY)

    def test_oklahoma_feed_dates_are_not_last_modified(self):
        reports = p.parse_oklahoma_feed(json.loads(fixture('oklahoma.json')), p.SOURCES['oklahoma']['homepage'], today=TODAY)
        self.assertEqual(len(reports), 3)
        self.assertEqual(reports[0].breach_start, '2025-12-19')
        self.assertIsNone(reports[0].published_date)
        self.assertIsNone(reports[2].breach_start)
        self.assertIn('state-government', reports[0].summary)

    def test_oklahoma_explicit_created_date_and_agency_table(self):
        report = p.parse_oklahoma_feed(json.loads(fixture('oklahoma.json')), p.SOURCES['oklahoma']['homepage'], today=TODAY)[0]
        p.enrich_oklahoma_detail(report, fixture('oklahoma_detail.html'), today=TODAY)
        self.assertEqual(report.published_date, '2026-04-07')
        self.assertIn('tax information', report.data_types[0])

    def test_oklahoma_unsafe_feed_link_fails(self):
        data = json.loads(fixture('oklahoma.json')); data[0]['newsUrl'] = 'https://example.com/incident'
        with self.assertRaises(SourceError): p.parse_oklahoma_feed(data, p.SOURCES['oklahoma']['homepage'])

    def test_oklahoma_max_detail_budget_marks_partial(self):
        home = p.SOURCES['oklahoma']['homepage']; html = fixture('oklahoma_index.html')
        feed = p.discover_oklahoma_feed(html, home)
        reports = p.parse_oklahoma_feed(json.loads(fixture('oklahoma.json')), home, today=TODAY)
        client = FakeClient({home: html, feed: fixture('oklahoma.json'), reports[0].source_url: fixture('oklahoma_detail.html')})
        with patch.object(p, 'PublicClient', return_value=client): result = p.collect('oklahoma', max_pages=1)
        self.assertEqual(len(result.reports), 3); self.assertFalse(result.complete)
        self.assertEqual(len(client.calls), 3)

    def test_maine_official_offline_notice_is_failure(self):
        home = p.SOURCES['maine']['homepage']; client = FakeClient({home: fixture('maine_offline.html')})
        with patch.object(p, 'PublicClient', return_value=client), self.assertRaisesRegex(SourceError, 'offline'):
            p.collect('maine')
        self.assertTrue(client.closed); self.assertEqual(len(client.calls), 1)

    def test_iowa_403_remains_failure_without_fallback_or_retry(self):
        home = p.SOURCES['iowa']['homepage']; client = FakeClient({home: SourceError('HTTP 403')})
        with patch.object(p, 'PublicClient', return_value=client), self.assertRaisesRegex(SourceError, '403'):
            p.collect('iowa')
        self.assertEqual(client.calls, [home]); self.assertTrue(client.closed)

    def test_iowa_synthetic_named_table_and_empty_schema_guard(self):
        result = p.parse_notice_table(fixture('iowa_synthetic.html'), 'iowa', p.SOURCES['iowa']['homepage'], today=TODAY)
        self.assertEqual(result.reports[0].reported_date, '2026-08-14'); self.assertFalse(result.complete)
        with self.assertRaises(SourceError): p.parse_notice_table('<table><tr><td>menu</td></tr></table>', 'iowa', p.SOURCES['iowa']['homepage'])

    def test_north_dakota_dead_endpoint_and_synthetic_directory(self):
        home = p.SOURCES['north_dakota']['homepage']; client = FakeClient({home: SourceError('HTTP 404')})
        with patch.object(p, 'PublicClient', return_value=client), self.assertRaisesRegex(SourceError, 'replacement'):
            p.collect('north_dakota')
        result = p.parse_north_dakota_notices(fixture('nd_synthetic.html'), home, today=TODAY)
        self.assertEqual(result.reports[0].native_id, '2026-09-01-ExampleOrganization')
        self.assertIsNone(result.reports[0].reported_date)
        with self.assertRaises(SourceError): p.parse_north_dakota_notices('<h1>Identity theft guidance</h1>', home)

    def test_identical_duplicates_count_as_rejected_and_force_partial(self):
        report = p.parse_oklahoma_feed(json.loads(fixture('oklahoma.json')), p.SOURCES['oklahoma']['homepage'], today=TODAY)[0]
        result = p.checked('oklahoma', [report, deepcopy(report)], 2, message='fixture', complete=True)
        self.assertEqual((len(result.reports), result.parsed, result.rejected), (1, 2, 1))
        self.assertFalse(result.complete)

    def test_invalid_page_budget_is_rejected_before_network(self):
        for value in [0, -1, 201, True, '3']:
            with self.assertRaises(SourceError): p.collect('maryland', max_pages=value)


if __name__ == '__main__':
    unittest.main()
