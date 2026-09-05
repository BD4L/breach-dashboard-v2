import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  AlertCircle as CircleAlert,
  Clock3,
  Database,
  FileText,
  FolderSearch,
  Info,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  affectedCount,
  affectedScope,
  changeValue,
  DAY,
  fieldLabel,
  filterReports,
  formatDate,
  INITIAL_FILTERS,
  isRecent,
  qualityMessage,
  readDataset,
  readSavedIds,
  recentHistory,
  reportDateLabel,
  relativeTime,
  safeUrl,
  SAVED_KEY,
  sourceHealth,
  timestamp,
  type Dataset,
  type Filters,
  type Report,
  type Source,
  type View,
} from "../lib/dashboard";

const PAGE_SIZE = 10;
const BASE = import.meta.env.BASE_URL.replace(/\/?$/, "/");
const shortSource = (source?: Source) =>
  source?.id === "hhs" ? "HHS · OCR" : source?.label || "Unknown source";

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
  return (
    <span className={`health-label ${health.tone}`}>
      <span className="status-dot" />
      {health.label}
    </span>
  );
}

function ReportBadge({ report, now }: { report: Report; now: number }) {
  if (report.revision > 1)
    return (
      <span className="report-badge revised">
        Updated <span className="revision-number">· {report.revision}</span>
      </span>
    );
  if (isRecent(report, now))
    return <span className="report-badge new">New</span>;
  return <span className="report-badge archived">Collected</span>;
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
        <button
          className="icon-button close-detail"
          onClick={onClose}
          aria-label="Return to reports"
        >
          <X size={17} />
        </button>
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
        {source && sourceHealth(source, now).tone !== "good" && (
          <div className="detail-source-health">
            <HealthLabel source={source} now={now} />
            <span>
              Last successful collection:{" "}
              {relativeTime(source.lastSuccess, now)}
            </span>
          </div>
        )}
        <button
          className={`save-detail ${saved ? "is-saved" : ""}`}
          onClick={onSave}
          aria-pressed={saved}
        >
          <Bookmark size={14} fill={saved ? "currentColor" : "none"} />
          {saved ? "Saved on this device" : "Save on this device"}
          {saved && <Check size={13} />}
        </button>
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
          <p className="scope-note">{affectedScope(report.affected)}</p>
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
                <span className="history-point" />
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
                    <span>{changeValue(change.before, change.field)}</span>
                    <ArrowDown size={11} />
                    <strong>{changeValue(change.after, change.field)}</strong>
                  </div>
                ))}
              </li>
            ))}
            <li>
              <span className="history-point initial" />
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
                <div className="source-monogram" aria-hidden="true">
                  {source.id === "hhs"
                    ? "US"
                    : source.jurisdiction === "Massachusetts"
                      ? "MA"
                      : source.jurisdiction === "California"
                        ? "CA"
                        : source.jurisdiction.slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <h3>{source.label}</h3>
                  <span>
                    {source.jurisdiction}{" "}
                    <span className="separator-dot">·</span> {source.method}
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
                  Official source
                </ExternalLink>
              </div>
            </article>
          );
        })}
      </div>
      <div className="source-footnote">
        <Info size={17} />
        <div>
          <strong>Public source reports, with their original context.</strong>
          <p>
            One breach can appear in more than one source. Reports are not
            automatically merged, and state counts are not added together.
            Failed collection keeps the last valid data available.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [view, setView] = useState<View>("recent");
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [saveMessage, setSaveMessage] = useState("");
  const [storageAvailable, setStorageAvailable] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const reportListRef = useRef<HTMLDivElement>(null);
  const storageKey = `${SAVED_KEY}:${BASE}:${data?.mode || "demo"}`;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => controller.abort(), 15_000);
    setError("");
    fetch(`${BASE}data/dashboard.json`, {
      signal: controller.signal,
      cache: "no-cache",
    })
      .then((response) => {
        if (!response.ok)
          throw new Error(
            `The dashboard export could not be loaded (${response.status}).`,
          );
        return response.json();
      })
      .then((value) => {
        if (active) setData(readDataset(value));
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error && reason.name !== "AbortError"
              ? reason.message
              : "The dashboard export took too long to load. Try again.",
          );
      })
      .finally(() => clearTimeout(timer));
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [reload]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
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
      if (event.key === "Escape" && mobileDetail) {
        setMobileDetail(false);
        reportListRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, mobileDetail]);

  const filtered = useMemo(
    () => filterReports(data?.reports || [], view, filters, saved, now),
    [data, view, filters, saved, now],
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
  const recentCount =
    data?.reports.filter((report) => isRecent(report, now)).length || 0;
  const savedCount =
    data?.reports.filter((report) => saved.has(report.id)).length || 0;
  const unhealthy =
    data?.sources.filter((source) => sourceHealth(source, now).tone !== "good")
      .length || 0;
  const filtersActive =
    filters.query !== "" ||
    filters.source !== "all" ||
    filters.size !== "all" ||
    filters.quality !== "all";
  const snapshotStale = !!data && now - timestamp(data.generatedAt) > 2 * DAY;
  const snapshotFuture =
    !!data && timestamp(data.generatedAt) > now + 5 * 60_000;

  function updateFilter(key: keyof Filters, value: string) {
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
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>
            Breach Watch
            <span className="brand-divider" />
            <small>Public notification monitor</small>
          </span>
        </a>
        <div className="header-context">
          <span className="workspace-dot" />
          Research workspace
          <span className="environment-label">LOCAL PREVIEW</span>
        </div>
      </header>
      <main id="main-content" className="main-content">
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
                onClick={() => setReload((n) => n + 1)}
              >
                Try again
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
                <span className="status-dot" />
                Collected public reports{" "}
                <span>Snapshot only · verify original sources before use</span>
              </div>
            )}
            <div className="page-heading">
              <div>
                <div className="eyebrow">The research desk</div>
                <h1>Breach reports</h1>
                <p>Find what changed. Follow the evidence.</p>
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
                  { id: "recent", label: "New & updated", count: recentCount },
                  {
                    id: "all",
                    label: "All reports",
                    count: data.reports.length,
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
                  className={view === tab.id ? "active" : ""}
                  aria-current={view === tab.id ? "page" : undefined}
                  onClick={() => changeView(tab.id)}
                >
                  {tab.id === "saved" && <Bookmark size={14} />}
                  {tab.id === "sources" && <Activity size={14} />}
                  {tab.label}
                  <span
                    className={`tab-count ${tab.id === "sources" && unhealthy ? "attention-count" : ""}`}
                  >
                    {tab.count}
                  </span>
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
                    · Showing the last 7 days
                  </span>
                )}
                {view === "saved" && (
                  <span className="freshness-context">
                    · Saved on this device
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
            {view === "sources" ? (
              <SourcesView data={data} now={now} />
            ) : (
              <>
                <div className="filter-bar">
                  <div className="search-box">
                    <Search size={17} />
                    <input
                      ref={searchRef}
                      aria-label="Search organizations, report IDs, or data types"
                      placeholder="Search organizations, report IDs, data…"
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
                  <div className="filter-selects">
                    <label>
                      <span className="sr-only">Source</span>
                      <select
                        aria-label="Filter by source"
                        value={filters.source}
                        onChange={(event) =>
                          updateFilter("source", event.target.value)
                        }
                      >
                        <option value="all">All sources</option>
                        {data.sources.map((source) => (
                          <option key={source.id} value={source.id}>
                            {shortSource(source)}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={13} />
                    </label>
                    <label>
                      <span className="sr-only">Affected count</span>
                      <select
                        aria-label="Filter by affected count"
                        value={filters.size}
                        onChange={(event) =>
                          updateFilter("size", event.target.value)
                        }
                      >
                        <option value="all">Any affected count</option>
                        <option value="1000">1,000+ reported</option>
                        <option value="100000">100,000+ reported</option>
                        <option value="unknown">Count not reported</option>
                      </select>
                      <ChevronDown size={13} />
                    </label>
                    <label className="quality-select">
                      <SlidersHorizontal size={14} />
                      <span className="sr-only">Report status</span>
                      <select
                        aria-label="Filter by report status"
                        value={filters.quality}
                        onChange={(event) =>
                          updateFilter("quality", event.target.value)
                        }
                      >
                        <option value="all">Any status</option>
                        <option value="updated">Updated reports</option>
                        <option value="flagged">Needs verification</option>
                      </select>
                      <ChevronDown size={13} />
                    </label>
                  </div>
                </div>
                <div className="result-toolbar">
                  <p role="status" aria-live="polite">
                    <strong>{filtered.length.toLocaleString()}</strong> source{" "}
                    {filtered.length === 1 ? "report" : "reports"}
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
                      <option value="latest">Latest collection change</option>
                      <option value="affected">Largest reported count</option>
                      <option value="organization">Organization A–Z</option>
                    </select>
                    <ChevronDown size={12} />
                  </label>
                </div>
                {view === "recent" && (
                  <p className="queue-note"><Info size={13} />New means newly collected here. A first collection can include older reports.</p>
                )}
                {view === "saved" && (
                  <div className="saved-note">
                    <Bookmark size={14} />
                    <span>
                      Saved on this device. Bookmarks contain report IDs only
                      and do not sync.
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
                    {filtered.length ? (
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
                                Observed
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
                                    <span className="published-text">
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
                                  </div>
                                  <span className="mobile-source">
                                    {shortSource(
                                      sourceMap.get(report.sourceId),
                                    )}
                                  </span>
                                </td>
                                <td className="source-column">
                                  <span className="source-short">
                                    {shortSource(
                                      sourceMap.get(report.sourceId),
                                    )}
                                  </span>
                                  <span className="cell-subtext">
                                    {report.sourceId === "hhs"
                                      ? "Federal portal"
                                      : "State register"}
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
                                    {affectedScope(report.affected)}
                                    {report.affected.count !== null && report.affected.qualifier === "unknown" && " · Bound unknown"}
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
                            of {filtered.length} reports
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
                          {filtersActive
                            ? "No reports match these filters"
                            : view === "saved"
                              ? "Keep a report within reach"
                              : view === "recent"
                                ? "No new or changed reports"
                                : "No reports collected yet"}
                        </h2>
                        <p>
                          {filtersActive
                            ? "Try a broader search or reset your filters. Unknown counts are included when “Any affected count” is selected."
                            : view === "saved"
                              ? "Use the bookmark beside any report to return to it here. Your saved list stays on this device."
                              : view === "recent"
                                ? "Nothing was first collected or revised in the last seven days. Check source health to confirm collection is current."
                                : "Reports will appear after the next successful collection. Check Sources for the current collection status."}
                        </p>
                        <button
                          className="secondary-button"
                          onClick={() =>
                            filtersActive
                              ? clearFilters()
                              : changeView(
                                  view === "saved" || view === "recent"
                                    ? "all"
                                    : "sources",
                                )
                          }
                        >
                          {filtersActive
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
                      Each row is a source report. Related reports may describe
                      the same breach.
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
              <span>
                <span className="footer-brand">Breach Watch</span> · Public
                notification research
              </span>
              <span>Source evidence first. All dates shown in UTC.</span>
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
