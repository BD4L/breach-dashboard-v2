"""Independent source workers with a hard deadline and portable result artifacts.

Workers never open a database. The supervisor kills the entire worker process
group on expiry, including a stuck parser, and still emits a failure artifact.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from importlib import import_module
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .models import Collection, Report, SOURCES, SourceError
from .validation import timestamp

MAX_RESULT_BYTES = 40_000_000
DEFAULT_TIMEOUT = 600


def dispatch(source_id: str, *, max_pages: int | None = None) -> Collection:
    groups = {
        'adapters': {'massachusetts', 'california', 'hhs'},
        'state_portals': {'indiana', 'iowa', 'maine', 'north_dakota', 'oklahoma', 'maryland'},
        'other_portals': {'new_jersey', 'wisconsin', 'montana', 'washington', 'south_carolina', 'delaware', 'new_hampshire'},
        'special_portals': {'texas', 'sec'},
    }
    for name, sources in groups.items():
        if source_id in sources:
            # Import only this source's parser family; unrelated parser imports
            # are not prerequisites for an independent collection job.
            module = import_module(f'ingestion.{name}')
            return module.collect(source_id, max_pages=max_pages)
    raise SourceError(f'No adapter for {source_id}')


def atomic_json(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(payload.encode('utf-8')) > MAX_RESULT_BYTES:
        raise SourceError('Source result exceeded its 40 MB limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload + '\n')
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def decode_collection(value: object, source_id: str) -> Collection:
    if not isinstance(value, dict) or value.get('source_id') != source_id:
        raise SourceError('Adapter returned a different source; no records were saved.')
    if not isinstance(value.get('reports'), list) or type(value.get('complete')) is not bool:
        raise SourceError('Malformed source collection')
    if type(value.get('empty_is_valid', False)) is not bool:
        raise SourceError('Malformed empty-result contract')
    for key in ('parsed', 'rejected'):
        if type(value.get(key)) is not int or value[key] < 0:
            raise SourceError('Malformed source counts')
    if value['parsed'] != len(value['reports']) + value['rejected']:
        raise SourceError('Source row accounting does not reconcile')
    try:
        collection = Collection(**{**value, 'reports': [Report(**report) for report in value['reports']]})
    except (TypeError, ValueError) as error:
        raise SourceError('Malformed source report contract') from error
    if any(report.source_id != source_id for report in collection.reports):
        raise SourceError('Source result mixes records from another source')
    return collection


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_RESULT_BYTES:
        raise SourceError('Source artifact exceeded its 40 MB limit')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise SourceError('Source artifact is not an object')
    return value


def supervise(command: list[str], *, timeout: float) -> int:
    """A timeout covers imports, HTTP retries, parsing and output serialization."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise SourceError(f'Source exceeded its {timeout:g}-second hard deadline; worker stopped') from error


def collect_bounded(source_id: str, *, timeout: float = DEFAULT_TIMEOUT,
                    max_pages: int | None = None) -> Collection:
    if source_id not in SOURCES or not 0 < timeout <= 900:
        raise ValueError('Unknown source or deadline outside (0, 900] seconds')
    with tempfile.TemporaryDirectory(prefix='breach-source-') as directory:
        output = Path(directory) / 'worker.json'
        command = [sys.executable, '-m', 'ingestion.runner', '_worker', '--source', source_id,
                   '--output', str(output)]
        if max_pages is not None:
            command += ['--max-pages', str(max_pages)]
        code = supervise(command, timeout=timeout)
        if not output.is_file():
            raise SourceError(f'Source worker exited {code} without a result')
        value = read_json(output)
        if code != 0 or value.get('error'):
            raise SourceError(str(value.get('error', f'Source worker exited {code}'))[:2000])
        return decode_collection(value.get('collection'), source_id)


def fetch(source_id: str, output: Path, *, timeout: float, max_pages: int | None = None) -> int:
    envelope = {'schemaVersion': 1, 'sourceId': source_id, 'attemptedAt': timestamp()}
    try:
        collection = collect_bounded(source_id, timeout=timeout, max_pages=max_pages)
        envelope['collection'] = asdict(collection)
        valid_empty = collection.empty_is_valid and collection.parsed == 0
        code = 0 if collection.complete and not collection.rejected and (collection.reports or valid_empty) else 1
    except Exception as error:
        envelope['error'] = f'{type(error).__name__}: {error}'[:2000]
        code = 1
    envelope['completedAt'] = timestamp()
    atomic_json(output, envelope)
    print(f"{source_id}: {'collected' if code == 0 else 'incomplete/failed'}; result saved to {output}")
    if envelope.get('error'):
        print(envelope['error'])
    else:
        print(f'{collection.parsed} parsed; {collection.rejected} rejected. {collection.message}')
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['fetch', '_worker'])
    parser.add_argument('--source', required=True, choices=list(SOURCES))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument('--max-pages', type=int)
    args = parser.parse_args(argv)
    if args.command == 'fetch':
        return fetch(args.source, args.output, timeout=args.timeout, max_pages=args.max_pages)
    try:
        collection = dispatch(args.source, max_pages=args.max_pages)
        atomic_json(args.output, {'collection': asdict(collection)})
        return 0
    except Exception as error:
        atomic_json(args.output, {'error': f'{type(error).__name__}: {error}'[:2000]})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
