"""Local SQLite state with source health, immutable revisions, and atomic export."""
from contextlib import AbstractContextManager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from .models import Collection, SOURCES
from .validation import InvalidReport, normalize_report, timestamp, utc_now


class ModeMismatch(ValueError):
    pass


MAX_EXPORTED_HISTORY = 20


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def report_id(source_id: str, native_id: str) -> str:
    digest = hashlib.sha256(native_id.encode("utf-8")).hexdigest()[:24]
    return f"{source_id}:{digest}"


def changed_fields(before: dict, after: dict, prefix: str = "") -> list[str]:
    fields = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key), after.get(key)
        field = f"{prefix}.{key}" if prefix else key
        if isinstance(left, dict) and isinstance(right, dict):
            fields.extend(changed_fields(left, right, field))
        elif left != right:
            fields.append(field)
    return fields


def field_value(content: dict, field: str):
    value = content
    for component in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(component)
    return value


def bounded_evidence(evidence: dict | None) -> dict:
    """Keep known retrieval metrics, never response bodies, headers, or credentials."""
    if not isinstance(evidence, dict):
        return {}
    result = {}
    for key in ("requests", "bytes", "httpStatus", "documentCount", "pageCount"):
        value = evidence.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1:
            result[key] = value
    digest = evidence.get("sha256")
    if isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        result["sha256"] = digest.lower()
    retrieved_at = evidence.get("retrievedAt")
    if isinstance(retrieved_at, str):
        try:
            result["retrievedAt"] = timestamp(datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")))
        except ValueError:
            pass
    return result


class Store(AbstractContextManager):
    def __init__(self, db_path: str | Path, mode: str | None = None):
        if mode not in {None, "demo", "live"}:
            raise ValueError("Database mode must be demo or live.")
        self.path = Path(db_path)
        if mode is None and not self.path.is_file():
            raise ValueError("Export requires an existing initialized database.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=20)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize(mode)
        except Exception:
            self.connection.close()
            raise

    def _initialize(self, mode: str | None) -> None:
        existing = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row["name"] for row in existing}
        if tables and "metadata" not in tables:
            raise ValueError("This is not a breach-dashboard database.")
        if "metadata" in tables:
            actual_mode = self.metadata("mode")
            if actual_mode not in {"demo", "live"} or self.metadata("schema_version") != "1":
                raise ValueError("Unsupported or incomplete database metadata.")
            if mode is not None and actual_mode != mode:
                raise ModeMismatch(f"Database is {actual_mode}; use a separate path for {mode} data.")
            # Additive local-pilot migration for databases created before audit metrics.
            if "source_run_evidence" not in tables:
                with self.connection:
                    self.connection.execute("CREATE TABLE source_run_evidence (run_id INTEGER PRIMARY KEY REFERENCES source_runs(id), evidence_json TEXT NOT NULL)")
            self.mode = actual_mode
            return
        if mode is None:
            raise ValueError("Database has not been initialized.")
        self.connection.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE reports (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL, native_id TEXT NOT NULL,
                content_json TEXT NOT NULL, content_hash TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_changed TEXT NOT NULL,
                revision INTEGER NOT NULL, retrieved_at TEXT NOT NULL, parser_version TEXT NOT NULL,
                UNIQUE(source_id, native_id)
            );
            CREATE TABLE revisions (
                report_id TEXT NOT NULL REFERENCES reports(id), revision INTEGER NOT NULL,
                observed_at TEXT NOT NULL, changed_fields_json TEXT NOT NULL,
                content_json TEXT NOT NULL, content_hash TEXT NOT NULL,
                PRIMARY KEY(report_id, revision)
            );
            CREATE TABLE source_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                attempted_at TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
                parsed INTEGER NOT NULL, accepted INTEGER NOT NULL, rejected INTEGER NOT NULL,
                new_count INTEGER NOT NULL, changed_count INTEGER NOT NULL
            );
            CREATE INDEX source_runs_latest ON source_runs(source_id, id DESC);
            CREATE TABLE source_run_evidence (
                run_id INTEGER PRIMARY KEY REFERENCES source_runs(id), evidence_json TEXT NOT NULL
            );
        """)
        with self.connection:
            self.connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                        [("mode", mode), ("schema_version", "1")])
        self.mode = mode

    def __exit__(self, *args):
        self.close()
        return False

    def close(self) -> None:
        self.connection.close()

    def metadata(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        if key in {"mode", "schema_version"}:
            raise ValueError("Database identity metadata cannot be changed.")
        with self.connection:
            self.connection.execute("INSERT INTO metadata VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _run(self, source_id: str, attempted_at: str, status: str, message: str, counts: dict,
             evidence: dict | None = None) -> dict:
        previous = self.connection.execute("SELECT attempted_at FROM source_runs WHERE source_id=? ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
        if previous and attempted_at < previous[0]:
            raise ValueError("Source observation precedes stored health; historical replay is not allowed.")
        cursor = self.connection.execute("""
            INSERT INTO source_runs(source_id, attempted_at, status, message, parsed, accepted, rejected, new_count, changed_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_id, attempted_at, status, message[:2000], counts["parsed"], counts["accepted"],
              counts["rejected"], counts["new"], counts["changed"]))
        self.connection.execute("INSERT INTO source_run_evidence VALUES (?, ?)",
                                (cursor.lastrowid, canonical(bounded_evidence(evidence))))
        return {"sourceId": source_id, "status": status, "message": message[:2000], "counts": counts}

    def record_failure(self, source_id: str, message: str, now: datetime | None = None,
                       *, parsed: int = 0, rejected: int = 0, evidence: dict | None = None) -> dict:
        if source_id not in SOURCES:
            raise ValueError(f"Unknown source: {source_id}")
        counts = {"parsed": parsed, "accepted": 0, "rejected": rejected, "new": 0, "changed": 0}
        with self.connection:
            return self._run(source_id, timestamp(now), "failed", message, counts, evidence)

    def apply_collection(self, collection: Collection, now: datetime | None = None) -> dict:
        now = utc_now(now)
        observed_at = timestamp(now)
        source_id = collection.source_id
        if source_id not in SOURCES:
            raise ValueError(f"Unknown source: {source_id}")
        if (not isinstance(collection.parsed, int) or collection.parsed < 0
                or not isinstance(collection.rejected, int) or collection.rejected < 0
                or collection.parsed != len(collection.reports) + collection.rejected):
            return self.record_failure(source_id, "Collection counts are inconsistent; no records were saved.", now, evidence=collection.evidence)
        rejected = collection.rejected
        normalized = {}
        conflicted = set()
        reasons = []
        for report in collection.reports:
            try:
                content = normalize_report(report, source_id=source_id, now=now)
            except InvalidReport as error:
                rejected += 1
                reasons.append(str(error))
                continue
            native_id = content["nativeId"]
            if native_id in conflicted:
                rejected += 1
            elif native_id in normalized:
                previous, _ = normalized[native_id]
                rejected += 1
                if previous != content:
                    del normalized[native_id]
                    conflicted.add(native_id)
                    rejected += 1
                    reasons.append("Conflicting duplicate native identifiers were withheld.")
                else:
                    reasons.append("Duplicate native identifiers were ignored.")
            else:
                normalized[native_id] = (content, str(report.parser_version))
        counts = {"parsed": collection.parsed, "accepted": len(normalized),
                  "rejected": rejected, "new": 0, "changed": 0}
        message_parts = [collection.message] if collection.message else []
        if reasons:
            message_parts.extend(dict.fromkeys(reasons))
        valid_empty = collection.empty_is_valid is True and collection.parsed == 0 and rejected == 0
        if not normalized and not valid_empty:
            message_parts.append("No valid reports were returned; retained the last valid data.")
            return self.record_failure(source_id, " ".join(message_parts), now,
                                       parsed=collection.parsed, rejected=rejected, evidence=collection.evidence)

        with self.connection:
            for native_id, (content, parser_version) in normalized.items():
                serialized = canonical(content)
                content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                identifier = report_id(source_id, native_id)
                existing = self.connection.execute("SELECT * FROM reports WHERE source_id=? AND native_id=?", (source_id, native_id)).fetchone()
                if existing and observed_at < existing["last_seen"]:
                    raise ValueError("Collection observation precedes stored data; historical replay is not allowed.")
                if existing is None:
                    revision = 1
                    fields = ["created"]
                    self.connection.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                            (identifier, source_id, native_id, serialized, content_hash,
                                             observed_at, observed_at, observed_at, revision, observed_at, parser_version))
                    counts["new"] += 1
                elif existing["content_hash"] != content_hash:
                    revision = existing["revision"] + 1
                    fields = changed_fields(json.loads(existing["content_json"]), content)
                    self.connection.execute("""UPDATE reports SET content_json=?, content_hash=?, last_seen=?,
                        last_changed=?, revision=?, retrieved_at=?, parser_version=? WHERE id=?""",
                        (serialized, content_hash, observed_at, observed_at, revision, observed_at, parser_version, identifier))
                    counts["changed"] += 1
                else:
                    self.connection.execute("UPDATE reports SET last_seen=?, retrieved_at=?, parser_version=? WHERE id=?",
                                            (observed_at, observed_at, parser_version, identifier))
                    continue
                self.connection.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?)",
                                        (identifier, revision, observed_at, canonical(fields), serialized, content_hash))
            if rejected or not collection.complete:
                status = "partial"
                message_parts.append("Collection is incomplete; last full success was not advanced.")
            elif counts["new"] or counts["changed"]:
                status = "healthy"
            else:
                status = "unchanged"
            if not message_parts:
                message_parts.append("Collection validated." if status == "healthy" else "No content changes found.")
            return self._run(source_id, observed_at, status, " ".join(message_parts), counts, collection.evidence)

    def dashboard(self, now: datetime | None = None) -> dict:
        # Explicit read transaction makes the export one consistent SQLite snapshot.
        self.connection.execute("BEGIN")
        try:
            sources = []
            for source_id, metadata in SOURCES.items():
                latest = self.connection.execute("SELECT * FROM source_runs WHERE source_id=? ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
                success = self.connection.execute("SELECT attempted_at FROM source_runs WHERE source_id=? AND status IN ('healthy','unchanged') ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
                sources.append({**metadata,
                    "status": latest["status"] if latest else "disabled",
                    "lastAttempt": latest["attempted_at"] if latest else None,
                    "lastSuccess": success[0] if success else None,
                    "message": latest["message"] if latest else "Not collected in this database.",
                    "counts": {"parsed": latest["parsed"] if latest else 0,
                               "accepted": latest["accepted"] if latest else 0,
                               "rejected": latest["rejected"] if latest else 0,
                               "new": latest["new_count"] if latest else 0,
                               "changed": latest["changed_count"] if latest else 0}})
            histories = {}
            previous_content = {}
            for row in self.connection.execute("SELECT report_id, observed_at, changed_fields_json, content_json FROM revisions ORDER BY report_id, revision ASC"):
                identifier = row["report_id"]
                fields = json.loads(row["changed_fields_json"])
                content = json.loads(row["content_json"])
                previous = previous_content.get(identifier)
                changes = ([{"field": field, "before": field_value(previous, field), "after": field_value(content, field)}
                            for field in fields] if previous is not None else [])
                history = histories.setdefault(identifier, [])
                history.append({"observedAt": row["observed_at"], "changedFields": fields, "changes": changes})
                if len(history) > MAX_EXPORTED_HISTORY:
                    del history[0]
                previous_content[identifier] = content
            reports = []
            for row in self.connection.execute("SELECT * FROM reports ORDER BY last_changed DESC, id ASC"):
                reports.append({**json.loads(row["content_json"]), "id": row["id"],
                    "firstSeen": row["first_seen"], "lastSeen": row["last_seen"],
                    "lastChanged": row["last_changed"], "revision": row["revision"],
                    "evidence": {"retrievedAt": row["retrieved_at"], "contentHash": row["content_hash"], "parserVersion": row["parser_version"]},
                    "history": list(reversed(histories.get(row["id"], [])))})
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {"schemaVersion": 1, "mode": self.mode, "generatedAt": timestamp(now), "sources": sources, "reports": reports}

    def export(self, path: str | Path, now: datetime | None = None) -> dict:
        destination = Path(path)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Export must not overwrite its SQLite database.")
        data = self.dashboard(now)
        # Compact public snapshots keep expanded source coverage inexpensive to load.
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                             prefix=f".{destination.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return data
