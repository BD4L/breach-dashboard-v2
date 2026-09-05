"""Durable, diffable public state; never restore executable SQL from artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from .runner import atomic_json
from .store import Store, canonical

TABLES = {
    'metadata': ('key', 'value'),
    'reports': ('id', 'source_id', 'native_id', 'content_json', 'content_hash',
                'first_seen', 'last_seen', 'last_changed', 'revision', 'retrieved_at', 'parser_version'),
    'revisions': ('report_id', 'revision', 'observed_at', 'changed_fields_json', 'content_json', 'content_hash'),
    'source_runs': ('id', 'source_id', 'attempted_at', 'status', 'message', 'parsed', 'accepted', 'rejected', 'new_count', 'changed_count'),
    'source_run_evidence': ('run_id', 'evidence_json'),
}
MAX_ARCHIVE_BYTES = 200_000_000
MAX_FILE_BYTES = 90_000_000  # Below GitHub's per-file limit; fail instead of dropping history.


def save(db: Path, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'schemaVersion': 1, 'mode': 'live', 'files': {}}
    total = 0
    with Store(db) as store:
        if store.mode != 'live':
            raise ValueError('Only public live collection state may be persisted')
        store.connection.execute('BEGIN')
        try:
            for table, columns in TABLES.items():
                name = f'{table}.jsonl'
                # Identifiers are fixed constants, never values from the state branch.
                rows = store.connection.execute(f'SELECT {",".join(columns)} FROM {table} ORDER BY {columns[0]}'
                                                + (', revision' if table == 'revisions' else ''))
                payload = ''.join(canonical(dict(row)) + '\n' for row in rows).encode('utf-8')
                total += len(payload)
                if len(payload) > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                    raise ValueError('Durable state size budget reached; archive history before further publication')
                temporary = directory / f'.{name}.tmp'
                temporary.write_bytes(payload)
                temporary.replace(directory / name)
                manifest['files'][name] = {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
            store.connection.commit()
        except Exception:
            store.connection.rollback()
            raise
    # A failed/interrupted save never creates a matching manifest for partial files.
    atomic_json(directory / 'manifest.json', manifest)


def restore(directory: Path, db: Path) -> None:
    if db.exists():
        raise ValueError('State restore requires a fresh database path')
    manifest = json.loads((directory / 'manifest.json').read_text())
    expected = {f'{table}.jsonl' for table in TABLES}
    if (manifest.get('schemaVersion') != 1 or manifest.get('mode') != 'live'
            or set(manifest.get('files', {})) != expected):
        raise ValueError('Unsupported or incomplete public state manifest')
    total = 0
    for name, metadata in manifest['files'].items():
        path = directory / name
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES or size != metadata['bytes']:
            raise ValueError('State file size mismatch or budget exceeded')
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
            raise ValueError('State checksum mismatch; refusing to reset or replace history')
    try:
        with Store(db, 'live') as store, store.connection:
            store.connection.execute('DELETE FROM metadata')
            for table, columns in TABLES.items():
                with (directory / f'{table}.jsonl').open() as handle:
                    for line in handle:
                        row = json.loads(line)
                        if not isinstance(row, dict) or set(row) != set(columns):
                            raise ValueError(f'Unexpected {table} archive schema')
                        store.connection.execute(
                            f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                            [row[column] for column in columns])
            if store.metadata('mode') != 'live' or store.metadata('schema_version') != '1':
                raise ValueError('State metadata does not describe a live database')
            if store.connection.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('State archive contains broken history references')
            if store.connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Restored state failed SQLite integrity validation')
    except Exception:
        db.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['save', 'restore'])
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'save':
            save(args.db, args.directory)
        else:
            restore(args.directory, args.db)
        print(f'Public state {args.command} complete')
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        print(f'Public state {args.command} failed: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
