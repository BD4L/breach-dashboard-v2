import { type Dataset } from "./dashboard.ts";
import { readSnapshot, verifyArchive, type SnapshotIndex } from "./snapshot-format.ts";

export interface SnapshotState {
  data: Dataset | null;
  index: SnapshotIndex | null;
  archiveStatus: "unloaded" | "loading" | "loaded" | "error";
  archiveError: string;
  error: string;
  refreshing: boolean;
  lastCheckedAt: number | null;
}
export const EMPTY_SNAPSHOT: SnapshotState = {
  data: null, index: null, archiveStatus: "unloaded", archiveError: "",
  error: "", refreshing: false, lastCheckedAt: null,
};
class SnapshotHttpError extends Error {
  status: number;
  constructor(status: number) {
    super(`The published snapshot could not be loaded (${status}).`);
    this.status = status;
  }
}
type Fetcher = (url: string, options: RequestInit) => Promise<Response>;

export function createSnapshotLoader({ url, onChange, fetcher = fetch, timeoutMs = 15_000,
  archiveTimeoutMs = 90_000, now = Date.now,
}: { url: string; onChange: (state: SnapshotState) => void; fetcher?: Fetcher;
  timeoutMs?: number; archiveTimeoutMs?: number; now?: () => number;
}) {
  let state: SnapshotState = { ...EMPTY_SNAPSHOT };
  let disposed = false;
  let task: Promise<Dataset | null> | null = null;
  let controller: AbortController | null = null;
  let archiveWanted = false;
  const update = (changes: Partial<SnapshotState>) => {
    if (!disposed) { state = { ...state, ...changes }; onChange(state); }
  };

  async function request<T>(target: string, duration: number, read: (response: Response) => Promise<T>): Promise<T> {
    const active = new AbortController();
    controller = active;
    let timedOut = false;
    const aborted = new Promise<never>((_, reject) => {
      active.signal.addEventListener("abort", () => reject(new Error(timedOut
        ? "The snapshot check timed out. Try again." : "Snapshot check cancelled.")), { once: true });
    });
    const timer = setTimeout(() => { timedOut = true; active.abort(); }, duration);
    try {
      const result = await Promise.race([(async () => {
        const response = await fetcher(target, { signal: active.signal, cache: "no-cache", mode: "same-origin", credentials: "omit", redirect: "error" });
        if (!response.ok) throw new SnapshotHttpError(response.status);
        return read(response);
      })(), aborted]);
      if (active.signal.aborted || disposed) throw new Error("Snapshot check cancelled.");
      return result;
    } finally {
      clearTimeout(timer);
      if (controller === active) controller = null;
    }
  }

  async function archive(data: Dataset, index: SnapshotIndex): Promise<Dataset> {
    const base = new URL(url, globalThis.location?.href || "https://snapshot.invalid/");
    const target = new URL(index.archive.url, base);
    // Only the existing public full-snapshot filename is accepted; it cannot leave this directory.
    const archiveUrl = /^https?:/.test(url) ? target.href : target.pathname;
    return request(archiveUrl, archiveTimeoutMs, async response => {
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength !== index.archive.bytes) throw new Error("The archive size does not match this snapshot. Refresh and try again.");
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      if (hash !== index.archive.sha256) throw new Error("The archive does not match this snapshot. Refresh and try again.");
      return verifyArchive(JSON.parse(new TextDecoder().decode(bytes)), data, index);
    });
  }

  function run(kind: "refresh" | "archive"): Promise<Dataset | null> {
    // The single request queue prevents refresh/archive responses from racing.
    task = Promise.resolve().then(async () => {
      if (disposed) return null;
      const wasFull = state.archiveStatus === "loaded";
      if (kind === "refresh") update({ refreshing: true });
      else update({ archiveStatus: "loading", archiveError: "" });
      try {
        if (kind === "archive") {
          if (!state.data || !state.index || wasFull) return state.data;
          const data = await archive(state.data, state.index);
          update({ data, archiveStatus: "loaded", archiveError: "" });
          return data;
        }
        let next;
        try {
          next = await request(url, timeoutMs, async response => readSnapshot(await response.json()));
        } catch (reason) {
          // Older deployments and the development server still expose schema1 only.
          if (!(reason instanceof SnapshotHttpError) || reason.status !== 404 || !url.endsWith("/snapshot.json")) throw reason;
          next = await request(url.replace(/snapshot\.json$/, "dashboard.json"), timeoutMs,
            async response => readSnapshot(await response.json()));
        }
        let data = next.data;
        let full = next.index === null || next.data.reports.length === next.index.totalReports;
        if (next.index && state.index?.id === next.index.id && wasFull && state.data) {
          // The retained archive is already verified for this exact revision.
          data = verifyArchive(state.data, next.data, next.index);
          full = true;
        } else if (next.index && archiveWanted && !full) {
          if (!wasFull) update({ archiveStatus: "loading", archiveError: "" });
          data = await archive(next.data, next.index);
          full = true;
        }
        // Commit metadata and reports together only after required archive validation.
        update({ data, index: next.index, archiveStatus: full ? "loaded" : "unloaded",
          archiveError: "", error: "", lastCheckedAt: now() });
        return data;
      } catch (reason) {
        const error = reason instanceof SyntaxError ? "The published snapshot could not be read. Try again."
          : reason instanceof Error ? reason.message : "The published snapshot could not be checked. Try again.";
        if (kind === "refresh") update({ error, archiveStatus: wasFull ? "loaded" : state.data ? "error" : "unloaded" });
        else update({ archiveError: error, archiveStatus: "error" });
        return null;
      } finally {
        if (kind === "refresh") update({ refreshing: false });
      }
    }).finally(() => { task = null; });
    return task;
  }
  function refresh(): Promise<Dataset | null> {
    if (disposed) return Promise.resolve(null);
    return task || run("refresh");
  }
  function loadArchive(): Promise<Dataset | null> {
    archiveWanted = true;
    if (disposed) return Promise.resolve(null);
    if (task) return task.then(() => state.archiveStatus === "loaded" ? state.data
      : state.error || state.archiveError ? null : loadArchive());
    if (!state.data || !state.index || state.archiveStatus === "loaded") return Promise.resolve(state.data);
    return run("archive");
  }
  return { refresh, loadArchive, getState: () => state, dispose() { disposed = true; controller?.abort(); } };
}
