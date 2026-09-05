"""Explicitly synthetic examples. No record describes an actual organization."""
from dataclasses import replace
from datetime import datetime, timedelta
from .models import Collection, Report, SOURCES


def demo_collections(now: datetime) -> list[Collection]:
    """Current sample snapshot, designed to exercise ambiguity and revisions."""
    day = lambda offset: (now - timedelta(days=offset)).date().isoformat()
    specs = [
        ("massachusetts", "2026-DEMO-001", "Example Community Health", 12480, ["Social Security numbers", "Medical information"], 5),
        ("california", "demo-notice-002", "Example Benefits Cooperative", None, ["Names", "Contact details"], 4),
        ("hhs", "demo-ocr-003", "Example Regional Medical Center", 42800, ["Medical information", "Dates of birth"], 6),
        ("california", "demo-notice-004", "Example Employee Services", 820, ["Social Security numbers", "Financial information"], 1),
        ("massachusetts", "2026-DEMO-005", "Example Learning Foundation", 315, ["Names", "Dates of birth"], 1),
        ("hhs", "demo-ocr-006", "Example Outpatient Network", 6100, ["Medical information"], 7),
        ("california", "demo-notice-007", "Example Retail Group", None, ["Payment information"], 4),
        ("massachusetts", "2026-DEMO-008", "Example Community Health", 980, ["Contact details"], 8),
        ("california", "demo-notice-009", "Example Housing Association", 2450, ["Social Security numbers", "Names"], 6),
        ("hhs", "demo-ocr-010", "Example Diagnostic Services", 540, ["Medical information", "Insurance information"], 10),
        ("massachusetts", "2026-DEMO-011", "Example Professional Services", 75, ["Financial information"], 12),
        ("california", "demo-notice-012", "Example Technology Cooperative", None, ["Account credentials"], 14),
    ]
    grouped = {source: [] for source in SOURCES}
    for source, native_id, organization, count, types, age in specs:
        is_state = source != "hhs"
        grouped[source].append(Report(
            source_id=source, native_id=native_id, organization=organization,
            source_url=SOURCES[source]["homepage"],
            published_date=day(age) if source != "hhs" else None,
            reported_date=day(age) if source == "hhs" else None,
            breach_start=day(age + 42) if count is not None else None,
            breach_end=day(age + 39) if count is not None else None,
            discovery_date=day(age + 20) if count is not None else None,
            affected_count=count,
            affected_scope="state" if is_state else "reported",
            affected_jurisdiction=SOURCES[source]["jurisdiction"] if is_state else None,
            affected_qualifier="exact" if count is not None else "unknown",
            data_types=types,
            summary="Synthetic example for reviewing the interface. No real breach or organization is represented. The linked page is the official source index, not evidence of this example.",
            quality_flags=([{"code":"count_unknown", "message":"The source has not provided an affected-person count."}] if count is None else []),
            parser_version="demo-1",
        ))
    # Explicitly questionable source date exercises the validation path.
    grouped["california"][-1] = replace(grouped["california"][-1], published_date=(now + timedelta(days=120)).date().isoformat())
    return [Collection(source, reports, len(reports), message="Synthetic preview records; collection was not performed.") for source, reports in grouped.items()]


def demo_events(now: datetime):
    """Seed real revision mechanics with a deterministic synthetic timeline."""
    collections = demo_collections(now)
    events = []
    for collection in collections:
        initial = []
        for index, report in enumerate(collection.reports):
            if index == 1 and collection.source_id != "hhs":
                continue  # A genuinely new source record arrives in the later snapshot.
            initial.append(replace(report, affected_count=8200) if report.native_id == "2026-DEMO-001" else report)
        events.append((now - timedelta(days=4), Collection(collection.source_id, initial, len(initial), message="Synthetic initial snapshot.")))
    for collection in collections:
        if collection.source_id == "hhs":
            events.append((now - timedelta(minutes=80), ("hhs", "Example failure: source structure changed. Last valid reports are retained.")))
        else:
            events.append((now - timedelta(minutes=90), collection))
    return sorted(events, key=lambda event: event[0])
