"""Explicit local ingestion commands; no production credentials or services."""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

from .models import Collection, SOURCES, SourceError
from .store import Store
from .validation import timestamp, utc_now


def collect(source_id: str, **options) -> Collection:
    # Delay optional parser/network dependencies until live collection is requested.
    from .runner import collect_bounded as collect_source
    return collect_source(source_id, **options)


def demo_events(now: datetime):
    from .demo import demo_events as events
    return events(now)


def parse_now(value: str) -> datetime:
    try:
        return utc_now(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a timezone-aware ISO timestamp, e.g. 2026-09-05T12:00:00Z.") from error


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command, description in (("demo", "Seed a separate database with synthetic examples."),
                                 ("collect", "Run isolated, deadline-bounded public collectors into a local database."),
                                 ("export", "Export the current local database without collecting.")):
        subparser = commands.add_parser(command, help=description)
        subparser.add_argument("--db", required=True, type=Path, help="Explicit path to local durable SQLite state.")
        subparser.add_argument("--export", required=True, type=Path, help="Destination for atomic public dashboard JSON.")
        subparser.add_argument("--now", type=parse_now, help="UTC observation timestamp override for reproducible fixtures.")
        if command == "collect":
            subparser.add_argument("--source", required=True, choices=["all", *SOURCES])
            subparser.add_argument("--max-pages", type=int, help="Override the adapter's page limit where supported.")
            subparser.add_argument("--timeout", type=float, help="Hard per-source deadline in seconds (maximum 900).")
    return result


def show_run(result: dict) -> None:
    counts = result["counts"]
    print(f"{result['sourceId']}: {result['status']}; {counts['accepted']} accepted, "
          f"{counts['rejected']} rejected, {counts['new']} new, {counts['changed']} changed. "
          f"{result['message']}")


def seed_demo(store: Store, now: datetime, *, explicit_now: bool) -> None:
    seeded_at = store.metadata("demo_seed_at")
    if seeded_at:
        if store.metadata("demo_seed_complete") != "yes":
            raise ValueError("This demo seed was interrupted. Use a fresh --db path to seed a complete timeline.")
        if explicit_now and timestamp(now) != seeded_at:
            raise ValueError(f"Demo database was seeded at {seeded_at}; use a fresh --db path for a different --now.")
        print(f"Demo database already seeded at {seeded_at}; exporting its existing timeline.")
        return
    if store.connection.execute("SELECT 1 FROM source_runs LIMIT 1").fetchone():
        raise ValueError("This demo database already contains observations. Use a fresh --db path to seed examples.")
    store.set_metadata("demo_seed_at", timestamp(now))
    for observed_at, event in sorted(demo_events(now), key=lambda event: event[0]):
        if isinstance(event, Collection):
            result = store.apply_collection(event, observed_at)
        else:
            source_id, message = event
            result = store.record_failure(source_id, message, observed_at)
        show_run(result)
    store.set_metadata("demo_seed_complete", "yes")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    now = args.now or utc_now()
    mode = {"demo": "demo", "collect": "live", "export": None}[args.command]
    try:
        if args.db.resolve() == args.export.resolve():
            raise ValueError("--db and --export must be different paths.")
        with Store(args.db, mode) as store:
            failed = False
            if args.command == "demo":
                seed_demo(store, now, explicit_now=args.now is not None)
            elif args.command == "collect":
                source_ids = list(SOURCES) if args.source == "all" else [args.source]
                for source_id in source_ids:
                    try:
                        options = {}
                        if args.max_pages is not None:
                            options['max_pages'] = args.max_pages
                        if args.timeout is not None:
                            options['timeout'] = args.timeout
                        collection = collect(source_id, **options)
                        if collection.source_id != source_id:
                            raise SourceError("Adapter returned a different source; no records were saved.")
                        result = store.apply_collection(collection, now)
                    except Exception as error:
                        # Record failures and continue to the remaining sources, then export
                        # retained data even if the source or parser is currently unavailable.
                        result = store.record_failure(source_id, f"{type(error).__name__}: {error}", now)
                    show_run(result)
                    failed |= result["status"] in {"failed", "partial"}
            dashboard = store.export(args.export, now)
            print(f"Exported {len(dashboard['reports'])} source reports in {store.mode} mode to {args.export}.")
            return 1 if failed else 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
