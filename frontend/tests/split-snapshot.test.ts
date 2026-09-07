import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { splitSnapshot, splitFile } from "../scripts/split-snapshot.mjs";
import { readSnapshot, snapshotRecentCount, snapshotTodayCount, needsArchive } from "../src/lib/snapshot-format.ts";
import { countTodayReports, filterReports, INITIAL_FILTERS, readDataset, isRecentSignal } from "../src/lib/dashboard.ts";

const raw = await readFile(new URL("../public/data/dashboard.json", import.meta.url));
const full = readDataset(JSON.parse(raw.toString()));
const now = Date.parse(full.generatedAt);

test("split retains the exact full archive, histories, source outcomes and whole-snapshot counts", () => {
  const result = splitSnapshot(raw, { recentLimit: 2 });
  assert.deepEqual(result.archive, raw);
  assert.equal(result.archiveName, "dashboard.json");
  assert.equal(result.bootstrap.snapshot.archive.sha256, createHash("sha256").update(raw).digest("hex"));
  const parsed = readSnapshot(result.bootstrap);
  assert.deepEqual(parsed.data.reports, filterReports(full.reports, "all", INITIAL_FILTERS, new Set(), now).slice(0, 2));
  assert.deepEqual(parsed.data.sources, full.sources);
  assert.equal(parsed.index?.totalReports, full.reports.length);
  assert.equal(snapshotRecentCount(parsed.index!, now), full.reports.filter(r => isRecentSignal(r, now)).length);
  assert.equal(snapshotTodayCount(parsed.index!, now), countTodayReports(full.reports, now));
  assert.equal(parsed.index?.sourceDateCounts[full.generatedAt.slice(0,10)] || 0, countTodayReports(full.reports, now));
  assert.deepEqual(splitSnapshot(raw, { recentLimit: 2 }).encoded, result.encoded);
});

test("bootstrap shrinks by whole reports to its budget, without truncating evidence", () => {
  const one = splitSnapshot(raw, { recentLimit: 1 });
  const result = splitSnapshot(raw, { bootstrapBudget: one.encoded.byteLength });
  assert.equal(result.bootstrap.reports.length, 1);
  assert.deepEqual(result.bootstrap.reports, one.bootstrap.reports);
  assert.throws(() => splitSnapshot(raw, { bootstrapBudget: one.encoded.byteLength - 1 }), /budget/);
  assert.throws(() => splitSnapshot(raw, { recentLimit: 0 }));
  assert.throws(() => splitSnapshot('{"schemaVersion":99}'));
});

test("source-date summary obeys strict publication precedence, including a different UTC day", () => {
  const data = structuredClone(full);
  data.reports = [structuredClone(data.reports[0])];
  data.reports[0].publishedDate = "2026-09-04";
  data.reports[0].reportedDate = "2026-09-05";
  const index = splitSnapshot(JSON.stringify(data)).bootstrap.snapshot;
  assert.equal(index.sourceDateCounts["2026-09-04"], 1);
  assert.equal(index.sourceDateCounts["2026-09-05"], undefined);
});

test("bootstrap source ordering and complete counts exclude historical imports and future claims", () => {
  const data = structuredClone(full);
  data.generatedAt = "2026-09-05T18:00:00Z";
  const clock = Date.parse(data.generatedAt);
  const base = { ...data.reports[0], firstSeen: data.generatedAt, lastChanged: data.generatedAt, publishedDate: null, reportedDate: null };
  const claim = { ...base, sourceId: "ransomlook", signalType: "ransomware_claim" as const };
  data.sources.push({ ...data.sources[0], id: "ransomlook", label: "RansomLook", homepage: "https://www.ransomlook.io/" });
  data.reports = [
    { ...base, id: "historical-import", publishedDate: "2020-01-01" },
    { ...claim, id: "boundary", sourceObservedAt: "2026-08-29T18:00:00Z" },
    { ...claim, id: "outside", sourceObservedAt: "2026-08-29T17:59:59Z" },
    { ...claim, id: "claim-today", sourceObservedAt: "2026-09-05T12:30:00-05:00", publishedDate: "2020-01-01" },
    { ...claim, id: "future", sourceObservedAt: "2026-09-05T18:00:01Z" },
    { ...base, id: "report-today", publishedDate: "2026-09-05" },
    { ...base, id: "undated" },
  ];
  const result = splitSnapshot(JSON.stringify(data), { recentLimit: 2 });
  const parsed = readSnapshot(result.bootstrap);
  assert.deepEqual(parsed.data.reports.map(r => r.id), ["claim-today", "report-today"]);
  assert.equal(parsed.index!.totalReports, 7);
  assert.equal(snapshotRecentCount(parsed.index!, clock), 3);
  assert.equal(snapshotRecentCount(parsed.index!, clock), data.reports.filter(r => isRecentSignal(r, clock)).length);
  assert.equal(snapshotTodayCount(parsed.index!, clock), 2);
  assert.equal(snapshotTodayCount(parsed.index!, clock), countTodayReports(data.reports, clock));
  assert.equal(parsed.index!.signalTimeCounts!["2026-09-05T17:30:00.000Z"], 1);
  assert.equal(snapshotTodayCount(parsed.index!, clock + 1000), countTodayReports(data.reports, clock + 1000));
  assert.deepEqual(JSON.parse(result.archive.toString()).reports, data.reports, "full report history is preserved");
});

test("older indices use source dates, never collection changes, for Latest counts", () => {
  const data = structuredClone(full);
  data.generatedAt = "2026-09-05T18:00:00Z";
  data.reports = [{ ...data.reports[0], firstSeen: data.generatedAt, lastChanged: data.generatedAt, publishedDate: "2020-01-01" }];
  const bootstrap = splitSnapshot(JSON.stringify(data)).bootstrap;
  delete bootstrap.snapshot.signalTimeCounts;
  const parsed = readSnapshot(bootstrap);
  assert.equal(snapshotRecentCount(parsed.index!, Date.parse(data.generatedAt)), 0);
});

test("file splitting preserves the legacy URL and writes a separate lightweight index", async () => {
  const directory = await mkdtemp(join(tmpdir(), "snapshot split "));
  try {
    const path = join(directory, "dashboard.json");
    await writeFile(path, raw);
    const result = await splitFile(path);
    assert.deepEqual(await readFile(join(directory, result.archiveName)), raw);
    assert.equal(JSON.parse(await readFile(path, "utf8")).schemaVersion, 1);
    assert.equal(JSON.parse(await readFile(join(directory, "snapshot.json"), "utf8")).schemaVersion, 2);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("whole archive is required for full views and any filter or alternate sort", () => {
  assert.equal(needsArchive("recent", INITIAL_FILTERS), false);
  for (const view of ["all", "today", "saved"] as const) assert.equal(needsArchive(view, INITIAL_FILTERS), true);
  for (const [key, value] of Object.entries({query:"history", source:"maine", size:"unknown", quality:"flagged", sort:"organization"})) {
    assert.equal(needsArchive("recent", {...INITIAL_FILTERS, [key]:value}), true);
  }
  assert.equal(needsArchive("sources", {...INITIAL_FILTERS, query:"anything"}), false);
});

test("malformed count summaries cannot make partial views appear complete", () => {
  const result=splitSnapshot(raw,{recentLimit:2});
  const wrong=structuredClone(result.bootstrap);wrong.snapshot.totalReports++;
  assert.throws(()=>readSnapshot(wrong),/index/);
  const badDate=structuredClone(result.bootstrap);badDate.snapshot.sourceDateCounts["2026-02-30"]=1;
  assert.throws(()=>readSnapshot(badDate),/index/);
  const wrongArchive=structuredClone(result.bootstrap);wrongArchive.snapshot.archive.url="../archive.json";
  assert.throws(()=>readSnapshot(wrongArchive),/index/);
  const wrongSignal=structuredClone(result.bootstrap);wrongSignal.snapshot.signalTimeCounts["2026-09-05T12:00:00.000Z"]=100;
  assert.throws(()=>readSnapshot(wrongSignal),/index/);
  const badSignalDate=structuredClone(result.bootstrap);badSignalDate.snapshot.signalTimeCounts["2026-02-30T12:00:00.000Z"]=0;
  assert.throws(()=>readSnapshot(badSignalDate),/index/);
});
