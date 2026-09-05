import { createHash } from "node:crypto";
import { readFile, writeFile, rename, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readDataset, filterReports, INITIAL_FILTERS } from "../src/lib/dashboard.ts";
import { readSnapshot } from "../src/lib/snapshot-format.ts";

export function splitSnapshot(input, { recentLimit = 200, bootstrapBudget = 1_000_000 } = {}) {
  if (!Number.isInteger(recentLimit) || recentLimit < 1 || !Number.isInteger(bootstrapBudget) || bootstrapBudget < 1) {
    throw new Error("Snapshot limits must be positive integers.");
  }
  const archive = Buffer.isBuffer(input) ? input : Buffer.from(input);
  const full = readDataset(JSON.parse(archive.toString("utf8")));
  const id = createHash("sha256").update(archive).digest("hex");
  const sourceDateCounts = {}, changeTimeCounts = {};
  for (const report of full.reports) {
    const day = report.publishedDate ?? report.reportedDate;
    if (day) sourceDateCounts[day] = (sourceDateCounts[day] || 0) + 1;
    const changed = new Date(Math.max(Date.parse(report.firstSeen), Date.parse(report.lastChanged))).toISOString();
    changeTimeCounts[changed] = (changeTimeCounts[changed] || 0) + 1;
  }
  const ordered = filterReports(full.reports, "all", INITIAL_FILTERS, new Set(), Date.parse(full.generatedAt));
  const bootstrap = { schemaVersion: 2, mode: full.mode, generatedAt: full.generatedAt, sources: full.sources,
    reports: ordered.slice(0, recentLimit), snapshot: { id, totalReports: full.reports.length,
      archive: { url: "dashboard.json", sha256: id, bytes: archive.byteLength }, sourceDateCounts, changeTimeCounts } };
  let encoded = Buffer.from(JSON.stringify(bootstrap));
  // Whole records are retained; their evidence/history is never truncated to fit.
  while (encoded.byteLength > bootstrapBudget && bootstrap.reports.length > 1) {
    bootstrap.reports.pop();
    encoded = Buffer.from(JSON.stringify(bootstrap));
  }
  if (encoded.byteLength > bootstrapBudget) throw new Error("Snapshot summaries and one complete report exceed the bootstrap budget.");
  if (encoded.byteLength + archive.byteLength > 49_000_000) throw new Error("Snapshot files exceed the 49 MB data budget.");
  readSnapshot(bootstrap);
  return { bootstrap, encoded, archive, archiveName: bootstrap.snapshot.archive.url };
}

export async function splitFile(path) {
  const result = splitSnapshot(await readFile(path));
  async function atomic(destination, content) {
    const temp = `${destination}.${process.pid}.tmp`;
    try { await writeFile(temp, content); await rename(temp, destination); }
    finally { await rm(temp, { force: true }); }
  }
  // Keep the existing full schema1 URL byte-for-byte. Publish its matching index
  // last; readers reject mixed deployment/cache versions using the archive hash.
  await atomic(join(dirname(path), "snapshot.json"), result.encoded);
  return result;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const path = resolve(process.argv[2] || "dist/data/dashboard.json");
  const result = await splitFile(path);
  console.log(`Snapshot: ${result.bootstrap.reports.length}/${result.bootstrap.snapshot.totalReports} initial reports; ${result.encoded.byteLength.toLocaleString()} initial bytes; ${result.archive.byteLength.toLocaleString()} archive bytes.`);
}
