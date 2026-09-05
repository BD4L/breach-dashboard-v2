import test from "node:test";
import assert from "node:assert/strict";
import {
  affectedCount,
  filterReports,
  INITIAL_FILTERS,
  isRecent,
  qualityMessage,
  readDataset,
  readSavedIds,
  recentHistory,
  reportDateLabel,
  safeUrl,
  sourceHealth,
  type Dataset,
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

test("unknown counts and publication dates stay in the default review queue", () => {
  assert.equal(
    filterReports([report()], "recent", INITIAL_FILTERS, new Set(), now).length,
    1,
  );
  assert.equal(
    filterReports([report()], "all", INITIAL_FILTERS, new Set(), now).length,
    1,
  );
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
      { ...INITIAL_FILTERS, size: "1000" },
      new Set(),
      now,
    ).map((r) => r.id),
    ["exact", "at_least"],
  );
  assert.equal(
    filterReports(
      [report()],
      "all",
      { ...INITIAL_FILTERS, size: "1000" },
      new Set(),
      now,
    ).length,
    0,
  );
  assert.equal(
    filterReports(
      [report()],
      "all",
      { ...INITIAL_FILTERS, size: "unknown" },
      new Set(),
      now,
    ).length,
    1,
  );
  assert.equal(affectedCount({ ...affected, qualifier: "unknown" }), "1,000");
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

test("tied collection changes use valid source dates before organization order", () => {
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
    ["changed-first", "latest-published", "reported-newer", "reported-older", "published-tie", "future-withheld"],
  );
});

test("source date labels preserve reported versus published and show older years", () => {
  assert.equal(reportDateLabel(report({ publishedDate: "2026-09-04", reportedDate: "2026-09-03" }), now), "Published Sep 4");
  assert.equal(reportDateLabel(report({ reportedDate: "2026-09-03" }), now), "Reported Sep 3");
  assert.equal(reportDateLabel(report({ reportedDate: "2020-09-03" }), now), "Reported Sep 3, 2020");
  assert.equal(reportDateLabel(report({ publishedDate: "2029-01-01" }), now), "Source date not reported");
  assert.equal(reportDateLabel(report({ publishedDate: "2029-01-01", reportedDate: "2026-09-03" }), now), "Reported Sep 3");
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
