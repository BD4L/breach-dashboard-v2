"""Conservative public-report validation; unknown values remain unknown."""
from datetime import date, datetime, timezone
import re
from urllib.parse import urlsplit

from .models import Report, SOURCES


class InvalidReport(ValueError):
    """A record has no usable identity or original-source evidence."""


DATE_FIELDS = {
    "published_date": "publishedDate", "reported_date": "reportedDate",
    "breach_start": "breachStart", "breach_end": "breachEnd",
    "discovery_date": "discoveryDate",
}


def utc_now(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required.")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def timestamp(value: datetime | None = None) -> str:
    return utc_now(value).isoformat().replace("+00:00", "Z")


def safe_url(value: object) -> bool:
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in ("https", "http") and parsed.hostname
                    and not parsed.username and not parsed.password)
    except ValueError:
        return False


def normalize_report(report: Report, *, source_id: str, now: datetime) -> dict:
    """Reject unusable records; quarantine questionable fields with explicit flags."""
    if report.source_id != source_id or source_id not in SOURCES:
        raise InvalidReport("Record source does not match the collection.")
    native_id = str(report.native_id or "").strip()
    organization = str(report.organization or "").strip()
    if not native_id or not organization:
        raise InvalidReport("Record needs a native identifier and organization.")
    if not safe_url(report.source_url):
        raise InvalidReport("Record needs a safe original-source URL.")

    flags = []

    def flag(code: str, message: str) -> None:
        item = {"code": code, "message": message[:1000]}
        if item not in flags:
            flags.append(item)

    for item in report.quality_flags:
        if isinstance(item, dict) and item.get("code") and item.get("message"):
            flag(str(item["code"]), str(item["message"]))

    content = {"sourceId": source_id, "nativeId": native_id,
               "organization": organization, "sourceUrl": report.source_url}
    today = utc_now(now).date()
    for attribute, exported in DATE_FIELDS.items():
        raw = getattr(report, attribute)
        content[exported] = None
        if raw is None or raw == "":
            continue
        try:
            if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError("Non-ISO date")
            parsed = date.fromisoformat(raw)
        except ValueError:
            flag("invalid_date", f"{exported} has an invalid date: {raw!s}.")
            continue
        if parsed > today:
            flag("future_date", f"{exported} is in the future: {raw}.")
            continue
        content[exported] = parsed.isoformat()

    if content["breachStart"] and content["breachEnd"] and content["breachStart"] > content["breachEnd"]:
        flag("invalid_date_range", f"Breach start {content['breachStart']} follows end {content['breachEnd']}; both are withheld.")
        content["breachStart"] = content["breachEnd"] = None

    count = report.affected_count
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        flag("invalid_affected_count", f"Affected count is not a nonnegative integer: {count!s}.")
        count = None
    scope = report.affected_scope
    if scope not in {"state", "national", "reported", "unknown"}:
        flag("invalid_affected_scope", f"Unrecognized affected-count scope: {scope!s}.")
        scope = "unknown"
    jurisdiction = report.affected_jurisdiction
    if jurisdiction is not None:
        jurisdiction = str(jurisdiction).strip() or None
    if count is not None and scope == "state" and not jurisdiction:
        flag("missing_affected_jurisdiction", "State affected count has no stated jurisdiction.")
    if count is not None and scope == "unknown":
        flag("unknown_affected_scope", "The source does not establish the geographic scope of this affected count.")
    qualifier = report.affected_qualifier
    if qualifier not in {"exact", "at_least", "less_than", "unknown"}:
        flag("invalid_affected_qualifier", f"Unrecognized affected-count qualifier: {qualifier!s}.")
        qualifier = "unknown"
    if count is None:
        qualifier = "unknown"
    content["affected"] = {"count": count, "scope": scope,
                           "jurisdiction": jurisdiction, "qualifier": qualifier}

    notice_url = report.notice_url
    if notice_url and not safe_url(notice_url):
        flag("invalid_notice_url", "The notice URL is not a safe HTTP(S) link and was withheld.")
        notice_url = None
    content.update({
        "noticeUrl": notice_url or None,
        "summary": str(report.summary or "").strip(),
        "dataTypes": sorted({str(item).strip() for item in report.data_types if str(item).strip()}),
        "qualityFlags": sorted(flags, key=lambda item: (item["code"], item["message"])),
    })
    return content
