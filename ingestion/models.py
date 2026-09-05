"""Source adapter contracts, independent of storage and frontend."""
from dataclasses import dataclass, field
from typing import Any
from .source_catalog import EXTRA_SOURCES

SOURCES = {
    "massachusetts": {"id": "massachusetts", "label": "Massachusetts", "jurisdiction": "MA", "method": "Annual report", "homepage": "https://www.mass.gov/lists/data-breach-notification-reports"},
    "hhs": {"id": "hhs", "label": "HHS Office for Civil Rights", "jurisdiction": "US", "method": "Federal portal", "homepage": "https://ocrportal.hhs.gov/ocr/breach/breach_frontpage.jsf"},
    "california": {"id": "california", "label": "California", "jurisdiction": "CA", "method": "Public notices", "homepage": "https://oag.ca.gov/privacy/databreach/list"},
}
SOURCES.update(EXTRA_SOURCES)

class SourceError(RuntimeError):
    """Fetching or parsing failed; this is not an empty successful run."""

@dataclass
class Report:
    source_id: str
    native_id: str
    organization: str
    source_url: str
    published_date: str | None = None
    reported_date: str | None = None
    breach_start: str | None = None
    breach_end: str | None = None
    discovery_date: str | None = None
    affected_count: int | None = None
    affected_scope: str = "unknown"
    affected_jurisdiction: str | None = None
    affected_qualifier: str = "unknown"
    data_types: list[str] = field(default_factory=list)
    notice_url: str | None = None
    summary: str = ""
    quality_flags: list[dict[str, str]] = field(default_factory=list)
    parser_version: str = "1"

@dataclass
class Collection:
    source_id: str
    reports: list[Report]
    parsed: int
    rejected: int = 0
    message: str = ""
    complete: bool = True
    # Bounded retrieval metadata may be included, but no document blobs in public exports.
    evidence: dict[str, Any] = field(default_factory=dict)
    # Only set after positively validating an empty, filtered source response.
    empty_is_valid: bool = False
