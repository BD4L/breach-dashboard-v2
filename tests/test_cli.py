from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingestion.cli import main
from ingestion.models import Collection, Report, SourceError, SOURCES
from ingestion.store import Store


NOW = datetime(2026, 9, 5, 18, tzinfo=timezone.utc)
NOW_TEXT = "2026-09-05T18:00:00Z"


def collection(source="massachusetts", *, complete=True):
    return Collection(source, [Report(source, "sample-1", "Example", SOURCES[source]["homepage"], reported_date="2026-08-01")], 1, complete=complete)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name) / "state.sqlite"
        self.export = Path(self.directory.name) / "public" / "dashboard.json"

    def tearDown(self):
        self.directory.cleanup()

    def run_cli(self, command, *arguments, now=NOW_TEXT):
        argv = [command, "--db", str(self.db), "--export", str(self.export), "--now", now, *arguments]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_collect_all_continues_after_failure_and_exports_retained_data(self):
        with Store(self.db, "live") as store:
            store.apply_collection(collection("hhs"), NOW - timedelta(days=1))

        def fetch(source):
            if source == "hhs":
                raise SourceError("HTTP 403; source is unavailable.")
            return collection(source)

        with patch("ingestion.cli.collect", side_effect=fetch) as fetch_mock:
            result, _, _ = self.run_cli("collect", "--source", "all")
        self.assertEqual(result, 1)
        self.assertEqual(fetch_mock.call_count, len(SOURCES))
        data = json.loads(self.export.read_text())
        self.assertEqual(len(data["reports"]), len(SOURCES))
        hhs = next(source for source in data["sources"] if source["id"] == "hhs")
        self.assertEqual(hhs["status"], "failed")
        self.assertEqual(hhs["lastSuccess"], "2026-09-04T18:00:00Z")

    def test_success_unchanged_partial_and_empty_have_honest_exit_codes(self):
        for payload, expected, status in ((collection(), 0, "healthy"), (collection(), 0, "unchanged"),
                                          (collection(complete=False), 1, "partial"),
                                          (Collection("massachusetts", [], 0), 1, "failed")):
            with self.subTest(status=status), patch("ingestion.cli.collect", return_value=payload):
                result, _, _ = self.run_cli("collect", "--source", "massachusetts")
                self.assertEqual(result, expected)
                data = json.loads(self.export.read_text())
                self.assertEqual(data["sources"][0]["status"], status)
                self.assertEqual(len(data["reports"]), 1)

    def test_adapter_source_mismatch_is_failure_without_wrong_source_writes(self):
        with patch("ingestion.cli.collect", return_value=collection("california")):
            result, _, _ = self.run_cli("collect", "--source", "massachusetts")
        self.assertEqual(result, 1)
        data = json.loads(self.export.read_text())
        self.assertEqual(data["reports"], [])
        self.assertEqual(data["sources"][0]["status"], "failed")
        self.assertIn("different source", data["sources"][0]["message"])

    def test_export_reads_existing_database_without_collecting(self):
        with Store(self.db, "live") as store:
            store.apply_collection(collection(), NOW)
        with patch("ingestion.cli.collect", side_effect=AssertionError("network must not run")):
            result, _, _ = self.run_cli("export")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.export.read_text())["mode"], "live")

    def test_export_requires_existing_state_and_never_overwrites_db(self):
        result, _, error = self.run_cli("export")
        self.assertEqual(result, 2)
        self.assertIn("existing initialized", error)
        self.assertFalse(self.db.exists())
        with Store(self.db, "live"):
            pass
        before = self.db.read_bytes()
        with redirect_stderr(io.StringIO()):
            result = main(["export", "--db", str(self.db), "--export", str(self.db)])
        self.assertEqual(result, 2)
        self.assertEqual(self.db.read_bytes(), before)

    def test_demo_creates_real_revision_timeline_and_replay_is_idempotent(self):
        result, _, _ = self.run_cli("demo")
        self.assertEqual(result, 0)
        original = self.export.read_bytes()
        data = json.loads(original)
        self.assertEqual(data["mode"], "demo")
        self.assertEqual(len(data["reports"]), 12)
        changed = next(report for report in data["reports"] if report["nativeId"] == "2026-DEMO-001")
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["history"][0]["changedFields"], ["affected.count"])
        self.assertEqual(next(source for source in data["sources"] if source["id"] == "hhs")["status"], "failed")
        result, output, _ = self.run_cli("demo")
        self.assertEqual(result, 0)
        self.assertIn("already seeded", output)
        self.assertEqual(self.export.read_bytes(), original)
        result, _, error = self.run_cli("demo", now="2026-09-06T18:00:00Z")
        self.assertEqual(result, 2)
        self.assertIn("fresh --db path", error)

    def test_demo_and_live_modes_cannot_mix_in_either_direction(self):
        self.assertEqual(self.run_cli("demo")[0], 0)
        with patch("ingestion.cli.collect") as fetch:
            result, _, _ = self.run_cli("collect", "--source", "all")
            self.assertEqual(result, 2)
            fetch.assert_not_called()
        self.db = Path(self.directory.name) / "live.sqlite"
        with Store(self.db, "live"):
            pass
        self.assertEqual(self.run_cli("demo")[0], 2)

    def test_naive_now_is_rejected_before_creating_files(self):
        with self.assertRaises(SystemExit) as error:
            self.run_cli("demo", now="2026-09-05T18:00:00")
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
