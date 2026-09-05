"""Regression contracts for live public state schemas; no network in unit tests."""
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.other_portals import (SOURCES, collect, date_range, parse_date,
                                     parse_table, parse_wisconsin)

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


def fixture(source):
    return (FIXTURES / f'other_portals_{source}.html').read_text()


def wa_last_page():
    soup = BeautifulSoup(fixture('washington'), 'html.parser')
    pager = soup.select_one('nav.pager')
    pager.clear()
    pager.append(BeautifulSoup('<a href="?page=0">Previous</a><a href="?page=1" aria-current="page">2</a>', 'html.parser'))
    for index, link in enumerate(soup.select('table a'), 1):
        link['href'] = f'https://agportal-s3bucket.s3.amazonaws.com/databreach/BreachB{index}.pdf'
    return str(soup)


class OtherPortalTests(unittest.TestCase):
    def test_montana_native_ids_survive_reordering_and_updated_counts(self):
        result, _ = parse_table('montana', fixture('montana'), today=TODAY)
        self.assertEqual([r.native_id for r in result.reports], ['row-63234', 'row-63233'])
        soup = BeautifulSoup(fixture('montana'), 'html.parser')
        rows = soup.select('tbody tr')
        rows[0].find_all('td')[-1].string = '520'
        rows[0].extract()
        soup.tbody.append(rows[0])
        changed, _ = parse_table('montana', str(soup), today=TODAY)
        self.assertEqual({r.native_id for r in result.reports}, {r.native_id for r in changed.reports})
        self.assertEqual(next(r for r in changed.reports if r.native_id == 'row-63234').affected_count, 520)
        self.assertTrue(result.complete)

    def test_montana_missing_native_id_is_rejected_not_replaced_with_row_index(self):
        result, _ = parse_table('montana', fixture('montana').replace('data-row_id="63234"', ''), today=TODAY)
        self.assertEqual((len(result.reports), result.rejected, result.parsed), (1, 1, 2))
        self.assertFalse(result.complete)

    def test_montana_deferred_rows_cannot_claim_complete(self):
        result, _ = parse_table('montana', fixture('montana').replace('"defer_row_limit":false', '"defer_row_limit":100'), today=TODAY)
        self.assertFalse(result.complete)

    def test_sc_actual_typo_is_normalized_without_collection_time_fallback(self):
        result, _ = parse_table('south_carolina', fixture('south_carolina'), today=TODAY)
        typo = next(r for r in result.reports if any(f['code'] == 'normalized_date_separator' for f in r.quality_flags))
        self.assertEqual(typo.reported_date, '2024-12-19')
        self.assertEqual((len(result.reports), result.rejected, result.parsed), (2, 2, 4))
        self.assertFalse(result.complete)
        self.assertIn('ambiguous', result.message)

    def test_sc_conflicting_real_rows_do_not_choose_or_sum_counts(self):
        result, _ = parse_table('south_carolina', fixture('south_carolina'), today=TODAY)
        self.assertNotIn('Morgan Stanley', [r.organization for r in result.reports])
        self.assertEqual(result.rejected, 2)

    def test_de_annotations_are_parsed_but_multiple_report_dates_stay_unknown(self):
        result, _ = parse_table('delaware', fixture('delaware'), today=TODAY)
        lockton = next(r for r in result.reports if 'Lockton' in r.organization)
        kelly = next(r for r in result.reports if 'Kelly' in r.organization)
        substitute = next(r for r in result.reports if 'Substitute' in r.organization)
        self.assertEqual(lockton.reported_date, '2025-06-27')
        self.assertEqual(kelly.reported_date, '2025-06-30')
        self.assertIsNone(substitute.reported_date)
        self.assertIn('04/10/2025', str(substitute.quality_flags))
        self.assertEqual((lockton.breach_start, lockton.breach_end), ('2024-11-20', '2024-11-20'))

    def test_blank_formatting_rows_are_not_rejected_reports(self):
        html = fixture('delaware').replace('</tbody>', '<tr><td></td><td></td><td></td><td></td><td></td></tr></tbody>')
        result, _ = parse_table('delaware', html, today=TODAY)
        self.assertEqual(result.rejected, 0)
        self.assertTrue(result.complete)

    def test_wisconsin_current_schema_is_prose_and_has_separate_state_count(self):
        result = parse_wisconsin(fixture('wisconsin'), today=TODAY)
        self.assertEqual(len(result.reports), 2)
        self.assertEqual(result.reports[0].organization, 'Wisconsin Department of Health Services')
        self.assertEqual(result.reports[0].affected_count, 8157)
        self.assertIsNone(result.reports[0].published_date)
        self.assertIsNone(result.reports[0].reported_date)
        self.assertIn('2026-06-30', result.reports[0].summary)
        self.assertIn('notification_date_only', [flag['code'] for flag in result.reports[0].quality_flags])
        self.assertEqual([report.native_id for report in result.reports],
                         ['ce15856e6cc5bf3b9b3114b0475ceb4a', '10a31b68b32ca5779d6b0a0e7a22d017'])
        self.assertIsNone(result.reports[1].affected_count)
        self.assertFalse(result.complete)
        self.assertIn('archive', result.message)

    def test_washington_native_document_identity_does_not_depend_on_listing_page(self):
        result, next_url = parse_table('washington', fixture('washington'), today=TODAY)
        self.assertTrue(result.complete)
        self.assertEqual(next_url, SOURCES['washington']['homepage'] + '?page=1')
        self.assertEqual(result.reports[0].affected_count, 1929)
        self.assertIn('Full Date of Birth', result.reports[0].data_types)
        self.assertNotEqual(result.reports[0].native_id, result.reports[1].native_id)

    def test_washington_missing_pager_is_partial_and_missing_next_is_failure(self):
        soup = BeautifulSoup(fixture('washington'), 'html.parser')
        soup.select_one('nav.pager').decompose()
        result, next_url = parse_table('washington', str(soup), today=TODAY)
        self.assertFalse(result.complete)
        self.assertIsNone(next_url)
        soup = BeautifulSoup(fixture('washington'), 'html.parser')
        soup.select_one('a[rel="next"]').decompose()
        with self.assertRaisesRegex(SourceError, 'next-page'):
            parse_table('washington', str(soup), today=TODAY)

    def test_washington_does_not_accept_pagination_loop_or_foreign_host(self):
        for replacement in ('?page=0', 'https://example.org/?page=1'):
            html = fixture('washington').replace('href="?page=1" rel="next"', f'href="{replacement}" rel="next"')
            with self.assertRaises(SourceError):
                parse_table('washington', html, today=TODAY)

    def test_washington_collection_follows_pages_and_honors_budget(self):
        client = Mock(requests=2, bytes=1200)
        base = SOURCES['washington']['homepage']
        client.request.side_effect = [Response(base, fixture('washington').encode(), 'text/html'),
                                        Response(base+'?page=1', wa_last_page().encode(), 'text/html')]
        with patch('ingestion.other_portals.PublicClient', return_value=client):
            result = collect('washington')
        self.assertEqual(len(result.reports), 4)
        self.assertTrue(result.complete)
        self.assertEqual(result.evidence['pageCount'], 2)
        client.close.assert_called_once()
        client = Mock(requests=1, bytes=600)
        client.request.return_value = Response(base, fixture('washington').encode(), 'text/html')
        with patch('ingestion.other_portals.PublicClient', return_value=client):
            result = collect('washington', max_pages=1)
        self.assertFalse(result.complete)
        self.assertIn('older pages excluded', result.message)

    def test_washington_repeated_rows_across_pages_are_counted_as_partial(self):
        base = SOURCES['washington']['homepage']
        last = BeautifulSoup(wa_last_page(), 'html.parser')
        original = BeautifulSoup(fixture('washington'), 'html.parser')
        for link, original_link in zip(last.select('table a'), original.select('table a')):
            link['href'] = original_link['href']
        client = Mock(requests=2, bytes=1200)
        client.request.side_effect = [Response(base, fixture('washington').encode(), 'text/html'),
                                      Response(base+'?page=1', str(last).encode(), 'text/html')]
        with patch('ingestion.other_portals.PublicClient', return_value=client):
            result = collect('washington')
        self.assertEqual((len(result.reports), result.rejected, result.parsed), (2, 2, 4))
        self.assertFalse(result.complete)
        self.assertIn('repeated source rows', result.message)

    def test_challenges_and_empty_listings_never_succeed(self):
        client = Mock(requests=1, bytes=212)
        client.request.return_value = Response(SOURCES['new_jersey']['homepage'], fixture('new_jersey').encode(), 'text/html')
        with patch('ingestion.other_portals.PublicClient', return_value=client):
            with self.assertRaisesRegex(SourceError, 'access challenge'):
                collect('new_jersey')
        client.close.assert_called_once()
        for source in ('montana', 'washington', 'south_carolina', 'delaware'):
            with self.assertRaises(SourceError):
                parse_table(source, '<html>Access denied</html>')
        with self.assertRaises(SourceError):
            parse_wisconsin('<html></html>')

    def test_no_guessed_nh_pdf_fallback_or_retry_after_access_failure(self):
        client = Mock()
        client.request.side_effect = SourceError('HTTP 403 from www.doj.nh.gov')
        with patch('ingestion.other_portals.PublicClient', return_value=client):
            with self.assertRaisesRegex(SourceError, '403'):
                collect('new_hampshire')
        client.request.assert_called_once_with(SOURCES['new_hampshire']['homepage'])
        client.close.assert_called_once()

    def test_invalid_limits_fail_before_any_request(self):
        with patch('ingestion.other_portals.PublicClient') as client:
            for limit in (0, -1, 201, True, 2.5):
                with self.assertRaisesRegex(SourceError, 'max_pages'):
                    collect('washington', max_pages=limit)
            client.assert_not_called()

    def test_unknown_future_or_discovery_dates_do_not_become_breach_dates(self):
        for raw in ('nonsense', '09/06/2026', '01/01/2024 02/02/2024'):
            self.assertIsNone(parse_date(raw, [], today=TODAY))
        self.assertEqual(date_range('Additional discovered through on-going investigation – 01/04/2024', [], today=TODAY), (None, None))


if __name__ == '__main__':
    unittest.main()
