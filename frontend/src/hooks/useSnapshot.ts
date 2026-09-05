import { useCallback, useEffect, useRef, useState } from "react";
import { createSnapshotLoader, EMPTY_SNAPSHOT } from "../lib/snapshot";

export const SNAPSHOT_POLL_INTERVAL = 5 * 60_000;

export function useSnapshot(url: string) {
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const refreshRef = useRef<() => Promise<void>>(() => Promise.resolve());

  useEffect(() => {
    const loader = createSnapshotLoader({ url, onChange: setSnapshot });
    let disposed = false;
    let poll: ReturnType<typeof setTimeout> | undefined;

    function schedule() {
      clearTimeout(poll);
      if (!disposed && document.visibilityState === "visible") {
        poll = setTimeout(() => { void check(); }, SNAPSHOT_POLL_INTERVAL);
      }
    }
    async function check() {
      if (disposed) return;
      clearTimeout(poll);
      await loader.refresh();
      schedule();
    }
    function onVisibility() {
      if (document.visibilityState === "visible") void check();
      else clearTimeout(poll);
    }

    refreshRef.current = check;
    document.addEventListener("visibilitychange", onVisibility);
    void check();
    return () => {
      disposed = true;
      clearTimeout(poll);
      document.removeEventListener("visibilitychange", onVisibility);
      refreshRef.current = () => Promise.resolve();
      loader.dispose();
    };
  }, [url]);

  const refresh = useCallback(() => refreshRef.current(), []);
  return { ...snapshot, refresh };
}
