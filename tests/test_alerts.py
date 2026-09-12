from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from ingestion import alerts
from ingestion.models import Collection, Report
from ingestion.store import Store
from ingestion.validation import utc_now

NOW = datetime(2026, 9, 7, 20, tzinfo=timezone.utc)


def report(**changes):
    item = {'id': 'california:native-1', 'sourceId': 'california', 'revision': 1,
            'organization': 'Example Firm', 'sourceUrl': 'https://oag.ca.gov/example',
            'publishedDate': '2026-09-07', 'reportedDate': None,
            'firstSeen': '2026-09-07T19:00:00Z', 'lastSeen': '2026-09-07T20:00:00Z',
            **changes}
    item.setdefault('lastChanged', item['firstSeen'])
    item.setdefault('history', [{'observedAt': item['firstSeen'], 'changedFields': ['created'], 'changes': []}])
    return item


def snapshot(*reports):
    return {'schemaVersion': 1, 'mode': 'live', 'generatedAt': '2026-09-07T20:00:00Z',
            'sources': [{'id': 'california', 'label': 'California'}], 'reports': list(reports or [report()])}


class Reply:
    def __init__(self, value, status=200):
        self.content = json.dumps(value).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.content


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def post(self, url, **options):
        self.calls.append((url, options))
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result

    get = post


def configured(session):
    return alerts.PrivateDelivery(session=session, environment={
        'RESEND_API_KEY': 'test-key', 'ALERT_FROM_EMAIL': 'sender@example.invalid',
        'SUPABASE_URL': 'https://private.example.invalid', 'SUPABASE_SERVICE_KEY': 'private-test-key'})


def claimed(token='4b333210-83df-48f1-87b9-b9c2c37f277b'):
    return [{'id': '297d91e2-e5fd-45cd-9f57-8a1ce8c3ee03', 'lease_token': token,
             'payload': {'from': 'sender@example.invalid', 'to': ['staff@example.invalid'],
                         'subject': 'Example', 'text': 'Reviewed public notice'}}]


class AlertSelectionTests(unittest.TestCase):
    def test_secondary_reports_keep_their_classification_and_references_cannot_alert(self):
        item = report(id='hibp:example', sourceId='hibp', signalType='secondary_report')
        data = {**snapshot(item), 'sources': [{'id': 'hibp', 'label': 'Have I Been Pwned', 'category': 'secondary'}]}
        event = alerts.events_for_snapshot(data, now=NOW)[0]
        self.assertIn('secondary breach report', event['subject'])
        self.assertIn('https://creativecommons.org/licenses/by/4.0/', event['text'])
        data['sources'][0]['category'] = 'reference'
        item.pop('signalType')
        with self.assertRaises(ValueError): alerts.events_for_snapshot(data, now=NOW)

    def test_old_or_unknown_source_dates_do_not_become_new_breaches_on_import(self):
        for dated in (None, '2019-01-01', '2026-09-08', 'not a date'):
            self.assertEqual(alerts.events_for_snapshot(snapshot(report(publishedDate=dated)), now=NOW), [])

    def test_activation_cutoff_uses_observation_and_date_window_independently(self):
        self.assertEqual(alerts.events_for_snapshot(snapshot(), now=NOW, since=NOW), [])
        self.assertEqual(len(alerts.events_for_snapshot(snapshot(), now=NOW, since=NOW - timedelta(hours=2))), 1)
        old = report(publishedDate='2020-01-01', firstSeen='2026-09-07T19:59:00Z')
        self.assertEqual(alerts.events_for_snapshot(snapshot(old), now=NOW, since=NOW - timedelta(hours=2)), [])

    def test_repeat_observation_has_stable_event_key_and_no_last_seen_alert(self):
        first = alerts.events_for_snapshot(snapshot(), now=NOW)[0]
        newer = report(lastSeen='2026-09-07T20:00:00Z')
        self.assertEqual(first['event_key'], alerts.events_for_snapshot(snapshot(newer), now=NOW)[0]['event_key'])
        newer = report(firstSeen='2026-08-01T00:00:00Z')
        self.assertEqual(alerts.events_for_snapshot(snapshot(newer), now=NOW, since=NOW - timedelta(days=1)), [])

    def test_updates_require_real_material_changes_and_use_distinct_revision_keys(self):
        changed = report(revision=2, lastChanged='2026-09-07T19:30:00Z', history=[{
            'observedAt': '2026-09-07T19:30:00Z', 'changedFields': ['affected.count'], 'changes': [
                {'field': 'affected.count', 'before': 10, 'after': 20}]}, *report()['history']])
        event = alerts.events_for_snapshot(snapshot(changed), now=NOW)[0]
        self.assertTrue(event['subject'].startswith('Updated'))
        self.assertNotEqual(event['event_key'], alerts.events_for_snapshot(snapshot(), now=NOW)[0]['event_key'])
        for changes in ([], [{'field': 'qualityFlags', 'before': [], 'after': ['parser warning']}],
                        [{'field': 'affected.count', 'before': 20, 'after': 20}]):
            changed['history'][0]['changes'] = changes
            changed['history'][0]['changedFields'] = [change['field'] for change in changes]
            original = alerts.events_for_snapshot(snapshot(), now=NOW)[0]
            self.assertEqual(alerts.events_for_snapshot(snapshot(changed), now=NOW)[0]['event_key'], original['event_key'])

    def test_store_export_retains_new_and_material_events_through_technical_revisions(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / 'state.sqlite', 'live') as store:
            item = Report(source_id='california', native_id='1', organization='Example Firm',
                          source_url='https://oag.ca.gov/example', published_date='2026-09-07', affected_count=10)
            def observe(record, minutes):
                store.apply_collection(Collection('california', [record], 1), NOW - timedelta(minutes=minutes))
                return alerts.events_for_snapshot(store.dashboard(NOW), now=NOW)
            created = observe(item, 60)[0]
            technical = replace(item, quality_flags=[{'code': 'quality', 'message': 'Review parser field'}])
            self.assertEqual(observe(technical, 55)[0]['event_key'], created['event_key'])
            amended = replace(technical, affected_count=20)
            material = observe(amended, 50)[0]
            later = replace(amended, quality_flags=[])
            selected = observe(later, 40)[0]
            self.assertEqual(selected, material)
            self.assertEqual(selected['observed_at'], '2026-09-07T19:10:00Z')
            self.assertTrue(selected['subject'].startswith('Updated'))
            # A delivery ledger keyed by event_key sees no new event after technical changes.
            delivered = {created['event_key'], material['event_key']}
            self.assertEqual([event for event in observe(amended, 30) if event['event_key'] not in delivered], [])
            # The public suffix no longer proves a material event after enough technical revisions.
            for index in range(alerts.MAX_EXPORTED_HISTORY):
                selected = observe(later if index % 2 == 0 else amended, 29 - index)
            self.assertEqual(selected, [])

    def test_malformed_or_missing_history_fails_closed(self):
        for history in ([], None, [{'observedAt': '2026-09-07T19:00:00Z', 'changedFields': ['created'], 'changes': [{}]}]):
            with self.assertRaises(ValueError):
                alerts.events_for_snapshot(snapshot(report(history=history)), now=NOW)

    def test_claims_use_source_observation_and_keep_unverified_attribution(self):
        item = report(id='ransomlook:claim-1', sourceId='ransomlook', signalType='ransomware_claim',
                      sourceObservedAt='2026-09-06T10:00:00Z', publishedDate=None)
        data = {**snapshot(item), 'sources': [{'id': 'ransomlook', 'label': 'RansomLook'}]}
        event = alerts.events_for_snapshot(data, now=NOW)[0]
        self.assertEqual(event['source_date'], '2026-09-06')
        self.assertIn('unverified ransomware claim', event['subject'])
        self.assertIn('not an independently confirmed breach', event['text'])
        self.assertIn('RansomLook', event['text'])
        self.assertIn('https://creativecommons.org/licenses/by/4.0/', event['text'])
        for changes in ({'signalType': None}, {'signalType': 'confirmed_breach'}, {'sourceObservedAt': None},
                        {'sourceObservedAt': '2026-09-06T10:00:00'}, {'sourceObservedAt': '2026-09-08T10:00:00Z'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                alerts.events_for_snapshot({**data, 'reports': [{**item, **changes}]}, now=NOW)
        for changes in ({'signalType': 'ransomware_claim'}, {'signalType': 'confirmed_breach'}, {'sourceId': 'ransomlook'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                alerts.events_for_snapshot(snapshot(report(**changes)), now=NOW)

    def test_untrusted_content_is_escaped_and_unsafe_links_are_rejected(self):
        item = report(organization='<script>alert(1)</script>', summary='<img src=x onerror=alert(1)>')
        event = alerts.events_for_snapshot(snapshot(item), now=NOW)[0]
        self.assertNotIn('<script>', event['html'])
        self.assertIn('&lt;script&gt;', event['html'])
        with self.assertRaises(ValueError):
            alerts.events_for_snapshot(snapshot(report(sourceUrl='javascript:alert(1)')), now=NOW)

    def test_partial_demo_duplicate_or_future_snapshot_fails(self):
        for value in ({**snapshot(), 'schemaVersion': 2}, {**snapshot(), 'mode': 'demo'},
                      snapshot(report(), report()), {**snapshot(), 'generatedAt': '2027-01-01T00:00:00Z'}):
            with self.assertRaises(ValueError):
                alerts.events_for_snapshot(value, now=NOW)

    def test_dry_run_needs_no_credentials_or_network_and_preview_has_no_recipients(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps(snapshot()))
            output = StringIO()
            with patch('ingestion.alerts.PrivateDelivery', side_effect=AssertionError('must stay offline')), \
                    patch('ingestion.alerts.utc_now', side_effect=lambda value=None: utc_now(value if value is not None else NOW)), redirect_stdout(output):
                self.assertEqual(alerts.main(['--snapshot', str(path)]), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value['candidate_count'], 1)
            self.assertNotIn('to', value['preview'][0])
            self.assertNotIn('subscription', value['preview'][0])


class PublicSnapshotTests(unittest.TestCase):
    def test_download_uses_fixed_https_endpoint_and_writes_valid_full_snapshot(self):
        session = Session([Reply(snapshot())])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            result = alerts.fetch_published_snapshot(path, session=session, now=NOW)
            self.assertEqual(json.loads(path.read_bytes()), result)
        url, options = session.calls[0]
        self.assertEqual(url, 'https://bd4l.github.io/breach-dashboard-v2/data/dashboard.json')
        self.assertEqual(options['timeout'], (5, 20))
        self.assertFalse(options['allow_redirects'])
        self.assertNotIn('verify', options)
        with patch('requests.sessions.get_netrc_auth', side_effect=AssertionError('implicit credentials prohibited')):
            request = requests.Session().prepare_request(requests.Request(
                'GET', url, auth=options['auth'], headers={'Authorization': 'must not leave process'}))
        self.assertNotIn('Authorization', request.headers)

    def test_stale_future_demo_and_partial_snapshots_are_rejected(self):
        for changes in ({'generatedAt': '2026-09-07T17:59:59Z'}, {'generatedAt': '2026-09-07T20:02:01Z'},
                        {'generatedAt': None}, {'mode': 'demo'}, {'schemaVersion': 2}, {'reports': None}):
            with self.subTest(changes=changes), self.assertRaises(alerts.AlertError):
                alerts.validate_published_snapshot({**snapshot(), **changes}, now=NOW)
        for generated in ('2026-09-07T18:00:00Z', '2026-09-07T20:02:00Z'):
            alerts.validate_published_snapshot({**snapshot(), 'generatedAt': generated}, now=NOW)

    def test_failed_download_preserves_previous_file(self):
        malformed = Reply({})
        malformed.content = b'not json'
        for response in (Reply(snapshot(), 302), Reply(snapshot(), 503), malformed,
                         Reply({**snapshot(), 'generatedAt': '2020-01-01T00:00:00Z'}), requests.Timeout('private details')):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'snapshot.json'
                path.write_text('previous')
                with self.assertRaises(alerts.AlertError):
                    alerts.fetch_published_snapshot(path, session=Session([response]), now=NOW)
                self.assertEqual(path.read_text(), 'previous')

    def test_response_size_and_wall_clock_budgets_stop_download(self):
        for size, elapsed in ((10, 1), (50_000_000, 91)):
            with tempfile.TemporaryDirectory() as directory, patch('ingestion.alerts.MAX_SNAPSHOT_BYTES', size):
                path = Path(directory) / 'snapshot.json'
                with patch('ingestion.alerts.time.monotonic', side_effect=[0, elapsed]), self.assertRaises(alerts.AlertError):
                    alerts.fetch_published_snapshot(path, session=Session([Reply(snapshot())]), now=NOW)
                self.assertFalse(path.exists())

    def test_deliver_rejects_stale_snapshot_before_private_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps({**snapshot(), 'generatedAt': '2026-09-07T17:00:00Z'}))
            with patch('ingestion.alerts.utc_now', side_effect=lambda value=None: utc_now(value if value is not None else NOW)), redirect_stdout(StringIO()), \
                    patch('ingestion.alerts.PrivateDelivery', side_effect=AssertionError('must not contact private service')):
                self.assertEqual(alerts.main(['--snapshot', str(path), '--deliver']), 1)

    def test_download_cli_cannot_deliver_and_logs_only_public_counts(self):
        with tempfile.TemporaryDirectory() as directory, patch('ingestion.alerts.fetch_published_snapshot', return_value=snapshot()), \
                patch('ingestion.alerts.PrivateDelivery', side_effect=AssertionError('download has no private service')):
            path = Path(directory) / 'snapshot.json'
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(alerts.main(['--fetch-published', str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue())['reports'], 1)
            with redirect_stdout(StringIO()):
                self.assertEqual(alerts.main(['--fetch-published', str(path), '--deliver']), 1)


class PrivateDeliveryTests(unittest.TestCase):
    def test_prepared_private_requests_preserve_explicit_bearer_auth_without_netrc(self):
        session = Session([Reply([]), Reply({'id': 'accepted'})])
        worker = configured(session)
        worker.rpc('claim', {})
        worker.request('https://api.resend.com/emails', worker.provider_headers, {}, provider=True)
        with patch('requests.sessions.get_netrc_auth', side_effect=AssertionError('implicit credentials prohibited')):
            for url, options in session.calls:
                prepared = requests.Session().prepare_request(requests.Request(
                    'POST', url, headers=options['headers'], json=options['json'], auth=options['auth']))
                self.assertEqual(prepared.headers['Authorization'], options['headers']['Authorization'])

    def test_missing_configuration_and_unsafe_storage_fail_before_network(self):
        with self.assertRaises(alerts.AlertError):
            alerts.PrivateDelivery(environment={})
        with self.assertRaises(alerts.AlertError):
            alerts.PrivateDelivery(environment={'RESEND_API_KEY': 'x', 'ALERT_FROM_EMAIL': 'x@example.invalid',
                                   'SUPABASE_URL': 'https://host.invalid/redirect', 'SUPABASE_SERVICE_KEY': 'x'})

    def test_storage_claim_failure_stops_all_sends(self):
        session = Session([Reply({'message': 'sensitive details'}, 503)])
        with self.assertRaisesRegex(alerts.AlertError, '^private_storage_request_failed$'):
            configured(session).deliver([])
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn('resend.com', session.calls[0][0])

    def test_ack_failure_does_not_claim_another_email(self):
        session = Session([Reply(claimed()), Reply({'id': 'accepted-id'}), Reply({}, 503)])
        with self.assertRaises(alerts.AlertError):
            configured(session).deliver([])
        self.assertEqual(len(session.calls), 3)

    def test_retry_reuses_provider_key_and_frozen_payload_across_claims(self):
        session = Session([Reply(claimed()), requests.Timeout('sensitive provider text'), Reply(True),
                           Reply([]), Reply({'pending': 1, 'held': 0}),
                           Reply(claimed('fc0701da-2b55-4d3d-b102-48589c0e7483')), Reply({'id': 'accepted-id'}), Reply(True),
                           Reply([]), Reply({'pending': 0, 'held': 0})])
        worker = configured(session)
        self.assertEqual(worker.deliver([])['retry'], 1)
        self.assertEqual(worker.deliver([])['sent'], 1)
        sends = [options for url, options in session.calls if url == 'https://api.resend.com/emails']
        self.assertEqual(sends[0]['headers']['Idempotency-Key'], sends[1]['headers']['Idempotency-Key'])
        self.assertEqual(sends[0]['json'], sends[1]['json'])
        self.assertEqual(sends[0]['timeout'], (5, 20))
        self.assertFalse(sends[0]['allow_redirects'])
        self.assertNotIn('verify', sends[0])

    def test_provider_403_is_held_and_not_retried_as_success(self):
        session = Session([Reply(claimed()), Reply({'message': 'private recipient data'}, 403),
                           Reply(True), Reply([]), Reply({'pending': 0, 'held': 1})])
        result = configured(session).deliver([])
        self.assertEqual(result['held_total'], 1)
        ack = session.calls[2][1]['json']
        self.assertEqual(ack['p_state'], 'held')
        self.assertEqual(ack['p_error_code'], 'provider_http_403')

    def test_cli_partial_failure_is_nonzero_and_prints_only_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps(snapshot()))
            output = StringIO()
            with patch('ingestion.alerts.PrivateDelivery') as worker, \
                    patch('ingestion.alerts.utc_now', side_effect=lambda value=None: utc_now(value if value is not None else NOW)), redirect_stdout(output):
                worker.return_value.deliver.return_value = {'queued': 1, 'sent': 0, 'retry': 1,
                                                            'held': 0, 'held_total': 0, 'pending': 1}
                self.assertEqual(alerts.main(['--snapshot', str(path), '--deliver']), 1)
            self.assertNotIn('example.invalid', output.getvalue())


if __name__ == '__main__':
    unittest.main()
