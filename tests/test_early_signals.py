from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingestion.early_signals import (
    MAX_POSTS, MAX_RESPONSE_BYTES, collect, collect_with_client, parse_posts, posts_url,
)
from ingestion.models import SourceError
from ingestion.network import PublicClient, Response

FIXTURE = Path(__file__).parent / 'fixtures' / 'ransomlook-posts.json'
START = date(2026, 9, 5)
END = date(2026, 9, 7)
NOW = datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc)


class Client:
    def __init__(self, value, *, content_type='application/json', response_url=None):
        self.value = value
        self.content_type = content_type
        self.response_url = response_url
        self.requests = self.bytes = 0
        self.calls = []
        self.closed = False

    def request(self, url, *, headers=None):
        self.calls.append((url, headers))
        self.requests += 1
        if isinstance(self.value, Exception):
            raise self.value
        body = self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()
        self.bytes += len(body)
        return Response(self.response_url or url, body, self.content_type)

    def close(self):
        self.closed = True


class EarlySignalTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(FIXTURE.read_text())

    def parse(self, value=None):
        return parse_posts(self.value if value is None else value, start=START, end=END, now=NOW)

    def test_actual_metadata_is_an_unverified_claim_with_provider_time(self):
        result = self.parse()
        self.assertTrue(result.complete)
        self.assertEqual((result.parsed, result.rejected), (3, 0))
        report = result.reports[1]
        self.assertEqual(report.source_id, 'ransomlook')
        self.assertEqual(report.organization, 'Hochschule Heilbronn Bildungscampus')
        self.assertEqual(report.signal_type, 'ransomware_claim')
        self.assertEqual(report.source_observed_at, '2026-09-05T06:36:02Z')
        self.assertEqual(report.reported_date, '2026-09-05')
        self.assertIsNone(report.published_date)
        self.assertIsNone(report.discovery_date)
        self.assertIsNone(report.breach_start)
        self.assertIsNone(report.affected_count)
        self.assertIsNone(report.notice_url)
        self.assertEqual(report.source_url, 'https://www.ransomlook.io/group/panzer')
        self.assertIn('Unverified', report.summary)
        self.assertIn('derived_claim_identity', {flag['code'] for flag in report.quality_flags})
        self.assertFalse(result.evidence['independentTotalAvailable'])
        self.assertIn('no independent total', result.message)

    def test_collection_makes_one_metadata_request_and_does_not_follow_title_urls(self):
        self.value['posts'][0]['post_title'] = 'https://victim.example/path'
        client = Client(self.value)
        result = collect_with_client(client, now=NOW)
        self.assertEqual(client.calls, [(posts_url(START, END), {'Accept': 'application/json'})])
        self.assertEqual(result.evidence['requests'], 1)
        self.assertTrue(result.evidence['metadataOnly'])

    def test_group_spaces_are_encoded_on_the_clearnet_provider_link(self):
        self.value['posts'][0]['group_name'] = 'space bears'
        self.assertEqual(self.parse().reports[0].source_url,
                         'https://www.ransomlook.io/group/space%20bears')

    def test_identity_is_order_independent_and_distinguishes_recurring_claims(self):
        original = {r.organization: r.native_id for r in self.parse().reports}
        self.value['posts'].reverse()
        self.assertEqual(original, {r.organization: r.native_id for r in self.parse().reports})
        repeat = deepcopy(self.value['posts'][0])
        repeat['discovered'] = '2026-09-06T12:36:16.809898Z'
        self.value['posts'].append(repeat)
        result = self.parse()
        self.assertEqual(len({r.native_id for r in result.reports}), 4)

    def test_canonical_utc_spelling_matches_but_microseconds_remain_in_identity(self):
        original = self.parse().reports[0].native_id
        self.value['posts'][0]['discovered'] = '2026-09-05T01:47:00.000000+00:00'
        self.assertEqual(self.parse().reports[0].native_id, original)
        self.value['posts'][0]['discovered'] = '2026-09-05T01:47:00.000001Z'
        self.assertNotEqual(self.parse().reports[0].native_id, original)

    def test_duplicates_make_partial_and_count_every_withheld_row(self):
        self.value['posts'].append(deepcopy(self.value['posts'][0]))
        result = self.parse()
        self.assertFalse(result.complete)
        self.assertEqual((result.parsed, len(result.reports), result.rejected), (4, 3, 1))
        self.assertEqual(result.evidence['duplicateRows'], 1)

    def test_case_collisions_with_conflicting_content_withhold_all_versions(self):
        conflict = deepcopy(self.value['posts'][0])
        conflict['post_title'] = conflict['post_title'].upper()
        self.value['posts'].extend([conflict, deepcopy(conflict)])
        result = self.parse()
        self.assertEqual((result.parsed, len(result.reports), result.rejected), (5, 2, 3))
        self.assertEqual(result.evidence['conflictingIdentities'], 1)

    def test_invalid_titles_groups_and_unexpected_rich_fields_are_withheld(self):
        for field, value in [
            ('post_title', None), ('post_title', 123), ('post_title', 'x' * 301),
            ('post_title', '<script>bad</script>'), ('post_title', 'hidden\u200btext'),
            ('group_name', '../other'), ('group_name', 'http://x.onion'),
            ('group_name', 'percent%2fpath'), ('source', '<html>do not retain</html>'),
            ('screen', 'screenshot-data'),
        ]:
            with self.subTest(field=field, value=value):
                data = deepcopy(self.value)
                data['posts'][0][field] = value
                result = self.parse(data)
                self.assertEqual((len(result.reports), result.rejected), (2, 1))
                self.assertFalse(result.complete)

    def test_bad_out_of_window_naive_or_future_discovery_times_are_withheld(self):
        for observed in ['2026-09-04T23:59:59Z', '2026-09-07T20:00:01Z',
                         '2026-09-05T01:47:00', '2026-09-05T01:47:00-04:00',
                         '2026-02-31T01:47:00Z', None, 123]:
            with self.subTest(observed=observed):
                data = deepcopy(self.value)
                data['posts'][0]['discovered'] = observed
                result = self.parse(data)
                self.assertEqual(result.rejected, 1)

    def test_rejection_reasons_explain_future_provider_dates_without_reinterpretation(self):
        for discovered in ['2026-09-07T20:00:01Z', '2026-09-04T23:59:59Z', 'invalid']:
            row = deepcopy(self.value['posts'][0])
            row['discovered'] = discovered
            self.value['posts'].append(row)
        result = self.parse()
        self.assertFalse(result.complete)
        self.assertEqual(len(result.reports), 3)
        self.assertEqual(result.evidence['rejectionReasons'], {
            'future_discovery_timestamp': 1, 'outside_requested_window': 1,
            'invalid_discovery_timestamp': 1,
        })
        self.assertEqual(sum(result.evidence['rejectionReasons'].values()), result.rejected)
        self.assertIn('1 provider discovery timestamps were in the future', result.message)

    def test_verified_empty_is_scoped_success_but_invalid_envelopes_fail(self):
        result = self.parse({'posts': []})
        self.assertTrue(result.empty_is_valid)
        self.assertTrue(result.complete)
        self.assertEqual(result.parsed, 0)
        for value in [{}, [], {'posts': None}, {'posts': {}}, {'posts': [], 'error': 'failed'}]:
            with self.subTest(value=value), self.assertRaises(SourceError):
                self.parse(value)
        with self.assertRaisesRegex(SourceError, 'no usable'):
            self.parse({'posts': [{}]})

    def test_limits_invalid_json_content_type_and_redirects_fail(self):
        with self.assertRaisesRegex(SourceError, 'record limit'):
            self.parse({'posts': [{}] * (MAX_POSTS + 1)})
        for client in [Client(b'x' * (MAX_RESPONSE_BYTES + 1)), Client(b'{broken'),
                       Client(self.value, content_type='text/html'),
                       Client(self.value, response_url='https://www.ransomlook.io/api/recent'),
                       Client(SourceError('HTTP 403'))]:
            with self.subTest(client=client), self.assertRaises(SourceError):
                collect_with_client(client, now=NOW)

    def test_wrapper_budgets_closes_client_and_rejects_pagination_override(self):
        client = Client(self.value)
        with patch('ingestion.early_signals.CLIENT_FACTORY', return_value=client) as factory:
            collect(now=NOW)
        factory.assert_called_once_with(max_requests=2, max_bytes=2_000_000, deadline_seconds=60,
                                        allowed_urls={posts_url(START, END)})
        self.assertTrue(client.closed)
        client = Client(SourceError('unavailable'))
        with patch('ingestion.early_signals.CLIENT_FACTORY', return_value=client):
            with self.assertRaises(SourceError):
                collect(now=NOW)
        self.assertTrue(client.closed)
        for limit in [True, 0, 2, -1, '1']:
            with self.subTest(limit=limit), self.assertRaises(SourceError):
                collect(max_pages=limit, now=NOW)
        with self.assertRaises(SourceError):
            collect('another-source', now=NOW)

    def test_redirect_is_rejected_before_fetching_any_other_endpoint(self):
        class Redirect:
            status_code = 302

            def __init__(self, location):
                self.headers = {'Location': location}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Session:
            def __init__(self, location):
                self.headers = {}
                self.location = location
                self.calls = []
                self.closed = False

            def request(self, method, url, **kwargs):
                self.calls.append((method, url))
                return Redirect(self.location)

            def close(self):
                self.closed = True

        for location in ['/api/recent', '/api/posts?from=2026-09-01&to=2026-09-07',
                         'https://www.mass.gov/', 'https://example.onion/']:
            with self.subTest(location=location):
                session = Session(location)

                def factory(**kwargs):
                    return PublicClient(session=session, **kwargs)

                with patch('ingestion.early_signals.CLIENT_FACTORY', side_effect=factory):
                    with self.assertRaisesRegex(SourceError, 'permitted metadata endpoint'):
                        collect(now=NOW)
                self.assertEqual(session.calls, [('GET', posts_url(START, END))])
                self.assertTrue(session.closed)

    def test_utc_midnight_and_historical_window_end_are_explicit(self):
        from datetime import timedelta
        local = datetime(2026, 9, 7, 0, 10, tzinfo=timezone(timedelta(hours=9)))
        client = Client({'posts': []})
        collect_with_client(client, now=local)
        self.assertEqual(client.calls[0][0], posts_url(date(2026, 9, 4), date(2026, 9, 6)))
        with self.assertRaises(SourceError):
            collect_with_client(Client({'posts': []}), today=date(2026, 9, 8), now=NOW)
        with self.assertRaises(SourceError):
            collect_with_client(Client({'posts': []}), now=datetime(2026, 9, 7))


if __name__ == '__main__':
    unittest.main()
