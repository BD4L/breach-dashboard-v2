import { readDataset, type Dataset } from "./dashboard.ts";

export interface SnapshotState {
  data: Dataset | null;
  error: string;
  refreshing: boolean;
  lastCheckedAt: number | null;
}

export const EMPTY_SNAPSHOT: SnapshotState = {
  data: null, error: "", refreshing: false, lastCheckedAt: null,
};

type Fetcher = (url: string, options: RequestInit) => Promise<Response>;

export function createSnapshotLoader({
  url,
  onChange,
  fetcher = fetch,
  timeoutMs = 15_000,
  now = Date.now,
}: {
  url: string;
  onChange: (state: SnapshotState) => void;
  fetcher?: Fetcher;
  timeoutMs?: number;
  now?: () => number;
}) {
  let state: SnapshotState = { ...EMPTY_SNAPSHOT };
  let disposed = false;
  let task: Promise<void> | null = null;
  let controller: AbortController | null = null;

  function update(changes: Partial<SnapshotState>) {
    if (disposed) return;
    state = { ...state, ...changes };
    onChange(state);
  }

  function refresh(): Promise<void> {
    if (disposed) return Promise.resolve();
    if (task) return task;
    // Assign the in-flight task before the request starts, including synchronous callers.
    task = Promise.resolve().then(async () => {
      if (disposed) return;
      const requestController = new AbortController();
      controller = requestController;
      let timedOut = false;
      const aborted = new Promise<never>((_, reject) => {
        requestController.signal.addEventListener("abort", () => {
          reject(new Error(timedOut ? "The snapshot check timed out. Try again." : "Snapshot check cancelled."));
        }, { once: true });
      });
      const timer = setTimeout(() => {
        timedOut = true;
        requestController.abort();
      }, timeoutMs);
      update({ refreshing: true });
      try {
        const request = async () => {
          const response = await fetcher(url, {
            signal: requestController.signal,
            cache: "no-cache",
            mode: "same-origin",
            credentials: "omit",
            redirect: "error",
          });
          if (!response.ok) throw new Error(`The published snapshot could not be loaded (${response.status}).`);
          return readDataset(await response.json());
        };
        const data = await Promise.race([request(), aborted]);
        if (!requestController.signal.aborted) update({ data, error: "", lastCheckedAt: now() });
      } catch (reason) {
        update({ error: reason instanceof SyntaxError ? "The published snapshot could not be read. Try again." : reason instanceof Error ? reason.message : "The published snapshot could not be checked. Try again." });
      } finally {
        clearTimeout(timer);
        if (controller === requestController) controller = null;
        update({ refreshing: false });
      }
    }).finally(() => { task = null; });
    return task;
  }

  return {
    refresh,
    getState: () => state,
    dispose() {
      disposed = true;
      controller?.abort();
    },
  };
}
