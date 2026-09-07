export type View = "recent" | "today" | "all" | "saved" | "sources";
export interface Source {
  id: string;
  label: string;
  jurisdiction: string;
  method: string;
  homepage: string;
  status: "healthy" | "unchanged" | "partial" | "failed" | "disabled";
  lastAttempt: string | null;
  lastSuccess: string | null;
  message: string;
  counts: {
    parsed: number;
    accepted: number;
    rejected: number;
    new: number;
    changed: number;
  };
  attribution?: { name: string; url: string; license: string; licenseUrl: string; changes: string };
}
export interface Report {
  id: string;
  sourceId: string;
  nativeId: string;
  organization: string;
  publishedDate: string | null;
  reportedDate: string | null;
  breachStart: string | null;
  breachEnd: string | null;
  discoveryDate: string | null;
  firstSeen: string;
  lastSeen: string;
  lastChanged: string;
  revision: number;
  affected: {
    count: number | null;
    scope: "state" | "national" | "reported" | "unknown";
    jurisdiction: string | null;
    qualifier: "exact" | "at_least" | "less_than" | "unknown";
  };
  dataTypes: string[];
  sourceUrl: string;
  noticeUrl: string | null;
  summary: string;
  signalType?: "ransomware_claim";
  sourceObservedAt?: string;
  qualityFlags: { code: string; message: string }[];
  evidence: { retrievedAt: string; contentHash: string; parserVersion: string };
  history: {
    observedAt: string;
    changedFields: string[];
    changes?: { field: string; before: unknown; after: unknown }[];
  }[];
}
export interface Dataset {
  schemaVersion: 1;
  mode: "demo" | "live";
  generatedAt: string;
  sources: Source[];
  reports: Report[];
}
export type ReportKind = "official" | "claims";
export type SearchField = "organization" | "ids" | "summary" | "dataTypes" | "source";
export interface Filters {
  query: string;
  source: string[] | null;
  size: string[] | null;
  quality: string[] | null;
  kind: ReportKind[] | null;
  searchFields: SearchField[] | null;
  sort: string;
}
export const INITIAL_FILTERS: Readonly<Filters> = Object.freeze({
  query: "",
  source: null,
  size: null,
  quality: null,
  kind: null,
  searchFields: null,
  sort: "latest",
});
export function freshInitialFilters(): Filters {
  return { ...INITIAL_FILTERS };
}
export function todayOfficialFilters(): Filters {
  return { ...INITIAL_FILTERS, kind: ["official"] };
}
export const DAY = 86_400_000;
export const SAVED_KEY = "breach-watch:saved-report-ids:v1";

const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const nullableText = (v: unknown) => v === null || typeof v === "string";
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const integer = (v: unknown) =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const validDate = (v: unknown): boolean =>
  typeof v === "string" &&
  /^\d{4}-\d{2}-\d{2}$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 10) === v;
const validTimestamp = (v: unknown): boolean =>
  typeof v === "string" &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
    v,
  ) &&
  validDate(v.slice(0, 10)) &&
  Number.isFinite(Date.parse(v));

export function readDataset(value: unknown): Dataset {
  const invalid = (): never => {
    throw new Error(
      "The published data does not match this dashboard’s format. Generate a fresh export and try again.",
    );
  };
  if (
    !object(value) ||
    value.schemaVersion !== 1 ||
    !["demo", "live"].includes(String(value.mode)) ||
    !validTimestamp(value.generatedAt) ||
    !Array.isArray(value.sources) ||
    !Array.isArray(value.reports)
  )
    return invalid();
  for (const s of value.sources) {
    if (
      !object(s) ||
      !["id", "label", "jurisdiction", "method", "homepage", "message"].every(
        (k) => typeof s[k] === "string",
      ) ||
      !["healthy", "unchanged", "partial", "failed", "disabled"].includes(
        String(s.status),
      ) ||
      !nullableText(s.lastAttempt) ||
      !nullableText(s.lastSuccess) ||
      !object(s.counts) ||
      !["parsed", "accepted", "rejected", "new", "changed"].every((k) =>
        integer((s.counts as Record<string, unknown>)[k]),
      )
    )
      return invalid();
    if (
      ![s.lastAttempt, s.lastSuccess].every(
        (date) => date === null || validTimestamp(date),
      )
    )
      return invalid();
    if (!safeUrl(s.homepage as string)) return invalid();
    if (s.attribution !== undefined && (!object(s.attribution) ||
        !["name", "url", "license", "licenseUrl", "changes"].every(
          key => typeof (s.attribution as Record<string, unknown>)[key] === "string",
        ) || !safeUrl(s.attribution.url as string) || !safeUrl(s.attribution.licenseUrl as string))) return invalid();
  }
  const sourceIds = new Set(value.sources.map((s) => s.id));
  const reportIds = new Set<string>();
  for (const r of value.reports) {
    if (
      !object(r) ||
      ![
        "id",
        "sourceId",
        "nativeId",
        "organization",
        "firstSeen",
        "lastSeen",
        "lastChanged",
        "sourceUrl",
        "summary",
      ].every((k) => typeof r[k] === "string") ||
      !sourceIds.has(r.sourceId) ||
      reportIds.has(r.id as string) ||
      ![
        "publishedDate",
        "reportedDate",
        "breachStart",
        "breachEnd",
        "discoveryDate",
        "noticeUrl",
      ].every((k) => nullableText(r[k])) ||
      !integer(r.revision) ||
      Number(r.revision) < 1 ||
      !strings(r.dataTypes) ||
      !object(r.affected) ||
      !(r.affected.count === null || integer(r.affected.count)) ||
      !["state", "national", "reported", "unknown"].includes(
        String(r.affected.scope),
      ) ||
      !["exact", "at_least", "less_than", "unknown"].includes(
        String(r.affected.qualifier),
      ) ||
      !nullableText(r.affected.jurisdiction) ||
      !object(r.evidence) ||
      !["retrievedAt", "contentHash", "parserVersion"].every(
        (k) => typeof (r.evidence as Record<string, unknown>)[k] === "string",
      ) ||
      !Array.isArray(r.qualityFlags) ||
      !r.qualityFlags.every(
        (f) =>
          object(f) &&
          typeof f.code === "string" &&
          typeof f.message === "string",
      ) ||
      !Array.isArray(r.history) ||
      !r.history.every(
        (h) =>
          object(h) &&
          typeof h.observedAt === "string" &&
          strings(h.changedFields),
      )
    )
      return invalid();
    reportIds.add(r.id as string);
    if ((r.signalType !== undefined && r.signalType !== "ransomware_claim") ||
        (r.sourceId === "ransomlook" && (r.signalType !== "ransomware_claim" || !validTimestamp(r.sourceObservedAt))) ||
        (r.signalType === "ransomware_claim" && r.sourceId !== "ransomlook") ||
        (r.sourceObservedAt !== undefined && !validTimestamp(r.sourceObservedAt))) return invalid();
    if (
      !["firstSeen", "lastSeen", "lastChanged"].every((k) =>
        validTimestamp(r[k]),
      ) ||
      !validTimestamp(r.evidence.retrievedAt) ||
      ![
        "publishedDate",
        "reportedDate",
        "breachStart",
        "breachEnd",
        "discoveryDate",
      ].every((k) => r[k] === null || validDate(r[k])) ||
      !r.history.every(
        (h) =>
          validTimestamp(h.observedAt) &&
          (h.changes === undefined ||
            (Array.isArray(h.changes) &&
              h.changes.every(
                (c: unknown) =>
                  object(c) &&
                  typeof c.field === "string" &&
                  "before" in c &&
                  "after" in c,
              ))),
      )
    )
      return invalid();
  }
  if (sourceIds.size !== value.sources.length) return invalid();
  return value as unknown as Dataset;
}

export function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
export function timestamp(value: string | null | undefined): number {
  return value ? Date.parse(value) : NaN;
}
export function signalTime(report: Report): number {
  return timestamp(report.sourceObservedAt ?? report.publishedDate ?? report.reportedDate);
}

export function isRecentSignal(report: Report, now: number, days = 7): boolean {
  const at = signalTime(report);
  return Number.isFinite(at) && at >= now - days * DAY && at <= now;
}
export function isRecent(report: Report, now: number): boolean {
  const time = Math.max(
    timestamp(report.firstSeen) || 0,
    timestamp(report.lastChanged) || 0,
  );
  return time >= now - 7 * DAY && time <= now + 5 * 60_000;
}

export function utcDay(now: number): string {
  return new Date(now).toISOString().slice(0, 10);
}

export function isReportFromToday(report: Report, now: number): boolean {
  const at = signalTime(report);
  return Number.isFinite(at) && at <= now && utcDay(at) === utcDay(now);
}

export function countTodayReports(reports: Report[], now: number): number {
  // The validated export has unique report IDs; related source reports remain separate.
  return reports.filter(report => isReportFromToday(report, now)).length;
}

export function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname.endsWith(".localhost") ||
    hostname === "[::1]" || hostname === "::1" || /^127(?:\.\d{1,3}){3}$/.test(hostname);
}
export function sourceHealth(
  source: Source,
  now: number,
): {
  label: string;
  tone: "good" | "warn" | "bad" | "neutral";
  stale: boolean;
} {
  const success = timestamp(source.lastSuccess);
  const stale = !Number.isFinite(success) || now - success > 48 * 60 * 60_000;
  if (source.status === "disabled")
    return { label: "Disabled", tone: "neutral", stale };
  if (
    success > now + 5 * 60_000 ||
    timestamp(source.lastAttempt) > now + 5 * 60_000
  )
    return { label: "Unreliable timestamp", tone: "warn", stale: true };
  if (source.status === "failed")
    return { label: "Collection failed", tone: "bad", stale };
  if (source.status === "partial")
    return { label: "Needs review", tone: "warn", stale };
  if (stale) return { label: "Stale", tone: "warn", stale };
  return {
    label: source.status === "unchanged" ? "No changes" : "Current",
    tone: "good",
    stale,
  };
}
export function formatDate(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = timestamp(value);
  if (!Number.isFinite(date)) return "Not reported";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
    ...options,
  }).format(new Date(date));
}
export function relativeTime(value: string | null, now: number): string {
  const date = timestamp(value);
  if (!Number.isFinite(date)) return "Never collected";
  const diff = now - date;
  if (diff < -5 * 60_000) return "Future timestamp";
  if (diff < 60_000) return "Just now";
  if (diff < 60 * 60_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / (60 * 60_000))}h ago`;
  return `${Math.floor(diff / DAY)}d ago`;
}
export function affectedScope(affected: Report["affected"]): string {
  if (affected.scope === "state")
    return affected.jurisdiction
      ? `${affected.jurisdiction} residents`
      : "State residents";
  if (affected.scope === "national") return "Nationwide";
  if (affected.scope === "reported") return "As reported · scope unspecified";
  return "Scope not reported";
}
export function affectedCount(affected: Report["affected"]): string {
  if (affected.count === null) return "Not reported";
  const prefix =
    affected.qualifier === "at_least"
      ? "≥ "
      : affected.qualifier === "less_than"
        ? "< "
        : "";
  return prefix + affected.count.toLocaleString("en-US");
}

export function sourceKind(sourceId: string): string {
  if (sourceId === "ransomlook") return "Ransomware claims";
  if (sourceId === "sec") return "SEC filings";
  if (sourceId === "hhs") return "Federal portal";
  return "State register";
}

export function reportSourceDate(report: Report, now: number): { label: "Observed" | "Published" | "Reported"; date: string } | null {
  const at = signalTime(report);
  if (!Number.isFinite(at) || at > now) return null;
  if (report.sourceObservedAt) return { label: "Observed", date: report.sourceObservedAt };
  if (report.publishedDate) return { label: "Published", date: report.publishedDate };
  return { label: "Reported", date: report.reportedDate! };
}

export function reportDateLabel(report: Report, now: number): string {
  const sourceDate = reportSourceDate(report, now);
  if (!sourceDate) return "Source date not reported";
  const year = sourceDate.date.slice(0, 4) === String(new Date(now).getUTCFullYear()) ? undefined : "numeric";
  return `${sourceDate.label} ${formatDate(sourceDate.date, { year })}`;
}

export function filterReports(
  reports: Report[],
  view: View,
  filters: Filters,
  saved: Set<string>,
  now: number,
  sources: Source[] = [],
): Report[] {
  const query = filters.query.trim().toLocaleLowerCase("en-US");
  const sourceLabels = new Map(sources.map(source => [source.id, source.label]));
  return reports
    .filter((r) => {
      if (view === "recent" && !isRecentSignal(r, now)) return false;
      if (view === "today" && !isReportFromToday(r, now)) return false;
      if (view === "saved" && !saved.has(r.id)) return false;
      if (filters.source !== null && !filters.source.includes(r.sourceId))
        return false;
      if (filters.size !== null && !filters.size.some(size =>
        size === "unknown" ? r.affected.count === null :
          ["1000", "100000"].includes(size) && r.affected.count !== null &&
          r.affected.count >= Number(size) && ["exact", "at_least"].includes(r.affected.qualifier)))
        return false;
      if (filters.quality !== null && !filters.quality.some(quality =>
        quality === "flagged" ? r.qualityFlags.length > 0 : quality === "updated" && r.revision > 1))
        return false;
      if (filters.kind !== null && !filters.kind.includes(r.signalType === "ransomware_claim" ? "claims" : "official"))
        return false;
      if (filters.searchFields?.length === 0) return false;
      if (!query) return true;
      const searchable: Record<SearchField, string> = {
        organization: r.organization,
        ids: `${r.id} ${r.nativeId}`,
        summary: r.summary,
        dataTypes: r.dataTypes.join(" "),
        source: `${r.sourceId} ${sourceLabels.get(r.sourceId) || ""}`,
      };
      const fields = filters.searchFields ?? Object.keys(searchable) as SearchField[];
      return fields.some(field => searchable[field].toLocaleLowerCase("en-US").includes(query));
    })
    .sort((a, b) => {
      if (filters.sort === "organization")
        return a.organization.localeCompare(b.organization);
      if (filters.sort === "affected")
        return (b.affected.count ?? -1) - (a.affected.count ?? -1);
      return (
        (timestamp(reportSourceDate(b, now)?.date) || 0) - (timestamp(reportSourceDate(a, now)?.date) || 0) ||
        a.organization.localeCompare(b.organization)
      );
    });
}
export function readSavedIds(value: string | null): Set<string> {
  try {
    const decoded = JSON.parse(value || "[]");
    return new Set(
      Array.isArray(decoded)
        ? decoded.filter((id) => typeof id === "string").slice(0, 5000)
        : [],
    );
  } catch {
    return new Set();
  }
}
export function fieldLabel(value: string): string {
  return (
    (
      {
        "affected.count": "Affected count",
        affected: "Affected count or scope",
        publishedDate: "Publication date",
        published_date: "Publication date",
        reportedDate: "Reported date",
        reported_date: "Reported date",
        sourceObservedAt: "Source observation time",
        source_observed_at: "Source observation time",
        signalType: "Report classification",
        signal_type: "Report classification",
        breachStart: "Breach start date",
        breach_start: "Breach start date",
        breachEnd: "Breach end date",
        breach_end: "Breach end date",
        discoveryDate: "Discovery date",
        discovery_date: "Discovery date",
        firstSeen: "First collection date",
        first_seen: "First collection date",
        lastSeen: "Last observation date",
        last_seen: "Last observation date",
        lastChanged: "Last change date",
        last_changed: "Last change date",
        organization: "Organization",
        noticeUrl: "Notice link",
        notice_url: "Notice link",
        dataTypes: "Data involved",
        data_types: "Data involved",
        summary: "Summary",
      } as Record<string, string>
    )[value] ||
    value
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replaceAll("_", " ")
      .replace(/^./, (c) => c.toUpperCase())
  );
}

export function qualityMessage(message: string): string {
  return message.replace(/\b(?:publishedDate|published_date|reportedDate|reported_date|breachStart|breach_start|breachEnd|breach_end|discoveryDate|discovery_date|firstSeen|first_seen|lastSeen|last_seen|lastChanged|last_changed)\b/g, fieldLabel);
}

export function recentHistory(report: Report): Report["history"] {
  return report.history
    .filter((h) => h.changedFields.some((field) => field !== "created"))
    .slice()
    .sort((a, b) => timestamp(b.observedAt) - timestamp(a.observedAt))
    .slice(0, 5);
}
export function changeValue(value: unknown, field: string): string {
  if (value === null || value === undefined || value === "")
    return "Not reported";
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "string") return value;
  if (Array.isArray(value))
    return value.map((item) => changeValue(item, field)).join(", ");
  if (object(value) && field === "affected" && "count" in value) {
    const count =
      typeof value.count === "number"
        ? value.count.toLocaleString("en-US")
        : "Not reported";
    const qualifier =
      value.qualifier === "at_least"
        ? "≥ "
        : value.qualifier === "less_than"
          ? "< "
          : "";
    const scope =
      value.scope === "state"
        ? `${value.jurisdiction || "State"} residents`
        : value.scope === "national"
          ? "Nationwide"
          : "Scope unspecified";
    return `${qualifier}${count} · ${scope}`;
  }
  return JSON.stringify(value);
}
