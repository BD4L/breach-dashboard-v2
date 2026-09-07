import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUpRight,
  Bookmark,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  AlertCircle as CircleAlert,
  AlertTriangle,
  Clock3,
  Database,
  Download,
  FileText,
  FolderSearch,
  Info,
  Pause,
  Plus,
  Plug,
  Rss,
  RotateCcw,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  affectedCount,
  affectedScope,
  changeValue,
  countTodayReports,
  DAY,
  fieldLabel,
  filterReports,
  formatDate,
  INITIAL_FILTERS,
  isRecent,
  isRecentSignal,
  isLocalHostname,
  qualityMessage,
  readSavedIds,
  recentHistory,
  reportDateLabel,
  relativeTime,
  safeUrl,
  SAVED_KEY,
  sourceHealth,
  sourceKind,
  timestamp,
  todayOfficialFilters,
  utcDay,
  type Dataset,
  type Filters,
  type Report,
  type Source,
  type View,
} from "../lib/dashboard";
import { useSnapshot } from "../hooks/useSnapshot";
import MultiSelectFilter from "./MultiSelectFilter";
import { needsArchive, snapshotRecentCount, snapshotTodayCount } from "../lib/snapshot-format";

const PAGE_SIZE = 10;
const BASE = import.meta.env.BASE_URL.replace(/\/?$/, "/");
const shortSource = (source?: Source) =>
  source?.id === "hhs" ? "HHS OCR" : source?.label || "Unknown source";
const SIZE_OPTIONS = [
  { value: "1000", label: "1,000+ reported" },
  { value: "100000", label: "100,000+ reported" },
  { value: "unknown", label: "Count not reported" },
];
const STATUS_OPTIONS = [
  { value: "updated", label: "Updated reports" },
  { value: "flagged", label: "Needs verification" },
];
const KIND_OPTIONS = [
  { value: "official", label: "Official notices and filings" },
  { value: "claims", label: "Unverified ransomware claims" },
];
const SEARCH_OPTIONS = [
  { value: "organization", label: "Organization" },
  { value: "ids", label: "Report IDs" },
  { value: "summary", label: "Summary" },
  { value: "dataTypes", label: "Data involved" },
  { value: "source", label: "Source name" },
];

function displayChangeValue(value: unknown, field: string): string {
  const formatted = changeValue(value, field);
  return field === "affected" && typeof value === "object" && value !== null
    ? formatted.replace(" · ", ", ")
    : formatted;
}

function ExternalLink({
  url,
  children,
  className = "",
}: {
  url: string | null;
  children: React.ReactNode;
  className?: string;
}) {
  const safe = safeUrl(url);
  return safe ? (
    <a
      className={className}
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ArrowUpRight size={14} aria-label="Opens in a new tab" />
    </a>
  ) : (
    <span className={`${className} unavailable`}>{children} unavailable</span>
  );
}

function HealthLabel({ source, now }: { source: Source; now: number }) {
  const health = sourceHealth(source, now);
  const HealthIcon = source.status === "disabled"
    ? Pause
    : health.label === "Stale"
      ? Clock3
      : health.tone === "good"
        ? Check
        : AlertTriangle;
  return (
    <span className={`health-label ${health.tone}`}>
      <HealthIcon size={14} aria-hidden="true" />
      {health.label}
    </span>
  );
}

function ReportBadge({ report, now }: { report: Report; now: number }) {
  if (report.signalType === "ransomware_claim")
    return <span className="report-badge claim"><AlertTriangle size={13} aria-hidden="true" />Unverified claim</span>;
  if (report.revision > 1)
    return (
      <span className="report-badge revised" role="img" aria-label={`Updated report, revision ${report.revision}`} title={`Updated report, revision ${report.revision}`}>
        <RotateCcw size={13} aria-hidden="true" />
        <span className="revision-number">{report.revision}</span>
      </span>
    );
  if (isRecent(report, now))
    return <span className="report-badge new" role="img" aria-label="Newly collected" title="Newly collected"><Plus size={13} aria-hidden="true" /></span>;
  return <span className="report-badge archived">Collected</span>;
}

function SourceAttribution({ source }: { source?: Source }) {
  const attribution = source?.attribution;
  if (!attribution) return null;
  return <p className="source-attribution">
    Data from <ExternalLink url={attribution.url}>{attribution.name}</ExternalLink>{" "}
    under <ExternalLink url={attribution.licenseUrl}>{attribution.license}</ExternalLink>.
    {" "}{attribution.changes}
  </p>;
}

function DetailPane({
  report,
  source,
  now,
  saved,
  onSave,
  onClose,
  detailRef,
}: {
  report: Report;
  source?: Source;
  now: number;
  saved: boolean;
  onSave: () => void;
  onClose: () => void;
  detailRef: React.RefObject<HTMLElement>;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  useEffect(() => setDetailsOpen(false), [report.id]);
  return (
    <aside
      className="detail-pane"
      aria-label="Report evidence"
      ref={detailRef}
      tabIndex={-1}
    >
      <div className="detail-toolbar">
        <span className="eyebrow">
          <FileText size={13} /> Report evidence
        </span>
        <div className="detail-actions">
          <button
            className={`icon-button save-detail ${saved ? "is-saved" : ""}`}
            onClick={onSave}
            aria-pressed={saved}
            aria-label={saved ? "Saved on this device" : "Save on this device"}
            title={saved ? "Saved on this device" : "Save on this device"}
          >
            <Bookmark size={16} fill={saved ? "currentColor" : "none"} aria-hidden="true" />
          </button>
          <button
            className="icon-button close-detail"
            onClick={onClose}
            aria-label="Return to reports"
          >
            <X size={17} />
          </button>
        </div>
      </div>
      <div className="detail-content">
        <div className="detail-kicker">
          <span>{shortSource(source)}</span>
          <ReportBadge report={report} now={now} />
        </div>
        <h2>{report.organization}</h2>
        <p className="detail-source">
          {source?.label || "Source not available"}
        </p>
        {report.signalType === "ransomware_claim" && <p className="detail-hint">A ransomware group’s allegation observed by RansomLook. This claim has not been independently verified.</p>}
        <SourceAttribution source={source} />
        {source && sourceHealth(source, now).tone !== "good" && (
          <div className="detail-source-health">
            <HealthLabel source={source} now={now} />
            <span>
              Last successful collection:{" "}
              {relativeTime(source.lastSuccess, now)}
            </span>
          </div>
        )}
        {report.qualityFlags.length > 0 && (
          <div className="quality-callout">
            <CircleAlert size={16} />
            <div>
              <strong>Check the source</strong>
              {report.qualityFlags.map((flag) => (
                <p key={flag.code}>{qualityMessage(flag.message)}</p>
              ))}
            </div>
          </div>
        )}
        <section className="detail-section">
          <h3>Affected people</h3>
          <div
            className={`affected-value ${report.affected.count === null ? "unknown-value" : ""}`}
          >
            {affectedCount(report.affected)}
          </div>
          <p className="scope-note">{affectedScope(report.affected).replace(" · ", ", ")}</p>
          {report.affected.scope === "state" && (
            <p className="detail-hint">
              This state count is not a nationwide total.
            </p>
          )}
          {report.affected.qualifier === "unknown" &&
            report.affected.count !== null && (
              <p className="detail-hint">
                Count bound unknown. The source does not establish whether this
                is an exact count, a minimum, or a maximum.
              </p>
            )}
        </section>
        <section className="detail-section">
          <h3>Reported timeline</h3>
          <dl className="timeline-fields">
            {report.sourceObservedAt && <div>
              <dt>Observed by source</dt>
              <dd>{formatDate(report.sourceObservedAt, { hour: "numeric", minute: "2-digit" })} UTC</dd>
            </div>}
            <div>
              <dt>Published</dt>
              <dd>{formatDate(report.publishedDate)}</dd>
            </div>
            <div>
              <dt>Reported to source</dt>
              <dd>{formatDate(report.reportedDate)}</dd>
            </div>
            <div>
              <dt>Breach began</dt>
              <dd>{formatDate(report.breachStart)}</dd>
            </div>
            {report.breachEnd && (
              <div>
                <dt>Breach ended</dt>
                <dd>{formatDate(report.breachEnd)}</dd>
              </div>
            )}
            <div>
              <dt>Discovered</dt>
              <dd>{formatDate(report.discoveryDate)}</dd>
            </div>
          </dl>
        </section>
        <section className="detail-section">
          <h3>Data involved</h3>
          {report.dataTypes.length ? (
            <ul className="data-tags">
              {report.dataTypes.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className="detail-hint">
              Not specified in the collected report.
            </p>
          )}
          {report.summary && <p className="report-summary">{report.summary}</p>}
        </section>
        <section className="detail-section original-evidence">
          <h3>Original evidence</h3>
          <ExternalLink className="evidence-link" url={report.sourceUrl}>
            <span>
              <Database size={15} />
              Source record
            </span>
          </ExternalLink>
          {report.noticeUrl && (
            <ExternalLink className="evidence-link" url={report.noticeUrl}>
              <span>
                <FileText size={15} />
                Notification document
              </span>
            </ExternalLink>
          )}
          {!report.noticeUrl && (
            <p className="detail-hint">
              No separate notification document collected.
            </p>
          )}
          <p className="evidence-caption">
            Retrieved{" "}
            {formatDate(report.evidence.retrievedAt, {
              hour: "numeric",
              minute: "2-digit",
            })}{" "}
            UTC
          </p>
        </section>
        <section className="detail-section history-section">
          <h3>
            Collection history <span>Revision {report.revision}</span>
          </h3>
          <ol className="history-list">
            {recentHistory(report).map((history, i) => (
              <li key={`${history.observedAt}-${i}`}>
                <time dateTime={history.observedAt}>
                  {formatDate(history.observedAt)}
                </time>
                <p>
                  {history.changedFields
                    .filter((field) => field !== "created")
                    .map(fieldLabel)
                    .join(", ")}
                </p>
                {history.changes?.map((change, index) => (
                  <div
                    className="history-change"
                    key={`${change.field}-${index}`}
                  >
                    <span>{displayChangeValue(change.before, change.field)}</span>
                    <ArrowDown size={11} aria-hidden="true" />
                    <strong>{displayChangeValue(change.after, change.field)}</strong>
                  </div>
                ))}
              </li>
            ))}
            <li>
              <time dateTime={report.firstSeen}>
                {formatDate(report.firstSeen)}
              </time>
              <p>First collected from this source</p>
            </li>
          </ol>
          {report.history.filter((h) =>
            h.changedFields.some((field) => field !== "created"),
          ).length > 5 && (
            <p className="detail-hint">Showing the five latest changes.</p>
          )}
          <p className="detail-hint">
            Collection dates describe when this dashboard observed the report.
          </p>
        </section>
        <button
          className="provenance-toggle"
          onClick={() => setDetailsOpen((value) => !value)}
          aria-expanded={detailsOpen}
          aria-controls="provenance"
        >
          <span>Collection details</span>
          <ChevronDown size={15} className={detailsOpen ? "rotated" : ""} />
        </button>
        {detailsOpen && (
          <dl className="provenance" id="provenance">
            <div>
              <dt>Source record ID</dt>
              <dd>{report.nativeId}</dd>
            </div>
            <div>
              <dt>Last observed</dt>
              <dd>
                {formatDate(report.lastSeen, {
                  hour: "numeric",
                  minute: "2-digit",
                })}{" "}
                UTC
              </dd>
            </div>
            <div>
              <dt>Parser version</dt>
              <dd>{report.evidence.parserVersion}</dd>
            </div>
            <div>
              <dt>Normalized record fingerprint</dt>
              <dd className="content-hash">{report.evidence.contentHash}</dd>
            </div>
          </dl>
        )}
      </div>
    </aside>
  );
}

function SourcesView({ data, now }: { data: Dataset; now: number }) {
  return (
    <div className="sources-content">
      <div className="sources-intro">
        <div>
          <h2>Know what’s current.</h2>
          <p>
            A successful collection and an empty result are different things.
            Each source reports its own outcome.
          </p>
        </div>
        <span className="neutral-note">
          <Clock3 size={14} /> Stale after 48 hours
        </span>
      </div>
      <div className="source-list">
        {data.sources.map((source) => {
          const health = sourceHealth(source, now);
          return (
            <article className="source-item" key={source.id}>
              <div className="source-item-heading">
                <Database className="source-icon" size={18} aria-hidden="true" />
                <div>
                  <h3>{source.label}</h3>
                  <span className="source-description">
                    <span>{source.jurisdiction}</span>
                    <span>{source.method}</span>
                  </span>
                </div>
                <HealthLabel source={source} now={now} />
              </div>
              <p className={`source-message ${health.tone}`}>
                {source.message || "No collection message is available."}
              </p>
              <dl className="source-facts">
                <div>
                  <dt>Last attempt</dt>
                  <dd title={source.lastAttempt || ""}>
                    {relativeTime(source.lastAttempt, now)}
                  </dd>
                </div>
                <div>
                  <dt>Last success</dt>
                  <dd title={source.lastSuccess || ""}>
                    {relativeTime(source.lastSuccess, now)}
                  </dd>
                </div>
                <div>
                  <dt>Accepted / parsed</dt>
                  <dd>
                    {source.counts.accepted.toLocaleString()}{" "}
                    <span>/ {source.counts.parsed.toLocaleString()}</span>
                  </dd>
                </div>
                <div>
                  <dt>New / changed</dt>
                  <dd>
                    {source.counts.new.toLocaleString()}{" "}
                    <span>/ {source.counts.changed.toLocaleString()}</span>
                  </dd>
                </div>
                <div>
                  <dt>Rejected</dt>
                  <dd
                    className={source.counts.rejected ? "rejected-count" : ""}
                  >
                    {source.counts.rejected.toLocaleString()}
                  </dd>
                </div>
              </dl>
              <div className="source-item-footer">
                <span>
                  {health.label === "Unreliable timestamp"
                    ? "Collection timestamps need verification."
                    : health.stale
                      ? "Last valid collection is older than 48 hours or unavailable."
                      : "Last valid collection is within 48 hours."}
                </span>
                <ExternalLink url={source.homepage}>
                  {source.id === "ransomlook" ? "RansomLook" : "Official source"}
                </ExternalLink>
              </div>
              <SourceAttribution source={source} />
            </article>
          );
        })}
      </div>
      <div className="source-footnote">
        <Info size={17} />
        <div>
          <strong>Public reports and claims, with their original context.</strong>
          <p>
            One breach can appear in more than one source. Reports are not
            automatically merged, and state counts are not added together.
            Ransomware claims are unverified. Failed collection keeps the last valid data available.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data, index, error, refreshing, lastCheckedAt, refresh, archiveStatus, archiveError, loadArchive } = useSnapshot(`${BASE}data/snapshot.json`);
  const [now, setNow] = useState(() => Date.now());
  const [localPreview, setLocalPreview] = useState(false);
  const [view, setView] = useState<View>("recent");
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [saveMessage, setSaveMessage] = useState("");
  const [exporting, setExporting] = useState(false);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const reportListRef = useRef<HTMLDivElement>(null);
  const storageKey = `${SAVED_KEY}:${BASE}:${data?.mode || "demo"}`;

  useEffect(() => {
    const tick = () => setNow(Date.now());
    const onVisibility = () => { if (document.visibilityState === "visible") tick(); };
    setLocalPreview(isLocalHostname(window.location.hostname));
    const timer = setInterval(tick, 60_000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  useEffect(() => {
    if (!data) return;
    try {
      setSaved(readSavedIds(localStorage.getItem(storageKey)));
      setStorageAvailable(true);
    } catch {
      setStorageAvailable(false);
    }
    function handleStorage(event: StorageEvent) {
      if (event.key === storageKey) setSaved(readSavedIds(event.newValue));
    }
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [data?.mode, storageKey]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (
        event.key === "/" &&
        !event.metaKey &&
        !event.ctrlKey &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) &&
        !target.isContentEditable
      ) {
        event.preventDefault();
        if (view === "sources") setView("all");
        setTimeout(() => searchRef.current?.focus(), 0);
      }
      if (event.key === "Escape" && mobileDetail && !event.defaultPrevented) {
        setMobileDetail(false);
        reportListRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, mobileDetail]);

  const archiveLoaded = !!data && archiveStatus === "loaded";
  const archiveRequired = needsArchive(view, filters);
  const waitingForArchive = !!data && archiveRequired && !archiveLoaded;
  const totalReports = index?.totalReports ?? data?.reports.length ?? 0;
  useEffect(() => {
    if (archiveRequired && data && !archiveLoaded) void loadArchive();
  }, [archiveRequired, data?.generatedAt, index?.id, loadArchive]);
  const filtered = useMemo(
    () => waitingForArchive ? [] : filterReports(data?.reports || [], view, filters, saved, now, data?.sources),
    [data, view, filters, saved, now, waitingForArchive],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const selected =
    filtered.find((report) => report.id === selectedId) || visible[0];
  const sourceMap = new Map(
    data?.sources.map((source) => [source.id, source]) || [],
  );
  const recentCount = index && !archiveLoaded ? snapshotRecentCount(index, now)
    : data?.reports.filter((report) => isRecentSignal(report, now)).length || 0;
  const todayCount = useMemo(() => index && !archiveLoaded ? snapshotTodayCount(index, now)
    : countTodayReports(data?.reports || [], now), [data, index, archiveLoaded, now]);
  // Before the archive loads this is a device bookmark count, not a matched-report count.
  const savedCount = archiveLoaded ? data?.reports.filter((report) => saved.has(report.id)).length || 0 : saved.size;
  const unhealthy =
    data?.sources.filter((source) => sourceHealth(source, now).tone !== "good")
      .length || 0;
  const filtersActive =
    filters.query !== "" ||
    filters.source !== null ||
    filters.size !== null ||
    filters.quality !== null ||
    filters.kind !== null ||
    filters.searchFields !== null;
  const officialOnly = filters.kind?.length === 1 && filters.kind[0] === "official";
  const todayOfficialPreset = view === "today" && officialOnly && !filters.query &&
    filters.source === null && filters.size === null && filters.quality === null && filters.searchFields === null;
  const snapshotStale = !!data && now - timestamp(data.generatedAt) > 2 * DAY;
  const snapshotFuture =
    !!data && timestamp(data.generatedAt) > now + 5 * 60_000;
  const todayCoverage = data?.mode === "demo" ? "Demo data" : snapshotFuture ? "Timestamp needs review" : snapshotStale ? "Stale snapshot" : unhealthy ? `${unhealthy} ${unhealthy === 1 ? "source needs" : "sources need"} attention` : "Published snapshot";
  const checkStatus = refreshing
    ? error ? "Retrying snapshot check…" : "Checking published snapshot…"
    : error
      ? data ? `Update check failed. Showing snapshot from ${formatDate(data.generatedAt, { hour: "numeric", minute: "2-digit" })} UTC.` : "Snapshot check failed."
      : lastCheckedAt ? `Last checked ${relativeTime(new Date(lastCheckedAt).toISOString(), now).toLowerCase()}.` : "Loading published snapshot…";

  async function exportSnapshot() {
    setExporting(true);
    try {
      const full = await loadArchive();
      if (!full) return;
      const href = URL.createObjectURL(new Blob([JSON.stringify(full)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = href;
      link.download = `breach-watch-${full.generatedAt.slice(0, 10)}.json`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } finally { setExporting(false); }
  }
  function updateFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(0);
    setSelectedId(null);
    setMobileDetail(false);
  }
  function changeView(next: View) {
    setView(next);
    setPage(0);
    setSelectedId(null);
    setMobileDetail(false);
  }
  function clearFilters() {
    setFilters(INITIAL_FILTERS);
    setPage(0);
    setSelectedId(null);
    setMobileDetail(false);
  }
  function toggleSave(report: Report) {
    const next = new Set(saved);
    const wasSaved = next.has(report.id);
    if (wasSaved) next.delete(report.id);
    else next.add(report.id);
    setSaved(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...next]));
      setStorageAvailable(true);
      setSaveMessage(
        wasSaved
          ? `${report.organization} removed from saved reports.`
          : `${report.organization} saved on this device.`,
      );
    } catch {
      setStorageAvailable(false);
      setSaveMessage(
        "Browser storage is unavailable. This bookmark lasts only for this session.",
      );
    }
  }
  function openReport(report: Report) {
    setSelectedId(report.id);
    setMobileDetail(true);
    if (window.matchMedia("(max-width: 1000px)").matches)
      setTimeout(() => {
        detailRef.current?.focus();
        detailRef.current?.scrollIntoView({
          behavior: "instant",
          block: "start",
        });
      }, 0);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href={BASE} aria-label="Breach Watch home">
          <FileText className="brand-icon" size={22} aria-hidden="true" />
          <span>Breach Watch</span>
        </a>
        <div className="header-context">
          {localPreview && <span className="environment-label">Local preview</span>}
          <div className="header-feed">
            <button
              className={`today-counter ${view === "today" ? "active" : ""}`}
              disabled={!data}
              aria-pressed={view === "today"}
              aria-label={data ? `${data.mode === "demo" ? "Demo " : ""}Reports and claims today: ${todayCount}. View source signals dated ${utcDay(now)} UTC.` : "Reports and claims today: waiting for the published snapshot"}
              aria-describedby="today-explanation"
              title={`Reports published or reported today UTC, and claims observed by their source today. Claims are unverified; related records count separately. ${todayCoverage}.`}
              onClick={() => { setFilters(INITIAL_FILTERS); changeView("today"); }}
            >
              <CalendarDays size={17} aria-hidden="true" />
              <span className="today-labels"><span>Reports &amp; claims today</span><span className="today-coverage">{data ? todayCoverage : "Awaiting snapshot"}</span></span>
              <strong className="today-count">{data ? todayCount.toLocaleString("en-US") : "—"}</strong>
            </button>
            <button className={`icon-button snapshot-refresh ${refreshing ? "is-refreshing" : ""}`} onClick={() => void refresh()} disabled={refreshing} aria-label="Refresh snapshot" title={refreshing ? "Checking for a published snapshot" : "Refresh the published snapshot"} aria-busy={refreshing}>
              <RefreshCw size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>
      <main id="main-content" className="main-content">
        <p className="sr-only" id="today-explanation">Counts reports published today UTC, with reported date as fallback, and unverified claims observed by their source today. Related records count separately. This is not a count of confirmed breaches or occurrence dates. A zero may reflect incomplete or delayed collection. Published snapshots are checked every five minutes while this page is visible.</p>
        <div className={`snapshot-update-bar ${error ? "update-error" : ""}`}>
          <span>Auto-refresh every 5 min (UTC)</span>
          <span id="snapshot-check-status" role="status" aria-live="polite" title={error || (lastCheckedAt ? new Date(lastCheckedAt).toISOString() : undefined)}>{checkStatus}</span>
        </div>
        {!data ? (
          <div className="load-state" role={error ? "alert" : "status"}>
            <div className="loading-mark">
              {error ? <CircleAlert size={27} /> : <FolderSearch size={27} />}
            </div>
            <h1>
              {error ? "Reports are unavailable" : "Opening your workspace"}
            </h1>
            <p>
              {error ||
                "Loading the latest collection snapshot and source evidence…"}
            </p>
            {error && (
              <button
                className="primary-button"
                onClick={() => void refresh()}
                disabled={refreshing}
              >
                {refreshing ? "Retrying…" : "Try again"}
              </button>
            )}
          </div>
        ) : (
          <>
            {data.mode === "demo" && (
              <div className="mode-banner">
                <span className="demo-tag">DEMO DATA</span>
                <p>
                  Illustrative reports for evaluating this local pilot. Not for
                  case assessment.
                </p>
                <span className="mode-banner-note">No live connection</span>
              </div>
            )}
            {data.mode === "live" && (
              <div className="live-banner">
                <Database size={14} aria-hidden="true" />
                Public reports and claims{" "}
                <span>Snapshot only. Verify original sources before use.</span>
              </div>
            )}
            <div className="page-heading">
              <div>
                <h1>Breach reports</h1>
                <p>Recent disclosures and claims. Follow the evidence.</p>
              </div>
              <div className="snapshot-stamp">
                <span>Collection snapshot</span>
                <strong>
                  {formatDate(data.generatedAt, { month: "long" })}
                </strong>
                <span>
                  {
                    formatDate(data.generatedAt, {
                      hour: "numeric",
                      minute: "2-digit",
                    })
                      .split(", ")
                      .slice(-1)[0]
                  }{" "}
                  UTC
                </span>
              </div>
            </div>
            <nav className="view-tabs" aria-label="Report views">
              {(
                [
                  { id: "recent", label: "Latest", count: recentCount },
                  { id: "today", label: "Today · official only", count: undefined },
                  {
                    id: "all",
                    label: "All history",
                    count: totalReports,
                  },
                  { id: "saved", label: "Saved", count: savedCount },
                  {
                    id: "sources",
                    label: "Sources",
                    count: data.sources.length,
                  },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  className={`${view === tab.id && (tab.id !== "today" || officialOnly) ? "active" : ""} ${tab.id === "saved" || tab.id === "sources" ? "icon-tab" : ""}`}
                  aria-current={view === tab.id && (tab.id !== "today" || officialOnly) ? "page" : undefined}
                  aria-label={`${tab.label}${tab.count === undefined ? "" : ` ${tab.count}`}`}
                  title={tab.id === "saved" ? archiveLoaded ? "Saved reports present in this snapshot" : "Bookmarks on this device; load Saved to check the full archive" : tab.label}
                  onClick={() => { if (tab.id === "today") setFilters(todayOfficialFilters()); changeView(tab.id); }}
                >
                  {tab.id === "saved" && <Bookmark size={16} aria-hidden="true" />}
                  {tab.id === "sources" && <Activity size={16} aria-hidden="true" />}
                  {tab.id !== "saved" && tab.id !== "sources" && tab.label}
                  {tab.count !== undefined && <span
                    className={`tab-count ${tab.id === "sources" && unhealthy ? "attention-count" : ""}`}
                  >
                    {tab.count}
                  </span>}
                </button>
              ))}
            </nav>
            <div
              className={`freshness-strip ${snapshotStale || snapshotFuture ? "snapshot-stale" : ""}`}
            >
              <span>
                <Clock3 size={13} />
                {snapshotFuture
                  ? "Snapshot timestamp is in the future"
                  : snapshotStale
                    ? "Snapshot is stale"
                    : `Snapshot generated ${relativeTime(data.generatedAt, now)}`}
                {view === "recent" && (
                  <span className="freshness-context">
                    Showing the last 7 days
                  </span>
                )}
                {view === "today" && (
                  <span className="freshness-context">Source signals dated {formatDate(utcDay(now))} UTC</span>
                )}
                {view === "saved" && (
                  <span className="freshness-context">
                    Saved on this device
                  </span>
                )}
              </span>
              <button
                onClick={() => changeView("sources")}
                className={unhealthy ? "attention-link" : "healthy-link"}
              >
                {unhealthy ? <CircleAlert size={13} /> : <Check size={13} />}
                {unhealthy
                  ? `${unhealthy} ${unhealthy === 1 ? "source needs" : "sources need"} attention`
                  : "All sources current"}
                <ChevronRight size={13} />
              </button>
            </div>
            <div className={`snapshot-update-bar archive-bar ${archiveError ? "update-error" : ""}`}>
              <span className="archive-status" role="status" aria-live="polite">
                {archiveLoaded
                  ? `Full archive loaded · ${totalReports.toLocaleString()} reports.`
                  : `${data.reports.length.toLocaleString()} of ${totalReports.toLocaleString()} reports loaded. Report totals include the full archive.`}
                {archiveStatus === "loading" && " Loading the full archive…"}
                {archiveError && ` Archive unavailable: ${archiveError}`}
              </span>
              <div className="archive-actions">
                {!archiveLoaded && <button className="secondary-button" disabled={archiveStatus === "loading" || refreshing} onClick={() => void loadArchive()}>
                  {archiveStatus === "loading" ? "Loading archive…" : archiveError || archiveStatus === "error" ? "Retry full archive" : "Load full archive"}
                </button>}
                <button className="icon-button" disabled={exporting || refreshing || archiveStatus === "loading"} onClick={() => void exportSnapshot()} aria-label={exporting ? "Preparing full snapshot download" : "Download full snapshot"} title={exporting ? "Preparing download…" : "Download full snapshot"}>
                  <Download size={18} aria-hidden="true" />
                </button>
              </div>
            </div>
            {view === "sources" ? (
              <SourcesView data={data} now={now} />
            ) : (
              <>
                <div className="filter-bar">
                  <div className="search-box">
                    <Search size={17} />
                    <input
                      ref={searchRef}
                      aria-label="Search reports in selected fields"
                      placeholder="Search reports…"
                      value={filters.query}
                      onChange={(event) =>
                        updateFilter("query", event.target.value)
                      }
                    />
                    {filters.query ? (
                      <button
                        className="icon-button"
                        aria-label="Clear search"
                        onClick={() => updateFilter("query", "")}
                      >
                        <X size={14} />
                      </button>
                    ) : (
                      <kbd aria-hidden="true">/</kbd>
                    )}
                  </div>
                  <MultiSelectFilter label="Search in" allLabel="All search fields" options={SEARCH_OPTIONS}
                    value={filters.searchFields} onChange={value => updateFilter("searchFields", value as Filters["searchFields"])} />
                  <div className="filter-selects">
                    <MultiSelectFilter label="Sources" allLabel="All sources" searchable
                      options={data.sources.map(source => ({ value: source.id, label: shortSource(source) }))}
                      value={filters.source} onChange={value => updateFilter("source", value)} />
                    <MultiSelectFilter label="Report type" allLabel="All report types" options={KIND_OPTIONS}
                      value={filters.kind} onChange={value => updateFilter("kind", value as Filters["kind"])} />
                    <MultiSelectFilter label="Affected count" allLabel="Any affected count" options={SIZE_OPTIONS}
                      value={filters.size} onChange={value => updateFilter("size", value)} />
                    <MultiSelectFilter label="Status" allLabel="Any status" options={STATUS_OPTIONS}
                      value={filters.quality} onChange={value => updateFilter("quality", value)} />
                  </div>
                </div>
                <div className="result-toolbar">
                  <p role="status" aria-live="polite">
                    {waitingForArchive ? "Results require the full archive" : <><strong>{filtered.length.toLocaleString()}</strong> {archiveLoaded ? "source" : "loaded"}{" "}
                    {filtered.length === 1 ? "report" : "reports"}</>}
                    {filtersActive && (
                      <button className="reset-filters" onClick={clearFilters}>
                        Reset filters
                        <X size={12} />
                      </button>
                    )}
                  </p>
                  <label className="sort-select">
                    <ArrowDown size={12} />
                    <span className="sr-only">Sort reports</span>
                    <select
                      aria-label="Sort reports"
                      value={filters.sort}
                      onChange={(event) =>
                        updateFilter("sort", event.target.value)
                      }
                    >
                      <option value="latest">Latest source date</option>
                      <option value="affected">Largest reported count</option>
                      <option value="organization">Organization A–Z</option>
                    </select>
                    <ChevronDown size={12} />
                  </label>
                </div>
                {view === "recent" && (
                  <p className="queue-note"><Info size={13} />Last 7 days by source observation, publication, or reported date. Older and undated records remain in All history.</p>
                )}
                {view === "today" && (
                  <p className="queue-note"><CalendarDays size={13} />{officialOnly
                    ? `Official-source notices and filings published or reported today (${formatDate(utcDay(now))}, UTC). Ransomware claims are excluded; related reports count separately.`
                    : `Reports published or reported today and claims observed by their source today (${formatDate(utcDay(now))}, UTC). Claims are unverified and related records count separately.`}</p>
                )}
                {view === "saved" && (
                  <div className="saved-note">
                    <Bookmark size={14} />
                    <span>
                      Saved on this device. Bookmarks contain report IDs only
                      and do not sync.
                      {archiveLoaded && saved.size > savedCount && ` ${saved.size - savedCount} saved IDs are not present in this snapshot; their bookmarks are retained.`}
                    </span>
                    {!storageAvailable && (
                      <strong>Storage unavailable — this session only.</strong>
                    )}
                  </div>
                )}
                <div
                  className={`review-layout ${mobileDetail && selected ? "show-mobile-detail" : ""} ${!selected ? "no-selection" : ""}`}
                >
                  <div
                    className="report-list"
                    ref={reportListRef}
                    tabIndex={-1}
                    aria-label="Report list"
                  >
                    {waitingForArchive || (!archiveLoaded && !filtered.length && recentCount > 0) ? (
                      <div className="empty-state" role="status">
                        <FolderSearch size={31} strokeWidth={1.2} />
                        <h2>{archiveStatus === "loading" ? "Loading the full archive" : "Full archive needed"}</h2>
                        <p>{archiveError || "Load the full archive to search all reports."}</p>
                        <button className="secondary-button" disabled={archiveStatus === "loading" || refreshing} onClick={() => void loadArchive()}>
                          {archiveStatus === "loading" ? "Loading…" : "Load full archive"}
                        </button>
                      </div>
                    ) : filtered.length ? (
                      <>
                        <table className="reports-table">
                          <caption className="sr-only">
                            Public source reports. Select an organization to
                            inspect its evidence.
                          </caption>
                          <thead>
                            <tr>
                              <th scope="col">Organization / report</th>
                              <th scope="col" className="source-column">
                                Source
                              </th>
                              <th scope="col">
                                Affected people
                                <Info size={12}>
                                  <title>
                                    Counts retain their reported geographic
                                    scope.
                                  </title>
                                </Info>
                              </th>
                              <th scope="col" className="observed-column">
                                Collected
                              </th>
                              <th scope="col" className="bookmark-column">
                                <span className="sr-only">Save report</span>
                                <Bookmark size={13} aria-hidden="true" />
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {visible.map((report) => (
                              <tr
                                key={report.id}
                                className={`${selected?.id === report.id ? "selected-row" : ""} ${report.qualityFlags.length ? "has-flag" : ""}`}
                                onClick={() => openReport(report)}
                              >
                                <td className="organization-cell">
                                  <button
                                    className="organization-button"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      openReport(report);
                                    }}
                                    aria-label={`View evidence for ${report.organization}`}
                                    aria-pressed={selected?.id === report.id}
                                  >
                                    {report.organization}
                                  </button>
                                  <div className="report-meta">
                                    <ReportBadge report={report} now={now} />
                                    <span className="published-text" title={reportDateLabel(report, now)}>
                                      {reportDateLabel(report, now)}
                                    </span>
                                    {report.qualityFlags.length > 0 && (
                                      <span
                                        className="row-warning"
                                        title="Source details need verification"
                                        aria-label="Source details need verification"
                                      >
                                        <CircleAlert size={12} />
                                      </span>
                                    )}
                                    <span className="mobile-source">
                                      {shortSource(
                                        sourceMap.get(report.sourceId),
                                      )}
                                    </span>
                                  </div>
                                </td>
                                <td className="source-column">
                                  <span className="source-short">
                                    {shortSource(
                                      sourceMap.get(report.sourceId),
                                    )}
                                  </span>
                                  <span className="cell-subtext">
                                    {sourceKind(report.sourceId)}
                                  </span>
                                </td>
                                <td className="count-cell">
                                  <span
                                    className={
                                      report.affected.count === null
                                        ? "unknown-count"
                                        : "count-number"
                                    }
                                  >
                                    {affectedCount(report.affected)}
                                  </span>
                                  <span className="cell-subtext">
                                    {affectedScope(report.affected).replace(" · ", ", ")}
                                    {report.affected.count !== null && report.affected.qualifier === "unknown" && ", bound unknown"}
                                  </span>
                                </td>
                                <td className="observed-column">
                                  <time
                                    dateTime={report.lastChanged}
                                    title={formatDate(report.lastChanged, {
                                      hour: "numeric",
                                      minute: "2-digit",
                                    })}
                                  >
                                    {relativeTime(report.lastChanged, now)}
                                  </time>
                                  <span className="cell-subtext">
                                    {report.revision > 1
                                      ? "Changed"
                                      : "First seen"}
                                  </span>
                                </td>
                                <td className="bookmark-column">
                                  <button
                                    className={`icon-button bookmark-button ${saved.has(report.id) ? "is-saved" : ""}`}
                                    aria-label={`${saved.has(report.id) ? "Unsave" : "Save"} ${report.organization} on this device`}
                                    aria-pressed={saved.has(report.id)}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      toggleSave(report);
                                    }}
                                  >
                                    <Bookmark
                                      size={16}
                                      fill={
                                        saved.has(report.id)
                                          ? "currentColor"
                                          : "none"
                                      }
                                    />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="table-footer">
                          <span>
                            {currentPage * PAGE_SIZE + 1}–
                            {Math.min(
                              (currentPage + 1) * PAGE_SIZE,
                              filtered.length,
                            )}{" "}
                            of {filtered.length} {archiveLoaded ? "reports" : "loaded reports"}
                          </span>
                          <div className="pagination">
                            <button
                              className="icon-button"
                              disabled={currentPage === 0}
                              aria-label="Previous page"
                              onClick={() => {
                                setPage(currentPage - 1);
                                setSelectedId(null);
                              }}
                            >
                              <ChevronLeft size={16} />
                            </button>
                            <span>
                              {currentPage + 1} / {pageCount}
                            </span>
                            <button
                              className="icon-button"
                              disabled={currentPage + 1 === pageCount}
                              aria-label="Next page"
                              onClick={() => {
                                setPage(currentPage + 1);
                                setSelectedId(null);
                              }}
                            >
                              <ChevronRight size={16} />
                            </button>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="empty-state">
                        <FolderSearch size={31} strokeWidth={1.2} />
                        <h2>
                          {todayOfficialPreset
                            ? "No official reports dated today"
                            : filtersActive
                            ? "No reports match these filters"
                            : view === "saved"
                              ? "Keep a report within reach"
                              : view === "today"
                                ? "No reports or claims dated today"
                              : view === "recent"
                                ? "No recent reports or claims"
                                : "No reports collected yet"}
                        </h2>
                        <p>
                          {todayOfficialPreset
                            ? "This snapshot has no official-source notices or filings published or reported today UTC. Collection can lag or be incomplete. Recent official reports are still available."
                            : filtersActive
                            ? "Try a broader search or reset your filters. Unknown counts are included when “Any affected count” is selected."
                            : view === "saved"
                              ? "Use the bookmark beside any report to return to it here. Your saved list stays on this device."
                              : view === "today"
                                ? "This snapshot has no reports published or reported today UTC, or claims observed today. Collection can lag or be incomplete. Check source health for coverage."
                              : view === "recent"
                                ? "No source observation, publication, or reported dates fall within the last seven days. All history keeps older and undated records. Check Sources for collection status."
                                : "Reports will appear after the next successful collection. Check Sources for the current collection status."}
                        </p>
                        <button
                          className="secondary-button"
                          onClick={() =>
                            todayOfficialPreset
                              ? changeView("recent")
                              : filtersActive
                              ? clearFilters()
                              : changeView(
                                  view === "saved" || view === "recent"
                                    ? "all"
                                    : "sources",
                                )
                          }
                        >
                          {todayOfficialPreset
                            ? "View recent official reports"
                            : filtersActive
                            ? "Reset filters"
                            : view === "saved" || view === "recent"
                              ? "Browse all reports"
                              : "Check sources"}
                          <ArrowUpRight size={14} />
                        </button>
                      </div>
                    )}
                    <p className="table-context">
                      <Info size={13} />
                      Each row is a source report or an unverified claim. Related records may describe the same incident.
                    </p>
                  </div>
                  {selected && (
                    <DetailPane
                      key={selected.id}
                      report={selected}
                      source={sourceMap.get(selected.sourceId)}
                      now={now}
                      saved={saved.has(selected.id)}
                      onSave={() => toggleSave(selected)}
                      onClose={() => {
                        setMobileDetail(false);
                        reportListRef.current?.focus();
                      }}
                      detailRef={detailRef}
                    />
                  )}
                </div>
              </>
            )}
            <footer className="page-footer">
              <div className="feed-links">
                <a href={`${BASE}data/recent.xml`} title="Subscribe to recent reports and claims"><Rss size={14} aria-hidden="true" />RSS</a>
                <a href="https://github.com/BD4L/breach-dashboard-v2/tree/main/agent" target="_blank" rel="noopener noreferrer" title="Connect a local agent with MCP"><Plug size={14} aria-hidden="true" />Connect an agent</a>
              </div>
              <span>Dates shown in UTC</span>
            </footer>
          </>
        )}
      </main>
      <div className="sr-only" role="status" aria-live="polite">
        {saveMessage}
      </div>
    </div>
  );
}
