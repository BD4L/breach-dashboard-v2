import test from "node:test";
import assert from "node:assert/strict";
import { createSnapshotLoader, type SnapshotState } from "../src/lib/snapshot.ts";

const data = { schemaVersion: 1, mode: "demo", generatedAt: "2026-09-05T18:00:00Z", sources: [], reports: [] };
const response = () => new Response(JSON.stringify(data));

test("refresh calls coalesce and use only the same-origin public snapshot request", async () => {
  let resolve!: (value: Response) => void;
  let calls = 0;
  let options: RequestInit | undefined;
  const loader = createSnapshotLoader({ url: "/project/data/dashboard.json", onChange() {}, fetcher: async (url, init) => {
    assert.equal(url, "/project/data/dashboard.json");
    calls++; options = init;
    return new Promise<Response>(done => { resolve = done; });
  } });
  const first = loader.refresh();
  const second = loader.refresh();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.equal(options?.mode, "same-origin");
  assert.equal(options?.cache, "no-cache");
  assert.equal(options?.credentials, "omit");
  assert.equal(options?.redirect, "error");
  resolve(response());
  await first;
  assert.equal(loader.getState().data?.mode, "demo");
  loader.dispose();
});

test("HTTP and invalid JSON failures retain the last valid data and check time, then recover", async () => {
  let failure = "";
  let clock = 100;
  const loader = createSnapshotLoader({ url: "/data/dashboard.json", onChange() {}, now: () => clock, fetcher: async () => failure === "http" ? new Response("missing", { status: 404 }) : failure === "json" ? new Response("<html>") : failure === "schema" ? new Response('{"schemaVersion":99}') : response() });
  await loader.refresh();
  const good = loader.getState().data;
  for (const kind of ["http", "json", "schema"]) {
    failure = kind; clock++;
    await loader.refresh();
    assert.equal(loader.getState().data, good);
    assert.equal(loader.getState().lastCheckedAt, 100);
    assert.notEqual(loader.getState().error, "");
  }
  failure = "";
  await loader.refresh();
  assert.equal(loader.getState().error, "");
  assert.equal(loader.getState().lastCheckedAt, 103);
  loader.dispose();
});

test("timeout aborts stalled body parsing, releases the request, and ignores late completion", async () => {
  let bodyResolve!: (value: unknown) => void;
  let signal: AbortSignal | undefined;
  let stalled = true;
  const loader = createSnapshotLoader({ url: "/data/dashboard.json", onChange() {}, timeoutMs: 5, fetcher: async (_, init) => {
    signal = init.signal as AbortSignal;
    return stalled ? { ok: true, json: () => new Promise(done => { bodyResolve = done; }) } as Response : response();
  } });
  await loader.refresh();
  assert.equal(signal?.aborted, true);
  assert.match(loader.getState().error, /timed out/);
  assert.equal(loader.getState().refreshing, false);
  bodyResolve(data);
  await Promise.resolve();
  assert.equal(loader.getState().data, null);
  stalled = false;
  await loader.refresh();
  assert.equal(loader.getState().data?.mode, "demo");
  loader.dispose();
});

test("disposal aborts in-flight work and prevents late state updates", async () => {
  const updates: SnapshotState[] = [];
  let resolve!: (value: Response) => void;
  let signal: AbortSignal | undefined;
  const loader = createSnapshotLoader({ url: "/data/dashboard.json", onChange: state => updates.push(state), fetcher: async (_, init) => {
    signal = init.signal as AbortSignal;
    return new Promise(done => { resolve = done; });
  } });
  const pending = loader.refresh();
  await Promise.resolve();
  const count = updates.length;
  loader.dispose();
  assert.equal(signal?.aborted, true);
  resolve(response());
  await pending;
  assert.equal(updates.length, count);
  await loader.refresh();
  assert.equal(updates.length, count);
});

test("dispose before the queued initial request leaves a fresh loader usable", async () => {
  let calls = 0;
  const make = () => createSnapshotLoader({ url: "/data/dashboard.json", onChange() {}, fetcher: async () => { calls++; return response(); } });
  const old = make();
  const pending = old.refresh();
  old.dispose();
  await pending;
  assert.equal(calls, 0);
  const next = make();
  await next.refresh();
  assert.equal(calls, 1);
  next.dispose();
});
