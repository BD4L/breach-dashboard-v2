import test from "node:test";
import assert from "node:assert/strict";
import {
  affectedCount,
  countTodayReports,
  filterReports,
  freshInitialFilters,
  INITIAL_FILTERS,
  isRecent,
  isRecentSignal,
  isLocalHostname,
  isReportFromToday,
  qualityMessage,
  readDataset,
  readSavedIds,
  recentHistory,
  reportDateLabel,
  safeUrl,
  sourceHealth,
  sourceKind,
  signalTime,
  todayOfficialFilters,
  utcDay,
  type Dataset,
  type Filters,
  type Report,
  type Source,
} from "../src/lib/dashboard.ts";

const now = Date.parse("2026-09-05T18:00:00Z");
const source: Source = {
  id: "ma",
  label: "Massachusetts",
  jurisdiction: "MA",
  method: "Annual report",
  homepage: "https://www.mass.gov/",
  status: "healthy",
  lastAttempt: "2026-09-05T17:00:00Z",
  lastSuccess: "2026-09-05T17:00:00Z",
  message: "",
  counts: { parsed: 1, accepted: 1, rejected: 0, new: 1, changed: 0 },
};
function report(overrides: Partial<Report> = {}): Report {
  return {
    id: "one",
    sourceId: "ma",
    nativeId: "1",
    organization: "Example Organization",
    publishedDate: null,
    reportedDate: null,
    breachStart: null,
    breachEnd: null,
    discoveryDate: null,
    firstSeen: "2026-09-05T17:00:00Z",
    lastSeen: "2026-09-05T17:00:00Z",
    lastChanged: "2026-09-05T17:00:00Z",
    revision: 1,
    affected: {
      count: null,
      scope: "unknown",
      jurisdiction: null,
      qualifier: "unknown",
    },
    dataTypes: [],
    sourceUrl: source.homepage,
    noticeUrl: null,
    summary: "",
    qualityFlags: [],
    evidence: {
      retrievedAt: "2026-09-05T17:00:00Z",
      contentHash: "abc",
      parserVersion: "1",
    },
    history: [],
    ...overrides,
  };
}
function dataset(reports = [report()]): Dataset {
  return {
    schemaVersion: 1,
    mode: "demo",
    generatedAt: "2026-09-05T18:00:00Z",
    sources: [source],
    reports,
  };
}

test("undated reports remain in history without looking fresh; recent unknown counts stay visible", () => {
  assert.equal(
    filterReports([report()], "recent", INITIAL_FILTERS, new Set(), now).length,
    0,
  );
  assert.equal(
    filterReports([report()], "all", INITIAL_FILTERS, new Set(), now).length,
    1,
  );
  assert.equal(filterReports([report({ reportedDate: "2026-09-05" })], "recent", INITIAL_FILTERS, new Set(), now).length, 1);
});

test("Latest follows source time, never a new import or revision of an old disclosure", () => {
  const old = report({ publishedDate: "2020-01-01", revision: 2 });
  assert.equal(isRecent(old, now), true, "collection recency remains separate");
  assert.equal(isRecentSignal(old, now), false);
  assert.equal(isRecentSignal(report({ publishedDate: "2026-09-05", firstSeen: "2025-01-01T00:00:00Z", lastChanged: "2025-01-01T00:00:00Z" }), now), true);
  assert.equal(isRecentSignal(report({ publishedDate: "2029-01-01", reportedDate: "2026-09-05" }), now), false);
  assert.equal(filterReports([old], "recent", INITIAL_FILTERS, new Set(), now).length, 0);
});

test("claim freshness uses the source observation timestamp with exact seven-day boundaries", () => {
  const claim = report({ sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-08-29T18:00:00Z", publishedDate: "2026-09-05" });
  assert.equal(signalTime(claim), Date.parse("2026-08-29T18:00:00Z"));
  assert.equal(isRecentSignal(claim, now), true);
  assert.equal(isRecentSignal({ ...claim, sourceObservedAt: "2026-08-29T17:59:59Z" }, now), false);
  assert.equal(isRecentSignal({ ...claim, sourceObservedAt: "2026-09-05T18:00:01Z" }, now), false);
  assert.equal(isReportFromToday({ ...claim, sourceObservedAt: "2026-09-04T23:30:00-01:00", publishedDate: "2020-01-01" }, now), true);
  assert.equal(isReportFromToday({ ...claim, sourceObservedAt: "2026-09-05T18:00:01Z" }, now), false);
});

test("the claim filter and source labels distinguish allegations from official reports", () => {
  const claim = report({ id: "claim", sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-09-05T17:00:00Z" });
  const disclosure = report({ id: "disclosure", sourceId: "sec", publishedDate: "2026-09-05" });
  assert.deepEqual(filterReports([disclosure, claim], "recent", { ...INITIAL_FILTERS, kind: ["claims"] }, new Set(), now).map(r => r.id), ["claim"]);
  assert.equal(sourceKind("ransomlook"), "Ransomware claims");
  assert.equal(sourceKind("sec"), "SEC filings");
  assert.equal(sourceKind("hhs"), "Federal portal");
  assert.equal(sourceKind("ma"), "State register");
  assert.equal(reportDateLabel(claim, now), "Observed Sep 5");
});

test("today counts source notification dates and excludes historical imports", () => {
  const rows = [
    report({ id: "published", publishedDate: "2026-09-05" }),
    report({ id: "reported", reportedDate: "2026-09-05" }),
    report({ id: "historical", publishedDate: "2020-01-01", firstSeen: "2026-09-05T17:00:00Z", lastChanged: "2026-09-05T17:00:00Z" }),
    report({ id: "occurred", breachStart: "2026-09-05", discoveryDate: "2026-09-05" }),
  ];
  assert.equal(countTodayReports(rows, now), 2);
  assert.deepEqual(filterReports(rows, "today", INITIAL_FILTERS, new Set(), now).map(r => r.id), ["published", "reported"]);
  assert.equal(filterReports(rows, "today", { ...INITIAL_FILTERS, query: "not present" }, new Set(), now).length, 0);
  assert.equal(countTodayReports(rows, now), 2, "the header total is independent of table filters");
});

test("today uses published date precedence and reported date only as fallback", () => {
  assert.equal(isReportFromToday(report({ publishedDate: "2026-09-04", reportedDate: "2026-09-05" }), now), false);
  assert.equal(isReportFromToday(report({ publishedDate: null, reportedDate: "2026-09-05" }), now), true);
  assert.equal(isReportFromToday(report({ publishedDate: "2029-01-01", reportedDate: "2026-09-05" }), now), false);
  assert.equal(isReportFromToday(report(), now), false);
});

test("today rolls over at UTC midnight including year boundaries", () => {
  const before = Date.parse("2026-12-31T23:59:59Z");
  const after = Date.parse("2026-12-31T18:00:00-06:00");
  assert.equal(utcDay(after), "2027-01-01");
  const old = report({ publishedDate: "2026-12-31" });
  assert.equal(countTodayReports([old], before), 1);
  assert.equal(countTodayReports([old], after), 0);
  assert.equal(countTodayReports([report({ reportedDate: "2027-01-01" })], after), 1);
});

test("today counts separate source reports even when organizations describe one incident", () => {
  const sameOrganization = [report({ id: "source-one", publishedDate: "2026-09-05" }), report({ id: "source-two", sourceId: "another", publishedDate: "2026-09-05" })];
  assert.equal(countTodayReports(sameOrganization, now), 2);
  const duplicate = report({ publishedDate: "2026-09-05" });
  assert.throws(() => readDataset(dataset([duplicate, duplicate])), "duplicate report IDs cannot enter a validated export");
});

test("local preview label is reserved for actual loopback hostnames", () => {
  for (const host of ["localhost", "127.0.0.1", "[::1]", "preview.localhost"]) assert.equal(isLocalHostname(host), true);
  for (const host of ["bd4l.github.io", "localhost.example.com", "example.com"]) assert.equal(isLocalHostname(host), false);
});

test("minimum counts require a qualifying exact count or lower bound", () => {
  const affected = {
    count: 1000,
    scope: "state" as const,
    jurisdiction: "MA",
    qualifier: "exact" as const,
  };
  const rows = ["exact", "at_least", "less_than", "unknown"].map((qualifier) =>
    report({
      id: qualifier,
      affected: {
        ...affected,
        qualifier: qualifier as Report["affected"]["qualifier"],
      },
    }),
  );
  assert.deepEqual(
    filterReports(
      rows,
      "all",
      { ...INITIAL_FILTERS, size: ["1000"] },
      new Set(),
      now,
    ).map((r) => r.id),
    ["exact", "at_least"],
  );
  assert.equal(
    filterReports(
      [report()],
      "all",
      { ...INITIAL_FILTERS, size: ["1000"] },
      new Set(),
      now,
    ).length,
    0,
  );
  assert.equal(
    filterReports(
      [report()],
      "all",
      { ...INITIAL_FILTERS, size: ["unknown"] },
      new Set(),
      now,
    ).length,
    1,
  );
  assert.equal(affectedCount({ ...affected, qualifier: "unknown" }), "1,000");
});

test("multiselect uses OR within each dropdown and AND across independent dropdowns", () => {
  const flagged = [{ code: "review", message: "Check source" }];
  const counted = { count: 1500, scope: "reported" as const, jurisdiction: null, qualifier: "exact" as const };
  const rows = [
    report({ id: "ma-flagged", sourceId: "ma", affected: counted, qualityFlags: flagged }),
    report({ id: "ca-updated", sourceId: "california", revision: 2 }),
    report({ id: "ma-plain", sourceId: "ma", affected: counted }),
    report({ id: "other-source", sourceId: "hhs", affected: counted, qualityFlags: flagged }),
    report({ id: "claim", sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-09-05T17:00:00Z", qualityFlags: flagged }),
  ];
  const filters: Filters = { ...INITIAL_FILTERS, source: ["ma", "california", "ransomlook"],
    size: ["1000", "unknown"], quality: ["flagged", "updated"], kind: ["official"] };
  assert.deepEqual(filterReports(rows, "all", filters, new Set(), now).map(r => r.id), ["ma-flagged", "ca-updated"]);
  assert.deepEqual(filterReports(rows, "all", { ...filters, kind: ["claims"], quality: ["flagged"] }, new Set(), now).map(r => r.id), ["claim"]);
  assert.deepEqual(filterReports(rows, "all", { ...filters, kind: ["claims"], quality: ["updated"] }, new Set(), now), []);
  assert.equal(filterReports(rows, "all", { ...INITIAL_FILTERS, kind: ["official", "claims"] }, new Set(), now).length, rows.length);
});

test("null selects all including future sources; an empty dropdown selection selects none", () => {
  const rows = [report(), report({ id: "future-source", sourceId: "new-register" })];
  assert.equal(filterReports(rows, "all", INITIAL_FILTERS, new Set(), now).length, 2);
  assert.deepEqual(filterReports(rows, "all", { ...INITIAL_FILTERS, source: ["ma"] }, new Set(), now).map(r => r.id), ["one"]);
  for (const field of ["source", "size", "quality", "kind", "searchFields"] as const) {
    assert.deepEqual(filterReports(rows, "all", { ...INITIAL_FILTERS, [field]: [] }, new Set(), now), [], field);
  }
});

test("combining size choices keeps unknown counts and preserves threshold qualifiers", () => {
  const rows = [
    report({ id: "unknown" }),
    ...["exact", "at_least", "less_than", "unknown"].map(qualifier => report({ id: `bound-${qualifier}`,
      affected: { count: 100000, scope: "reported", jurisdiction: null, qualifier: qualifier as Report["affected"]["qualifier"] } })),
    report({ id: "small", affected: { count: 99, scope: "reported", jurisdiction: null, qualifier: "exact" } }),
  ];
  assert.deepEqual(filterReports(rows, "all", { ...INITIAL_FILTERS, size: ["1000", "100000", "unknown"] }, new Set(), now).map(r => r.id),
    ["unknown", "bound-exact", "bound-at_least"]);
});

test("search is restricted to selected fields, including both identifiers and source labels", () => {
  const item = report({ id: "stable-key", nativeId: "native-key", organization: "Sample Care", summary: "A vendor incident",
    dataTypes: ["Medical information"], sourceId: "ma" });
  const matches = (query: string, searchFields: Filters["searchFields"]) =>
    filterReports([item], "all", { ...INITIAL_FILTERS, query, searchFields }, new Set(), now, [source]).length;
  assert.equal(matches("vendor", ["summary"]), 1);
  assert.equal(matches("vendor", ["organization", "ids"]), 0);
  assert.equal(matches("sAmPlE", ["organization"]), 1);
  assert.equal(matches("stable-key", ["ids"]), 1);
  assert.equal(matches("native-key", ["ids"]), 1);
  assert.equal(matches("medical", ["summary", "dataTypes"]), 1);
  assert.equal(matches("massachusetts", ["source"]), 1);
  assert.equal(matches("ma", ["source"]), 1);
  assert.equal(matches("massachusetts", ["organization"]), 0);
  assert.equal(matches("vendor", null), 1);
  assert.equal(matches("vendor", []), 0);
  assert.equal(filterReports([item], "all", { ...INITIAL_FILTERS, query: "ma", searchFields: ["source"] }, new Set(), now).length, 1,
    "source IDs remain searchable without optional catalog metadata");
});

test("Today official shortcut resets filters and excludes claims and historical imports", () => {
  const shortcut = todayOfficialFilters();
  assert.deepEqual(shortcut, { ...INITIAL_FILTERS, kind: ["official"] });
  const rows = [
    report({ id: "published-today", publishedDate: "2026-09-05" }),
    report({ id: "reported-today", reportedDate: "2026-09-05" }),
    report({ id: "claim", sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-09-05T17:00:00Z" }),
    report({ id: "imported-today", publishedDate: "2020-01-01" }),
    report({ id: "news", sourceId: "news_krebs", signalType: "secondary_report", publishedDate: "2026-09-05" }),
    report({ id: "claim-date-only", sourceId: "breachsense", signalType: "ransomware_claim", reportedDate: "2026-09-05" }),
  ];
  assert.deepEqual(filterReports(rows, "today", shortcut, new Set(), now).map(r => r.id), ["published-today", "reported-today"]);
  shortcut.kind!.push("claims");
  assert.deepEqual(todayOfficialFilters().kind, ["official"], "shortcut selections are independent");
  const fresh = freshInitialFilters();
  fresh.source = ["ma"];
  fresh.query = "changed";
  assert.deepEqual(freshInitialFilters(), INITIAL_FILTERS);
});

test("secondary sources cannot be relabeled as official notices and references cannot emit reports", () => {
  const secondary: Source = { ...source, id: "news_krebs", category: "secondary", method: "News / metadata feed" };
  const item = report({ sourceId: secondary.id, signalType: "secondary_report", publishedDate: "2026-09-05" });
  const value = { ...dataset([item]), sources: [secondary] };
  assert.equal(readDataset(value).reports[0].signalType, "secondary_report");
  assert.throws(() => readDataset({ ...value, reports: [{ ...item, signalType: undefined }] }));
  assert.throws(() => readDataset({ ...value, sources: [{ ...secondary, category: "reference" }] }));
  assert.throws(() => readDataset({ ...dataset(), sources: [{ ...source, category: ["official"] }] }));
  assert.equal(sourceKind(secondary.id, secondary), "News / metadata feed");
  assert.deepEqual(filterReports([item], "today", { ...INITIAL_FILTERS, kind: ["secondary"] }, new Set(), now), [item]);
});

test("source health distinguishes a usable partial collection from complete coverage and reference datasets", () => {
  const partial: Source = { ...source, status: "partial", lastSuccess: null, lastCollected: source.lastAttempt, latestReportDate: "2020-01-01" };
  assert.deepEqual(sourceHealth(partial, now), { label: "Limited coverage", tone: "warn", stale: false });
  assert.equal(sourceHealth({ ...partial, lastSuccess: "2029-01-01T00:00:00Z" }, now).label, "Unreliable timestamp");
  assert.equal(sourceHealth({ ...source, status: "disabled", category: "reference", collectionEnabled: false }, now).label, "Reference only");
});

test("revisions use observation time and do not infer recency from publication", () => {
  assert.equal(
    isRecent(
      report({
        firstSeen: "2025-01-01T00:00:00Z",
        lastChanged: "2026-09-05T00:00:00Z",
        publishedDate: "2025-01-01",
      }),
      now,
    ),
    true,
  );
  assert.equal(
    isRecent(
      report({
        firstSeen: "2025-01-01T00:00:00Z",
        lastChanged: "2025-01-01T00:00:00Z",
        publishedDate: "2026-09-05",
      }),
      now,
    ),
    false,
  );
  assert.equal(
    isRecent(report({ lastChanged: "2029-01-01T00:00:00Z" }), now),
    false,
  );
});

test("latest ordering uses valid source dates ahead of collection changes and breaks ties by organization", () => {
  const rows = [
    report({ id: "reported-older", organization: "A company", reportedDate: "2026-09-02" }),
    report({ id: "published-tie", organization: "Z company", publishedDate: "2026-09-02" }),
    report({ id: "latest-published", organization: "Z company", publishedDate: "2026-09-04" }),
    report({ id: "reported-newer", organization: "A company", reportedDate: "2026-09-03" }),
    report({ id: "future-withheld", organization: "A company", publishedDate: "2029-01-01" }),
    report({ id: "changed-first", organization: "Z company", lastChanged: "2026-09-05T17:30:00Z", reportedDate: "2020-01-01" }),
  ];
  assert.deepEqual(
    filterReports(rows, "all", INITIAL_FILTERS, new Set(), now).map(row => row.id),
    ["latest-published", "reported-newer", "reported-older", "published-tie", "changed-first", "future-withheld"],
  );
});

test("source date labels preserve reported versus published and show older years", () => {
  assert.equal(reportDateLabel(report({ publishedDate: "2026-09-04", reportedDate: "2026-09-03" }), now), "Published Sep 4");
  assert.equal(reportDateLabel(report({ reportedDate: "2026-09-03" }), now), "Reported Sep 3");
  assert.equal(reportDateLabel(report({ reportedDate: "2020-09-03" }), now), "Reported Sep 3, 2020");
  assert.equal(reportDateLabel(report({ publishedDate: "2029-01-01" }), now), "Source date not reported");
  assert.equal(reportDateLabel(report({ publishedDate: "2029-01-01", reportedDate: "2026-09-03" }), now), "Source date not reported");
});

test("date quality messages use understandable field names", () => {
  assert.equal(qualityMessage("publishedDate is in the future"), "Publication date is in the future");
  assert.equal(qualityMessage("discovery_date could not be parsed"), "Discovery date could not be parsed");
});

test("source health is computed at viewing time and cannot turn future success green", () => {
  assert.equal(sourceHealth(source, now).tone, "good");
  assert.equal(sourceHealth(source, now + 3 * 86_400_000).label, "Stale");
  assert.equal(sourceHealth({ ...source, status: "failed" }, now).tone, "bad");
  assert.equal(
    sourceHealth({ ...source, status: "partial" }, now).tone,
    "warn",
  );
  assert.equal(
    sourceHealth({ ...source, lastSuccess: "2029-01-01T00:00:00Z" }, now).label,
    "Unreliable timestamp",
  );
  assert.notEqual(
    sourceHealth({ ...source, lastAttempt: "2029-01-01T00:00:00Z" }, now).tone,
    "good",
  );
});

test("untrusted links cannot execute scripts, load data URLs, or conceal credentials", () => {
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("data:text/html,hello"), null);
  assert.equal(safeUrl("//example.com"), null);
  assert.equal(safeUrl("https://user:pass@example.com"), null);
  assert.equal(
    safeUrl("https://www.mass.gov/record?q=a"),
    "https://www.mass.gov/record?q=a",
  );
});

test("contract rejects malformed dates, duplicate identities and dangling sources", () => {
  assert.equal(readDataset(dataset()).reports.length, 1);
  assert.throws(() => readDataset(dataset([report(), report()])));
  assert.throws(() => readDataset(dataset([report({ sourceId: "missing" })])));
  assert.throws(() =>
    readDataset(dataset([report({ firstSeen: "yesterday" })])),
  );
  assert.throws(() =>
    readDataset(dataset([report({ publishedDate: "2026-02-31" })])),
  );
  assert.throws(() =>
    readDataset({ ...dataset(), sources: [{ ...source, lastSuccess: "bad" }] }),
  );
  assert.throws(() => readDataset({ ...dataset(), schemaVersion: 2 }));
});

test("claim records require explicit classification and source observation; attribution links stay safe", () => {
  const claimSource: Source = { ...source, id: "ransomlook", label: "RansomLook", homepage: "https://www.ransomlook.io/", attribution: {
    name: "RansomLook", url: "https://www.ransomlook.io/", license: "CC BY 4.0", licenseUrl: "https://creativecommons.org/licenses/by/4.0/", changes: "Normalized and filtered for recent claims.",
  } };
  const claim = report({ sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-09-05T17:00:00Z" });
  const valid = { ...dataset([claim]), sources: [claimSource] };
  assert.equal(readDataset(valid).reports[0].signalType, "ransomware_claim");
  assert.throws(() => readDataset({ ...valid, reports: [{ ...claim, signalType: undefined }] }));
  assert.throws(() => readDataset({ ...valid, reports: [{ ...claim, sourceObservedAt: undefined }] }));
  assert.throws(() => readDataset(dataset([report({ signalType: "ransomware_claim" })])));
  for (const field of ["url", "licenseUrl"]) assert.throws(() => readDataset({ ...valid, sources: [{ ...claimSource, attribution: { ...claimSource.attribution, [field]: "javascript:alert(1)" } }] }));
  assert.throws(() => readDataset({ ...valid, sources: [{ ...claimSource, homepage: "javascript:alert(1)" }] }));
  assert.throws(() => readDataset({ ...valid, sources: [{ ...claimSource, attribution: { ...claimSource.attribution, changes: [] } }] }));
});

test("newest revisions render first without duplicating the initial collection", () => {
  const history: Report["history"] = [
    { observedAt: "2026-09-02T00:00:00Z", changedFields: ["summary"] },
    {
      observedAt: "2026-09-05T00:00:00Z",
      changedFields: ["affected"],
      changes: [{ field: "affected", before: 8200, after: 12480 }],
    },
    { observedAt: "2026-09-01T00:00:00Z", changedFields: ["created"] },
  ];
  assert.deepEqual(
    recentHistory(report({ history })).map((h) => h.observedAt),
    ["2026-09-05T00:00:00Z", "2026-09-02T00:00:00Z"],
  );
  assert.equal(history.length, 3);
});

test("saved view uses report IDs and tolerates damaged browser storage", () => {
  assert.deepEqual(
    [...readSavedIds('["one",5,{"notes":"no"},"two"]')],
    ["one", "two"],
  );
  assert.equal(readSavedIds("{bad").size, 0);
  assert.equal(
    filterReports(
      [report(), report({ id: "two" })],
      "saved",
      INITIAL_FILTERS,
      new Set(["two"]),
      now,
    )[0].id,
    "two",
  );
});
