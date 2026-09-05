from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingestion.models import Collection, Report
from ingestion.store import ModeMismatch, Store


NOW = datetime(2026, 9, 5, 18, tzinfo=timezone.utc)


def report(**changes):
    base = Report(source_id="massachusetts", native_id="2026-123", organization="Example Health",
                  source_url="https://www.mass.gov/example-report.pdf", published_date="2026-09-01",
                  affected_count=40, affected_scope="state", affected_jurisdiction="MA",
                  affected_qualifier="exact", data_types=["Names", "Medical information"])
    return replace(base, **changes)


def collection(*reports, **changes):
    return Collection("massachusetts", list(reports), len(reports), **changes)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "state.sqlite"
        self.store = Store(self.path, "live")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def current(self):
        return self.store.dashboard(NOW)

    def source(self):
        return next(source for source in self.current()["sources"] if source["id"] == "massachusetts")

    def test_idempotent_retrieval_does_not_create_content_revision(self):
        first = self.store.apply_collection(collection(report()), NOW)
        initial = self.current()["reports"][0]
        later = NOW + timedelta(hours=2)
        second = self.store.apply_collection(collection(report(parser_version="2", data_types=["Medical information", "Names", "Names"])), later)
        latest = self.current()["reports"][0]
        self.assertEqual(first["counts"]["new"], 1)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(second["counts"], {"parsed": 1, "accepted": 1, "rejected": 0, "new": 0, "changed": 0})
        self.assertEqual(initial["firstSeen"], latest["firstSeen"])
        self.assertEqual(initial["lastChanged"], latest["lastChanged"])
        self.assertNotEqual(initial["lastSeen"], latest["lastSeen"])
        self.assertEqual(initial["evidence"]["contentHash"], latest["evidence"]["contentHash"])
        self.assertEqual(latest["evidence"]["parserVersion"], "2")
        self.assertEqual(latest["revision"], 1)
        self.assertEqual(len(latest["history"]), 1)

    def test_changed_record_retains_identity_first_seen_and_full_local_revision(self):
        self.store.apply_collection(collection(report()), NOW)
        initial = self.current()["reports"][0]
        result = self.store.apply_collection(collection(report(affected_count=73)), NOW + timedelta(days=1))
        updated = self.current()["reports"][0]
        self.assertEqual(result["counts"]["new"], 0)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(initial["id"], updated["id"])
        self.assertEqual(initial["firstSeen"], updated["firstSeen"])
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["history"][0]["changedFields"], ["affected.count"])
        self.assertEqual(updated["history"][0]["changes"], [{"field": "affected.count", "before": 40, "after": 73}])
        previous = self.store.connection.execute("SELECT content_json FROM revisions WHERE revision=1").fetchone()
        self.assertEqual(json.loads(previous[0])["affected"]["count"], 40)

    def test_records_are_identified_per_source_not_organization(self):
        ma = report()
        ca = report(source_id="california", affected_jurisdiction="CA")
        self.store.apply_collection(collection(ma, report(native_id="2026-124")), NOW)
        self.store.apply_collection(Collection("california", [ca], 1), NOW)
        reports = self.current()["reports"]
        self.assertEqual(len(reports), 3)
        self.assertEqual(len({item["id"] for item in reports}), 3)

    def test_failure_keeps_last_good_data_and_full_success_timestamp(self):
        self.store.apply_collection(collection(report()), NOW)
        original = self.current()["reports"]
        last_success = self.source()["lastSuccess"]
        self.store.record_failure("massachusetts", "HTTP 403; access denied.", NOW + timedelta(hours=1))
        current_source = self.source()
        self.assertEqual(self.current()["reports"], original)
        self.assertEqual(current_source["status"], "failed")
        self.assertEqual(current_source["lastSuccess"], last_success)
        self.assertNotEqual(current_source["lastAttempt"], last_success)
        self.assertEqual(current_source["counts"]["accepted"], 0)

    def test_empty_and_all_rejected_collections_are_failures(self):
        self.store.apply_collection(collection(report()), NOW)
        self.assertEqual(self.store.apply_collection(collection(), NOW + timedelta(hours=1))["status"], "failed")
        result = self.store.apply_collection(collection(report(organization="")), NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["counts"]["rejected"], 1)
        self.assertEqual(len(self.current()["reports"]), 1)

    def test_partial_saves_valid_updates_without_advancing_full_success(self):
        self.store.apply_collection(collection(report(), report(native_id="keep-missing")), NOW)
        last_success = self.source()["lastSuccess"]
        result = self.store.apply_collection(collection(report(affected_count=50), complete=False), NOW + timedelta(days=1))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(self.source()["lastSuccess"], last_success)
        self.assertEqual(len(self.current()["reports"]), 2)
        rejected = self.store.apply_collection(collection(report(affected_count=55), report(native_id="bad", source_url="javascript:alert(1)")), NOW + timedelta(days=2))
        self.assertEqual(rejected["status"], "partial")
        self.assertEqual(rejected["counts"]["accepted"], 1)
        self.assertEqual(rejected["counts"]["rejected"], 1)
        self.assertEqual(self.source()["lastSuccess"], last_success)

    def test_future_invalid_and_reversed_dates_are_quarantined_with_raw_evidence(self):
        record = report(published_date="2029-01-01", reported_date="2026-02-30",
                        breach_start="2026-08-31", breach_end="2026-08-01", discovery_date="2026-08-20")
        self.store.apply_collection(collection(record), NOW)
        saved = self.current()["reports"][0]
        for field in ("publishedDate", "reportedDate", "breachStart", "breachEnd"):
            self.assertIsNone(saved[field])
        self.assertEqual(saved["discoveryDate"], "2026-08-20")
        self.assertEqual({flag["code"] for flag in saved["qualityFlags"]}, {"future_date", "invalid_date", "invalid_date_range"})
        self.assertIn("2029-01-01", json.dumps(saved["qualityFlags"]))
        self.assertIn("2026-02-30", json.dumps(saved["qualityFlags"]))

    def test_count_scope_is_preserved_and_invalid_count_is_unknown(self):
        self.store.apply_collection(collection(report(), report(native_id="missing", affected_count=-1),
                                               report(native_id="ambiguous", affected_jurisdiction=None)), NOW)
        saved = {item["nativeId"]: item for item in self.current()["reports"]}
        self.assertEqual(saved["2026-123"]["affected"], {"count": 40, "scope": "state", "jurisdiction": "MA", "qualifier": "exact"})
        self.assertIsNone(saved["missing"]["affected"]["count"])
        self.assertEqual(saved["missing"]["affected"]["qualifier"], "unknown")
        self.assertIsNone(saved["ambiguous"]["affected"]["jurisdiction"])
        self.assertIn("missing_affected_jurisdiction", {flag["code"] for flag in saved["ambiguous"]["qualityFlags"]})

    def test_conflicting_duplicate_ids_do_not_silently_choose_a_record(self):
        result = self.store.apply_collection(collection(report(), report(affected_count=75), report(native_id="usable")), NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"], {"parsed": 3, "accepted": 1, "rejected": 2, "new": 1, "changed": 0})
        self.assertEqual(self.current()["reports"][0]["nativeId"], "usable")

    def test_a_failed_batch_rolls_back_earlier_changes_and_source_health(self):
        self.store.apply_collection(collection(report(native_id="later")), NOW + timedelta(days=1))
        before = self.current()
        with self.assertRaisesRegex(ValueError, "historical replay"):
            self.store.apply_collection(collection(report(native_id="would-be-new"), report(native_id="later")), NOW)
        self.assertEqual(self.current(), before)

    def test_mode_is_durable_and_cannot_be_mixed_or_relabelled(self):
        with self.assertRaises(ModeMismatch):
            Store(self.path, "demo")
        with self.assertRaises(ValueError):
            self.store.set_metadata("mode", "demo")
        with Store(self.path) as reopened:
            self.assertEqual(reopened.mode, "live")
        with self.assertRaisesRegex(ValueError, "existing initialized"):
            Store(Path(self.directory.name) / "absent.sqlite")

    def test_retrieval_metrics_are_retained_locally_without_untrusted_payloads(self):
        evidence = {"requests": 2, "bytes": 2048, "sha256": "a" * 64,
                    "retrievedAt": "2026-09-05T18:00:00Z", "body": "private document", "Authorization": "secret"}
        self.store.apply_collection(collection(report(), evidence=evidence), NOW)
        audit = self.store.connection.execute("SELECT evidence_json FROM source_run_evidence").fetchone()
        self.assertEqual(json.loads(audit[0]), {"requests": 2, "bytes": 2048, "sha256": "a" * 64, "retrievedAt": "2026-09-05T18:00:00Z"})
        self.assertNotIn("private document", json.dumps(self.current()))
        self.assertNotIn("requests", self.current()["reports"][0]["evidence"])

    def test_initial_pilot_database_adds_audit_table_without_losing_existing_state(self):
        self.store.apply_collection(collection(report()), NOW)
        expected = self.current()
        # The initially shipped schema had the same tables except source_run_evidence.
        with self.store.connection:
            self.store.connection.execute("DROP TABLE source_run_evidence")
        with Store(self.path) as migrated:
            self.assertEqual(migrated.dashboard(NOW), expected)
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM source_run_evidence").fetchone()[0], 0)
            result = migrated.apply_collection(collection(report(), evidence={"requests": 1}), NOW + timedelta(hours=1))
            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM source_run_evidence").fetchone()[0], 1)
        with Store(self.path) as reopened:
            self.assertEqual(len(reopened.dashboard(NOW)["reports"]), 1)
            self.assertEqual(reopened.connection.execute("SELECT COUNT(*) FROM source_run_evidence").fetchone()[0], 1)

    def test_public_history_is_bounded_while_full_revisions_stay_local(self):
        for index in range(25):
            self.store.apply_collection(collection(report(affected_count=index)), NOW + timedelta(hours=index))
        saved = self.current()["reports"][0]
        self.assertEqual(saved["revision"], 25)
        self.assertEqual(len(saved["history"]), 20)
        self.assertEqual(saved["history"][-1]["changes"], [{"field": "affected.count", "before": 4, "after": 5}])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 25)

    def test_older_failure_cannot_replace_newer_source_health(self):
        self.store.apply_collection(collection(report()), NOW)
        before = self.current()
        with self.assertRaisesRegex(ValueError, "historical replay"):
            self.store.record_failure("massachusetts", "Old failure", NOW - timedelta(hours=1))
        self.assertEqual(self.current(), before)

    def test_export_has_contract_and_replacement_failure_preserves_existing_file(self):
        self.store.apply_collection(collection(report()), NOW)
        destination = Path(self.directory.name) / "public" / "dashboard.json"
        exported = self.store.export(destination, NOW)
        prior_bytes = destination.read_bytes()
        self.assertEqual(json.loads(prior_bytes), exported)
        self.assertEqual(exported["schemaVersion"], 1)
        self.assertEqual(exported["mode"], "live")
        self.assertTrue(all("source_id" not in item for item in exported["reports"]))
        self.assertEqual({source["status"] for source in exported["sources"]}, {"healthy", "disabled"})
        with patch("ingestion.store.os.replace", side_effect=OSError("simulated interrupted replacement")):
            with self.assertRaises(OSError):
                self.store.export(destination, NOW + timedelta(days=1))
        self.assertEqual(destination.read_bytes(), prior_bytes)
        self.assertEqual(list(destination.parent.glob("*.tmp")), [])
        with self.assertRaises(ValueError):
            self.store.export(self.path, NOW)


if __name__ == "__main__":
    unittest.main()
