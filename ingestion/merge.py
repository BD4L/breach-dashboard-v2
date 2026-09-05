"""Merge independent source artifacts; missing results preserve last good records."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .models import SOURCES, SourceError
from .runner import decode_collection, read_json
from .store import Store
from .validation import timestamp, utc_now


def merge(db: Path, results: Path, output: Path, source_ids: list[str], *, batch: str,
          summary: Path | None = None, now: datetime | None = None) -> int:
    now = utc_now(now)
    failed = False
    lines = ['| Source | Result | Accepted | New | Changed |', '|---|---|---:|---:|---:|']
    if not source_ids or len(set(source_ids)) != len(source_ids) or any(s not in SOURCES for s in source_ids):
        raise ValueError('Expected sources must be known and unique')
    with Store(db, 'live') as store:
        # Repeating a completed merge is harmless, even after a Pages build failed.
        if store.metadata(f'batch:{batch}'):
            store.export(output, now)
            return int(store.metadata(f'batch:{batch}') == 'incomplete')
        for source_id in source_ids:
            observed_at = now
            try:
                path = results / f'{source_id}.json'
                if not path.is_file():
                    raise SourceError('Source job did not produce a result (failed, cancelled, or timed out)')
                value = read_json(path)
                if value.get('schemaVersion') != 1 or value.get('sourceId') != source_id:
                    raise SourceError('Source artifact identity/schema mismatch')
                observed_at = utc_now(datetime.fromisoformat(value['attemptedAt'].replace('Z', '+00:00')))
                if observed_at > now:
                    raise SourceError('Source artifact timestamp is in the future')
                if value.get('error'):
                    raise SourceError(str(value['error'])[:2000])
                collection = decode_collection(value.get('collection'), source_id)
                result = store.apply_collection(collection, observed_at)
            except Exception as error:
                # Failure observations are recorded at merge time, even for stale/bad artifacts.
                result = store.record_failure(source_id, f'{type(error).__name__}: {error}', now)
            counts = result['counts']
            failed |= result['status'] in {'failed', 'partial'}
            lines.append(f"| {source_id} | {result['status']} | {counts['accepted']} | {counts['new']} | {counts['changed']} |")
            print(f"{source_id}: {result['status']}; {counts['accepted']} accepted, {counts['new']} new, {counts['changed']} changed")
        store.set_metadata(f'batch:{batch}', 'incomplete' if failed else 'complete')
        store.export(output, now)
    if summary:
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text('\n'.join(lines) + '\n')
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--sources', nargs='+', choices=list(SOURCES), required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args(argv)
    return merge(args.db, args.results, args.export, args.sources, batch=args.batch, summary=args.summary)


if __name__ == '__main__':
    raise SystemExit(main())
