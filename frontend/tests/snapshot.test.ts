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

// Split snapshots use a small initial envelope and a hash-verified full archive.
const { readFile } = await import("node:fs/promises");
const { splitSnapshot } = await import("../scripts/split-snapshot.mjs");
const raw = await readFile(new URL("../public/data/dashboard.json", import.meta.url));
const split = splitSnapshot(raw, { recentLimit: 2 });
const initialResponse = () => new Response(split.encoded);
const archiveResponse = () => new Response(split.archive);

test("initial load fetches only bootstrap; full archive loads once, and same-version refresh reuses it", async () => {
  const urls: string[] = [];
  const loader = createSnapshotLoader({url:"/project/data/snapshot.json", onChange() {}, fetcher:async url => {
    urls.push(url); return url.endsWith("/snapshot.json") ? initialResponse() : archiveResponse();
  }});
  await loader.refresh();
  assert.equal(urls.length, 1);
  assert.equal(loader.getState().data?.reports.length, 2);
  assert.equal(loader.getState().index?.totalReports, JSON.parse(raw.toString()).reports.length);
  assert.equal(loader.getState().archiveStatus, "unloaded");
  const [first,second] = await Promise.all([loader.loadArchive(), loader.loadArchive()]);
  assert.equal(first,second);
  assert.equal(urls.length, 2);
  assert.equal(urls[1], `/project/data/${split.archiveName}`);
  assert.equal(loader.getState().archiveStatus, "loaded");
  await loader.refresh();
  assert.equal(urls.length, 3);
  assert.equal(loader.getState().data, first);
  loader.dispose();
});

test("archive corruption retains the usable bootstrap and can be retried", async () => {
  let broken = true;
  const loader = createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async url =>
    url.endsWith("/snapshot.json") ? initialResponse() : broken ? new Response(new Uint8Array(split.archive.byteLength)) : archiveResponse()});
  await loader.refresh();
  const initial = loader.getState().data;
  assert.equal(await loader.loadArchive(), null);
  assert.equal(loader.getState().data, initial);
  assert.equal(loader.getState().archiveStatus, "error");
  assert.match(loader.getState().archiveError, /match/);
  broken = false;
  assert.ok(await loader.loadArchive());
  assert.equal(loader.getState().archiveError, "");
  loader.dispose();
});

test("new-version refresh keeps the old complete snapshot until its matching archive verifies", async () => {
  const changed = JSON.parse(raw.toString());
  changed.generatedAt = "2026-09-06T18:00:00Z";
  changed.reports[0].summary += " Revision two.";
  const next = splitSnapshot(JSON.stringify(changed), {recentLimit:2});
  let useNext = false, fail = true;
  let release!: (response: Response) => void;
  const loader = createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async url => {
    if (url.endsWith("/snapshot.json")) return useNext ? new Response(next.encoded) : initialResponse();
    if (!useNext) return archiveResponse();
    if (fail) return new Response("missing",{status:404});
    return new Promise(done => { release = done; });
  }});
  await loader.refresh(); await loader.loadArchive();
  const old = loader.getState().data;
  const oldId = loader.getState().index?.id;
  useNext = true;
  await loader.refresh();
  assert.equal(loader.getState().data, old);
  assert.equal(loader.getState().index?.id, oldId);
  assert.notEqual(loader.getState().error, "");
  assert.equal(loader.getState().archiveStatus,"loaded");
  fail = false;
  const pending = loader.refresh();
  while (!release) await new Promise(done => setTimeout(done,0));
  assert.equal(loader.getState().data, old);
  release(new Response(next.archive));
  await pending;
  assert.equal(loader.getState().index?.id,next.bootstrap.snapshot.id);
  assert.equal(loader.getState().data?.generatedAt,changed.generatedAt);
  loader.dispose();
});

test("archive request during bootstrap coalesces, and disposal cancels stalled archive body", async () => {
  let release!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  let calls = 0;
  const loader = createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async (_, options) => {
    signal=options.signal as AbortSignal; calls++;
    return calls===1 ? initialResponse() : new Promise(done => {release=done;});
  }});
  const initial=loader.refresh();
  const pending=loader.loadArchive();
  while (!release) await new Promise(done => setTimeout(done,0));
  loader.dispose(); release(archiveResponse());
  await Promise.all([initial,pending]);
  assert.equal(signal?.aborted,true);
  assert.equal(loader.getState().data,null);
});

test("index cannot redirect archives outside its same-origin data directory", async () => {
  const invalid=structuredClone(split.bootstrap);
  invalid.snapshot.archive.url="https://example.invalid/archive.json";
  let calls=0;
  const loader=createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async()=>{calls++;return new Response(JSON.stringify(invalid));}});
  await loader.refresh();
  assert.equal(calls,1);assert.equal(loader.getState().data,null);assert.match(loader.getState().error,/index/);
  loader.dispose();
});

test("archive timeout preserves initial reports, ignores a late body, then permits retry", async () => {
  let stalled=true, finish!: (body: ArrayBuffer) => void;
  let signal: AbortSignal | undefined;
  const loader=createSnapshotLoader({url:"/data/snapshot.json",onChange(){},archiveTimeoutMs:5,fetcher:async (url,options)=>{
    if (url.endsWith("/snapshot.json")) return initialResponse();
    signal=options.signal as AbortSignal;
    return stalled ? {ok:true,arrayBuffer:()=>new Promise(done=>{finish=done;})} as Response : archiveResponse();
  }});
  await loader.refresh();const initial=loader.getState().data;
  await loader.loadArchive();
  assert.equal(signal?.aborted,true);assert.equal(loader.getState().data,initial);
  assert.match(loader.getState().archiveError,/timed out/);
  finish(Uint8Array.from(split.archive).buffer);
  await new Promise(done=>setTimeout(done,0));
  assert.equal(loader.getState().data,initial);
  stalled=false;await loader.loadArchive();assert.equal(loader.getState().archiveStatus,"loaded");
  loader.dispose();
});

test("a valid archive hash cannot pair different source metadata or generation dates", async () => {
  const altered=structuredClone(split.bootstrap);altered.generatedAt="2026-09-06T01:00:00Z";
  const loader=createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async url=>url.endsWith("/snapshot.json")?new Response(JSON.stringify(altered)):archiveResponse()});
  await loader.refresh();assert.equal(await loader.loadArchive(),null);
  assert.match(loader.getState().archiveError,/different snapshot/);
  assert.equal(loader.getState().data?.reports.length,2);
  loader.dispose();
});

test("old deployments and development servers fall back to full schema1 only on a missing index", async () => {
  const urls:string[]=[];
  const loader=createSnapshotLoader({url:"/project/data/snapshot.json",onChange(){},fetcher:async url=>{
    urls.push(url);return url.endsWith("/snapshot.json")?new Response("missing",{status:404}):response();
  }});
  await loader.refresh();
  assert.deepEqual(urls,["/project/data/snapshot.json","/project/data/dashboard.json"]);
  assert.equal(loader.getState().archiveStatus,"loaded");assert.equal(loader.getState().index,null);
  loader.dispose();
  let calls=0;
  const invalid=createSnapshotLoader({url:"/data/snapshot.json",onChange(){},fetcher:async()=>{calls++;return new Response("bad json");}});
  await invalid.refresh();assert.equal(calls,1);assert.equal(invalid.getState().data,null);
  invalid.dispose();
});
