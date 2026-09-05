import { DAY, readDataset, type Dataset, type Filters, type View } from "./dashboard.ts";

export interface SnapshotIndex {
  id: string;
  totalReports: number;
  archive: { url: string; sha256: string; bytes: number };
  sourceDateCounts: Record<string, number>;
  changeTimeCounts: Record<string, number>;
}
export interface PublishedSnapshot { data: Dataset; index: SnapshotIndex | null }
export const MAX_ARCHIVE_BYTES = 50_000_000;
const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;

export function readSnapshot(value: unknown): PublishedSnapshot {
  if (!object(value) || value.schemaVersion !== 2) return { data: readDataset(value), index: null };
  const data = readDataset({ schemaVersion: 1, mode: value.mode, generatedAt: value.generatedAt,
    sources: value.sources, reports: value.reports });
  const s = value.snapshot;
  const invalid = (): never => { throw new Error("The snapshot index is invalid. Refresh the published snapshot and try again."); };
  if (!object(s) || typeof s.id !== "string" || !/^[a-f0-9]{64}$/.test(s.id) ||
      !count(s.totalReports) || s.totalReports < data.reports.length || !object(s.archive) ||
      s.archive.url !== "dashboard.json" || s.archive.sha256 !== s.id ||
      !count(s.archive.bytes) || s.archive.bytes < 1 || s.archive.bytes > MAX_ARCHIVE_BYTES ||
      !object(s.sourceDateCounts) || !object(s.changeTimeCounts)) return invalid();
  let dated = 0, changed = 0;
  for (const [day, n] of Object.entries(s.sourceDateCounts)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day)) ||
        new Date(day).toISOString().slice(0, 10) !== day || !count(n)) return invalid();
    dated += n;
  }
  for (const [time, n] of Object.entries(s.changeTimeCounts)) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(time) ||
        !Number.isFinite(Date.parse(time)) || !count(n)) return invalid();
    changed += n;
  }
  if (dated > s.totalReports || changed !== s.totalReports) return invalid();
  return { data, index: s as unknown as SnapshotIndex };
}

export function snapshotRecentCount(index: SnapshotIndex, now: number): number {
  return Object.entries(index.changeTimeCounts).reduce((n, [time, count]) => {
    const at = Date.parse(time);
    return n + (at >= now - 7 * DAY && at <= now + 5 * 60_000 ? count : 0);
  }, 0);
}

export function needsArchive(view: View, filters: Filters): boolean {
  return view !== "sources" && (view !== "recent" || filters.query.trim() !== "" ||
    filters.source !== "all" || filters.size !== "all" || filters.quality !== "all" || filters.sort !== "latest");
}

export function verifyArchive(value: unknown, bootstrap: Dataset, index: SnapshotIndex): Dataset {
  const data = readDataset(value);
  if (data.mode !== bootstrap.mode || data.generatedAt !== bootstrap.generatedAt ||
      data.reports.length !== index.totalReports || JSON.stringify(data.sources) !== JSON.stringify(bootstrap.sources)) {
    throw new Error("The archive belongs to a different snapshot. Refresh and try again.");
  }
  const reports = new Map(data.reports.map(r => [r.id, r]));
  if (bootstrap.reports.some(r => JSON.stringify(reports.get(r.id)) !== JSON.stringify(r))) {
    throw new Error("The archive does not match the loaded reports. Refresh and try again.");
  }
  return data;
}
