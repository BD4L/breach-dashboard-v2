from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ingestion.archive import restore, save
from ingestion.merge import merge
from ingestion.models import Collection, Report, SourceError, SOURCES
from ingestion.runner import atomic_json, decode_collection, dispatch, fetch, supervise
from ingestion.store import Store

NOW = datetime(2026, 9, 5, 20, tzinfo=timezone.utc)


def collection(count=10):
    return Collection('california', [Report('california', '12', 'Public Example',
                      'https://oag.ca.gov/privacy/databreach/list', affected_count=count)], 1)


class RunnerTests(unittest.TestCase):
    def test_dispatch_imports_only_the_requested_parser_family(self):
        with patch('ingestion.runner.import_module') as importer:
            dispatch('montana', max_pages=7)
            importer.assert_called_once_with('ingestion.other_portals')
            importer.return_value.collect.assert_called_once_with('montana', max_pages=7)

    def test_catalog_matches_adapter_contracts_without_loading_them_for_planning(self):
        from ingestion import (state_portals, other_portals, special_portals,
                               rediscovered_states, rediscovered_midatlantic,
                               rediscovered_northeast, rediscovered_sec, rediscovered_nj)
        active = {}
        for module in (state_portals, other_portals, special_portals, rediscovered_states,
                       rediscovered_midatlantic, rediscovered_northeast, rediscovered_sec, rediscovered_nj):
            active.update(module.SOURCES)
        for source, metadata in active.items():
            self.assertEqual(SOURCES[source], metadata)

    def test_rediscovered_sources_dispatch_to_the_active_publication_parser(self):
        for source, module in [('massachusetts', 'rediscovered_northeast'),
                               ('new_hampshire', 'rediscovered_northeast'),
                               ('iowa', 'rediscovered_states'), ('maine', 'rediscovered_states'),
                               ('maryland', 'rediscovered_midatlantic'), ('wisconsin', 'rediscovered_midatlantic'),
                               ('new_jersey', 'rediscovered_nj'), ('sec', 'rediscovered_sec')]:
            with self.subTest(source=source), patch('ingestion.runner.import_module') as importer:
                dispatch(source)
                importer.assert_called_once_with('ingestion.' + module)

    def test_hung_worker_is_killed_within_deadline(self):
        started = time.monotonic()
        with self.assertRaisesRegex(SourceError, 'hard deadline'):
            supervise([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.1)
        self.assertLess(time.monotonic() - started, 3)

    def test_timeout_still_produces_failure_artifact_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'california.json'
            with patch('ingestion.runner.collect_bounded', side_effect=SourceError('deadline exceeded')):
                self.assertEqual(fetch('california', path, timeout=1), 1)
            value = json.loads(path.read_text())
            self.assertEqual(value['sourceId'], 'california')
            self.assertIn('deadline', value['error'])
            self.assertNotIn('collection', value)

    def test_partial_and_empty_results_never_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            for payload in (Collection('california', [], 0), Collection('california', collection().reports, 1, complete=False)):
                with patch('ingestion.runner.collect_bounded', return_value=payload):
                    self.assertEqual(fetch('california', Path(directory) / 'result.json', timeout=1), 1)

    def test_cross_source_and_unreconciled_artifacts_are_rejected(self):
        value = asdict(collection())
        value['reports'][0]['source_id'] = 'hhs'
        with self.assertRaisesRegex(SourceError, 'another source'):
            decode_collection(value, 'california')
        value = asdict(collection())
        value['parsed'] = 20
        with self.assertRaisesRegex(SourceError, 'reconcile'):
            decode_collection(value, 'california')


class DurablePipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = self.root / 'source.sqlite'
        self.results = self.root / 'results'
        self.results.mkdir()
        self.output = self.root / 'dashboard.json'

    def tearDown(self):
        self.directory.cleanup()

    def test_fresh_runner_restore_preserves_first_seen_and_revision_history(self):
        with Store(self.db, 'live') as store:
            store.apply_collection(collection(10), NOW - timedelta(days=2))
            store.apply_collection(collection(20), NOW - timedelta(days=1))
            before = store.dashboard(NOW)
        archive = self.root / 'state-branch'
        save(self.db, archive)
        restored = self.root / 'fresh-runner.sqlite'
        restore(archive, restored)
        with Store(restored, 'live') as store:
            self.assertEqual(store.dashboard(NOW), before)
            result = store.apply_collection(collection(20), NOW)
            self.assertEqual(result['counts']['new'], 0)
            report = store.dashboard(NOW)['reports'][0]
            self.assertEqual(report['revision'], 2)
            self.assertEqual(report['firstSeen'], '2026-09-03T20:00:00Z')
            self.assertEqual(len(report['history']), 2)

    def test_corrupt_archive_never_creates_fresh_empty_replacement(self):
        with Store(self.db, 'live') as store:
            store.apply_collection(collection(), NOW)
        archive = self.root / 'state-branch'
        save(self.db, archive)
        with (archive / 'reports.jsonl').open('a') as handle:
            handle.write('{}\n')
        restored = self.root / 'fresh.sqlite'
        with self.assertRaises(ValueError):
            restore(archive, restored)
        self.assertFalse(restored.exists())

    def test_sparse_fallback_adds_new_identities_without_downgrading_existing_evidence(self):
        with Store(self.db, 'live') as store:
            store.apply_collection(collection(25), NOW - timedelta(days=1))
            before = store.dashboard(NOW)['reports'][0]
            sparse = Collection('california', [
                Report('california', '12', 'Public Example', 'https://oag.ca.gov/privacy/databreach/list'),
                Report('california', '13', 'New Example', 'https://oag.ca.gov/privacy/databreach/list'),
            ], 2, complete=False, new_records_only=True)
            result = store.apply_collection(sparse, NOW)
            records = {r['nativeId']: r for r in store.dashboard(NOW)['reports']}
            self.assertEqual(records['12'], before)
            self.assertEqual(result['counts']['new'], 1)
            self.assertEqual(result['counts']['changed'], 0)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(records['13']['revision'], 1)

    def test_missing_source_artifact_does_not_block_other_results_or_delete_history(self):
        with Store(self.db, 'live') as store:
            store.apply_collection(collection(), NOW - timedelta(days=1))
        hhs = Collection('hhs', [Report('hhs', '100', 'Public HHS Example',
                        'https://ocrportal.hhs.gov/ocr/breach/breach_frontpage.jsf')], 1)
        atomic_json(self.results / 'hhs.json', {'schemaVersion': 1, 'sourceId': 'hhs',
                    'attemptedAt': '2026-09-05T19:59:00Z', 'collection': asdict(hhs)})
        code = merge(self.db, self.results, self.output, ['california', 'hhs'], batch='run-1', now=NOW)
        self.assertEqual(code, 1)
        data = json.loads(self.output.read_text())
        self.assertEqual(len(data['reports']), 2)
        statuses = {source['id']: source['status'] for source in data['sources']}
        self.assertEqual(statuses['california'], 'failed')
        self.assertEqual(statuses['hhs'], 'healthy')
        with Store(self.db, 'live') as store:
            runs = store.connection.execute('SELECT count(*) FROM source_runs').fetchone()[0]
        self.assertEqual(merge(self.db, self.results, self.output, ['california', 'hhs'], batch='run-1', now=NOW), 1)
        with Store(self.db, 'live') as store:
            self.assertEqual(store.connection.execute('SELECT count(*) FROM source_runs').fetchone()[0], runs)

    def test_demo_archive_is_rejected(self):
        with Store(self.db, 'demo'):
            pass
        with self.assertRaisesRegex(ValueError, 'live'):
            save(self.db, self.root / 'archive')

    def test_explicit_valid_empty_retains_history_but_rejected_empty_still_fails(self):
        with Store(self.db, 'live') as store:
            store.apply_collection(collection(), NOW - timedelta(days=1))
            result = store.apply_collection(Collection('california', [], 0, empty_is_valid=True), NOW)
            self.assertEqual(result['status'], 'unchanged')
            self.assertEqual(len(store.dashboard(NOW)['reports']), 1)
            result = store.apply_collection(Collection('california', [], 1, rejected=1, empty_is_valid=True), NOW)
            self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
