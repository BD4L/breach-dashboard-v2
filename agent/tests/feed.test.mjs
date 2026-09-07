import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer as httpServer } from "node:http";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { fileURLToPath } from "node:url";
import { makeAgentFeed, MANIFEST_BUDGET } from "../../frontend/scripts/publish-agent-feed.mjs";
import { FeedClient, MAX_REPORT_OUTPUT_BYTES } from "../feed-client.mjs";

const demo = JSON.parse(await readFile(new URL("../../frontend/public/data/dashboard.json", import.meta.url)));
const NOW = Date.parse("2026-09-07T18:00:00Z");
function fixture(count = 105, now = NOW) {
  const generatedAt = new Date(now).toISOString();
  return { ...structuredClone(demo), mode: "live", generatedAt,
    reports: Array.from({ length: count }, (_, i) => ({ ...structuredClone(demo.reports[0]), id: `test-${String(i).padStart(3, "0")}`,
      organization: `Synthetic ${i}`, publishedDate: generatedAt.slice(0, 10), firstSeen: generatedAt,
      lastSeen: generatedAt, lastChanged: generatedAt })) };
}
function setup(dataset = fixture(), transform = (bytes) => bytes) {
  let feed = makeAgentFeed(dataset);
  const requests = [];
  const client = new FeedClient({ url: "https://example.com/data/agent/index.json", now: () => NOW,
    fetcher: async (url, options) => {
      requests.push(String(url));
      assert.equal(options.redirect, "error");
      const name = new URL(url).pathname.split("/").at(-1);
      const bytes = name === "index.json" ? feed.encoded : feed.pages.find(p => p.descriptor.url === name)?.body;
      return new Response(bytes ? transform(bytes, name) : "missing", { status: bytes ? 200 : 404 });
    } });
  return { client, requests, feed, replace: value => { feed = makeAgentFeed(value); } };
}

test("publication excludes old imports, undated records and future source observations", () => {
  const value = fixture(4);
  value.reports[1].publishedDate = "2020-01-01";
  value.reports[2].publishedDate = null;
  value.reports[3].publishedDate = "2026-09-08";
  const feed = makeAgentFeed(value);
  assert.equal(feed.manifest.totalReports, 1);
  assert.equal(feed.pages.length, 1);
  assert.match(feed.rss, /Synthetic 0/);
  assert.doesNotMatch(feed.rss, /Synthetic [123]/);
});

test("filtered pagination has stable IDs and bounded reads", async () => {
  const { client, requests } = setup();
  const first = await client.list({ limit: 100 });
  const second = await client.list({ limit: 100, cursor: first.nextCursor });
  assert.equal(first.count, 100);
  assert.equal(second.count, 5);
  assert.equal(second.nextCursor, null);
  assert.equal(new Set([...first.reports, ...second.reports].map(r => r.id)).size, 105);
  assert.equal(requests.filter(url => !url.endsWith("index.json")).length, 2);
  assert.equal((await client.list({ query: "Synthetic 104" })).count, 1);
});

test("source health does not download report pages", async () => {
  const { client, requests } = setup();
  const value = await client.sources();
  assert.equal(value.stale, false);
  assert.equal(value.sources.length, demo.sources.length);
  assert.equal(requests.length, 1);
});

test("cursors reject changed filters and generations", async () => {
  const { client, replace } = setup();
  const first = await client.list({ limit: 1 });
  await assert.rejects(client.list({ query: "different", cursor: first.nextCursor }), /Cursor/);
  replace(fixture(104));
  await assert.rejects(client.list({ cursor: first.nextCursor }), /Cursor/);
});

test("default date window remains fixed across pagination as wall time advances", async () => {
  const value = fixture(2);
  value.reports[1].publishedDate = "2026-08-31";
  // Provider timestamps permit an exact seven-day boundary independent of midnight.
  value.reports[1].sourceObservedAt = new Date(NOW - 7 * 86_400_000).toISOString();
  const { client } = setup(value);
  const first = await client.list({ limit: 1 });
  client.now = () => NOW + 60_000;
  const second = await client.list({ limit: 1, cursor: first.nextCursor });
  assert.equal(second.count, 1);
  assert.equal(second.reports[0].id, value.reports[1].id);
});

test("tampered pages fail integrity verification", async () => {
  const { client } = setup(fixture(), (bytes, name) => name === "index.json" ? bytes : Buffer.from(bytes.toString().replace("Synthetic", "Tampered!")));
  await assert.rejects(client.list(), /inconsistent/);
});

test("manifest rejects paths outside hashed sibling pages and excessive sizes", async () => {
  for (const change of [m => { m.pages[0].url = "https://attacker.invalid/"; }, m => { m.pages[0].bytes = 500_001; }]) {
    const { client } = setup(fixture(), (bytes, name) => {
      if (name !== "index.json") return bytes;
      const m = JSON.parse(bytes); change(m); return Buffer.from(JSON.stringify(m));
    });
    await assert.rejects(client.sources(), /inconsistent/);
  }
});

test("publisher rejects a manifest that its reader cannot accept", () => {
  const value = fixture(0);
  value.sources[0] = { ...value.sources[0], message: "x".repeat(MANIFEST_BUDGET) };
  assert.throws(() => makeAgentFeed(value), /bounded size/);
});

test("source-date limits and empty feeds are explicit", async () => {
  const { client } = setup(fixture(0));
  assert.equal((await client.list()).count, 0);
  await assert.rejects(client.list({ since: "2020-01-01T00:00:00Z" }), /30-day/);
  await assert.rejects(client.get("missing"), /not found/);
  await assert.rejects(client.list({ sourceId: "invented" }), /Unknown sourceId/);
  await assert.rejects(client.list({ limit: 101 }), /limit/);
});

test("claims keep classification, attribution and escaped RSS content", async () => {
  const value = fixture(1);
  value.sources.push({ ...demo.sources[0], id: "ransomlook", label: "RansomLook",
    attribution: { name: "RansomLook", url: "https://www.ransomlook.io/", license: "CC BY 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/", changes: "Metadata normalized; claims unverified." } });
  Object.assign(value.reports[0], { sourceId: "ransomlook", signalType: "ransomware_claim",
    sourceObservedAt: "2026-09-07T17:00:00Z", organization: "Synthetic <claim> & company" });
  const { client, feed } = setup(value);
  const row = (await client.list()).reports[0];
  assert.equal(row.classification, "Unverified ransomware claim");
  assert.equal(row.attribution.license, "CC BY 4.0");
  assert.match(feed.rss, /Unverified claim: Synthetic &lt;claim&gt; &amp; company/);
  assert.match(feed.rss, /creativecommons.org/);
  assert.equal((await client.get(row.id)).source.id, "ransomlook");
});

test("RansomLook attribution is required both before publication and when reading a feed", async () => {
  const value = fixture(1);
  const source = { ...demo.sources[0], id: "ransomlook", label: "RansomLook",
    attribution: { name: "RansomLook", url: "https://www.ransomlook.io/", license: "CC BY 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/", changes: "Metadata normalized; claims unverified." } };
  value.sources = [...value.sources, source];
  Object.assign(value.reports[0], { sourceId: "ransomlook", signalType: "ransomware_claim", sourceObservedAt: "2026-09-07T17:00:00Z" });
  for (const attribution of [undefined, { ...source.attribution, license: "Unknown" },
                             { ...source.attribution, changes: "" }]) {
    const invalid = { ...value, sources: value.sources.map(s => s.id === "ransomlook" ? { ...s, attribution } : s) };
    assert.throws(() => makeAgentFeed(invalid), /attribution/);
    const { client } = setup(value, (bytes, name) => {
      if (name !== "index.json") return bytes;
      const manifest = JSON.parse(bytes);
      manifest.sources.find(s => s.id === "ransomlook").attribution = attribution;
      return Buffer.from(JSON.stringify(manifest));
    });
    await assert.rejects(client.sources(), /inconsistent/);
  }
});

test("report details bound output, explicitly count omitted history, and preserve cached evidence", async () => {
  const value = fixture(1);
  value.reports[0].history = Array.from({ length: 8 }, (_, i) => ({
    observedAt: new Date(NOW - i * 60_000).toISOString(), changedFields: ["summary"],
    changes: [{ field: "summary", before: "x".repeat(12_000), after: "y".repeat(12_000) }],
  }));
  const { client } = setup(value);
  const result = await client.get(value.reports[0].id);
  assert.ok(Buffer.byteLength(JSON.stringify(result)) <= MAX_REPORT_OUTPUT_BYTES);
  assert.ok(result.omittedHistoryEntries > 0);
  assert.equal(result.report.history.length + result.omittedHistoryEntries, 8);
  assert.equal(result.report.history[0].observedAt, value.reports[0].history[0].observedAt);
  assert.equal([...client.pages.values()][0][0].history.length, 8);
});

test("oversized report core returns a bounded actionable error", async () => {
  const value = fixture(1);
  value.reports[0].summary = "x".repeat(MAX_REPORT_OUTPUT_BYTES);
  const { client } = setup(value);
  await assert.rejects(client.get(value.reports[0].id), error => {
    assert.match(error.message, /64 KB.*original source or dashboard/);
    assert.ok(error.message.length < 2_500);
    return true;
  });
});

test("real stdio MCP protocol initializes, lists read-only tools, calls tools and rejects invalid input", async () => {
  const value = fixture(105, Date.now());
  value.reports.forEach(report => { report.organization = report.organization.repeat(90); });
  const feed = makeAgentFeed(value);
  const server = httpServer((req, res) => {
    const name = req.url.split("/").at(-1);
    const body = name === "index.json" ? feed.encoded : feed.pages.find(p => p.descriptor.url === name)?.body;
    res.writeHead(body ? 200 : 404, { "Content-Type": "application/json" }); res.end(body ?? "{}");
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const transport = new StdioClientTransport({ command: process.execPath,
    args: ["--experimental-strip-types", fileURLToPath(new URL("../server.mjs", import.meta.url))],
    env: { BREACH_FEED_URL: `http://127.0.0.1:${server.address().port}/index.json` }, stderr: "pipe" });
  const client = new Client({ name: "offline-test", version: "1.0.0" });
  try {
    await client.connect(transport);
    const { tools } = await client.listTools();
    assert.equal(tools.length, 3);
    assert.ok(tools.every(t => t.annotations.readOnlyHint && !t.annotations.destructiveHint));
    const result = await client.callTool({ name: "breaches_list_recent", arguments: { limit: 1 } });
    assert.equal(result.isError, undefined);
    assert.equal(result.structuredContent.count, 1);
    const oversized = await client.callTool({ name: "breaches_list_recent", arguments: { limit: 100 } });
    assert.equal(oversized.isError, true);
    assert.match(oversized.content[0].text, /64 KB/);
    const invalid = await client.callTool({ name: "breaches_list_recent", arguments: { limit: 101 } });
    assert.equal(invalid.isError, true);
    const sources = await client.callTool({ name: "breaches_list_sources", arguments: {} });
    assert.equal(sources.structuredContent.sources.length, demo.sources.length);
  } finally {
    await client.close();
    await new Promise(resolve => server.close(resolve));
  }
});
