from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.special_portals import (collect, parse_sec_feed, parse_texas_response,
                                       sec_document_has_item_105, sec_filing_index, texas_request)

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


def fixture(name):
    return (FIXTURES / name).read_text()


class SpecialPortalTests(unittest.TestCase):
    def test_texas_public_read_action_matches_page_and_preserves_no_secrets_in_reports(self):
        endpoint, body = texas_request(fixture('texas-navigation.html'), 'https://oag.my.site.com/datasecuritybreachreport/apex/DataSecurityReportsPage')
        self.assertEqual(endpoint, 'https://oag.my.site.com/datasecuritybreachreport/apexremote')
        action = json.loads(body)[0]
        self.assertEqual(action['data'], [False])
        self.assertEqual(action['method'], 'getDatareports')
        self.assertEqual(action['ctx']['csrf'], 'fixture-csrf')
        result = parse_texas_response(fixture('texas-response.json'), today=TODAY)
        self.assertEqual(result.parsed, 3)
        self.assertTrue(result.complete)
        report = result.reports[0]
        self.assertEqual(report.native_id, 'a49cs000000GR2fAAG')
        self.assertEqual(report.organization, 'CDS in Texas')
        self.assertEqual(report.published_date, '2025-04-01')
        self.assertEqual(report.affected_count, 566)
        self.assertEqual((report.affected_scope, report.affected_jurisdiction), ('state', 'TX'))
        self.assertIsNone(report.reported_date)
        self.assertIsNone(report.breach_start)
        self.assertNotIn('authorization', report.__dict__)
        self.assertNotIn('ctx', report.__dict__)

    def test_texas_protocol_exception_empty_and_duplicate_are_failures(self):
        for text in [json.dumps([{'type':'exception','statusCode':402,'message':'Unable to determine from which page the request originated'}]),
                     json.dumps([{'type':'rpc','statusCode':200,'method':'getDatareports','result':[]}])]:
            with self.assertRaises(SourceError):
                parse_texas_response(text)
        data = json.loads(fixture('texas-response.json'))
        data[0]['result'].append(data[0]['result'][0])
        with self.assertRaisesRegex(SourceError, 'duplicate native'):
            parse_texas_response(json.dumps(data))

    def test_texas_does_not_truncate_at_fifty_or_use_random_ids(self):
        data = json.loads(fixture('texas-response.json'))
        base = data[0]['result'][0]
        data[0]['result'] = [{**base, 'Id': f'a49{number:012d}AAG'} for number in range(75)]
        first = parse_texas_response(json.dumps(data), today=TODAY)
        second = parse_texas_response(json.dumps(data), today=TODAY)
        self.assertEqual(len(first.reports), 75)
        self.assertEqual([r.native_id for r in first.reports], [r.native_id for r in second.reports])

    def test_texas_future_timestamp_and_invalid_count_are_quarantined(self):
        data = json.loads(fixture('texas-response.json'))
        data[0]['result'][0]['Published_at_AG_website_Date__c'] = 4_102_444_800_000
        data[0]['result'][0]['Number_of_Texans_affected_by_the_breach__c'] = 'about 100'
        report = parse_texas_response(json.dumps(data), today=TODAY).reports[0]
        self.assertIsNone(report.published_date)
        self.assertIsNone(report.affected_count)
        self.assertEqual({f['code'] for f in report.quality_flags}, {'future_date', 'unparsed_count'})

    def test_texas_collector_sends_normal_page_referer_and_full_public_action(self):
        client = Mock(requests=2, bytes=1000)
        landing = 'https://oag.my.site.com/datasecuritybreachreport/apex/DataSecurityReportsPage'
        client.request.side_effect = [Response(landing, fixture('texas-navigation.html').encode(), 'text/html'),
                                      Response(landing, fixture('texas-response.json').encode(), 'application/json')]
        with patch('ingestion.special_portals.PublicClient', return_value=client):
            result = collect('texas', max_pages=1)
        self.assertEqual(result.parsed, 3)
        self.assertEqual(client.request.call_args.kwargs['headers']['Referer'], landing)
        self.assertEqual(json.loads(client.request.call_args.kwargs['data'])[0]['data'], [False])

    def test_sec_native_accession_actual_primary_link_and_no_xbrl_dependency(self):
        filings = parse_sec_feed(fixture('sec-feed-synthetic.xml'), today=TODAY)
        self.assertEqual(filings[0]['native_id'], '0000123456-26-000001')
        self.assertEqual(filings[0]['published_date'], '2026-09-04')
        decision, primary = sec_filing_index(fixture('sec-index-synthetic.html'), filings[0]['source_url'])
        self.assertTrue(decision)
        self.assertEqual(primary, 'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/report.htm')
        self.assertTrue(sec_document_has_item_105('<html>FORM 8-K Item 1.05 Material Cybersecurity Incidents A reported incident.</html>'))
        self.assertFalse(sec_document_has_item_105('<html>FORM 8-K Item 8.01 Other Events We discuss general cybersecurity risks.</html>'))

    def test_sec_missing_identity_or_unrecognized_index_fails(self):
        with self.assertRaises(SourceError):
            parse_sec_feed('<html>Request denied</html>')
        with self.assertRaises(SourceError):
            parse_sec_feed(fixture('sec-feed-synthetic.xml').replace('0000123456-26-000001','missing'))
        with self.assertRaises(SourceError):
            sec_filing_index('<html>Access denied</html>', 'https://www.sec.gov/example')

    def test_sec_positive_valid_empty_scope_is_explicit_and_incomplete(self):
        client = Mock(requests=2, bytes=1000)
        client.request.side_effect = [Response('https://www.sec.gov/feed', fixture('sec-feed-synthetic.xml').encode(), 'application/atom+xml'),
                                      Response('https://www.sec.gov/index', fixture('sec-index-synthetic.html').replace('1.05','8.01').encode(), 'text/html')]
        with patch('ingestion.special_portals.PublicClient', return_value=client):
            result = collect('sec', max_pages=1)
        self.assertEqual(result.reports, [])
        self.assertTrue(result.empty_is_valid)
        self.assertFalse(result.complete)
        self.assertEqual((result.parsed, result.rejected), (0, 0))

    def test_sec_matching_disclosure_records_accession_without_enrichment_requests(self):
        client = Mock(requests=2, bytes=1000)
        client.request.side_effect = [Response('https://www.sec.gov/feed', fixture('sec-feed-synthetic.xml').encode(), 'application/atom+xml'),
                                      Response('https://www.sec.gov/index', fixture('sec-index-synthetic.html').encode(), 'text/html')]
        with patch('ingestion.special_portals.PublicClient', return_value=client):
            result = collect('sec', max_pages=1)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(result.reports[0].native_id, '0000123456-26-000001')
        self.assertIsNone(result.reports[0].affected_count)
        self.assertEqual(client.request.call_count, 2)
        self.assertIn('BreachWatch/1.0', client.request.call_args.kwargs['headers']['User-Agent'])


if __name__ == '__main__':
    unittest.main()
