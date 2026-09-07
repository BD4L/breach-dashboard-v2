import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DAY, readDataset, signalTime } from "../src/lib/dashboard.ts";

export const FEED_DAYS = 30;
export const FEED_BUDGET = 4_000_000;
export const MANIFEST_BUDGET = 128_000;
const xml = value => String(value).replace(/[<>&"']/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c]);

export function makeAgentFeed(value) {
  const full = readDataset(value);
  if (full.sources.some(s => s.id === "ransomlook" && (!s.attribution ||
      s.attribution.name !== "RansomLook" || s.attribution.license !== "CC BY 4.0" ||
      s.attribution.url !== "https://www.ransomlook.io/" ||
      s.attribution.licenseUrl !== "https://creativecommons.org/licenses/by/4.0/" ||
      !s.attribution.changes.trim()))) {
    throw new Error("RansomLook attribution is required before publishing its metadata feed or RSS.");
  }
  const now = Date.parse(full.generatedAt);
  const reports = full.reports.filter(r => signalTime(r) >= now - FEED_DAYS * DAY && signalTime(r) <= now)
    .sort((a, b) => signalTime(b) - signalTime(a) || a.id.localeCompare(b.id));
  const pages = [];
  let bytes = 0;
  for (let offset = 0; offset < reports.length;) {
    let count = Math.min(100, reports.length - offset);
    let body;
    do {
      body = Buffer.from(JSON.stringify({ schemaVersion: 1, mode: full.mode, generatedAt: full.generatedAt,
        sources: full.sources, reports: reports.slice(offset, offset + count) }));
      if (body.length <= 500_000 || count === 1) break;
      count = Math.max(1, Math.floor(count / 2));
    } while (true);
    if (body.length > 500_000) throw new Error("A report exceeds the agent page budget; publication stopped without dropping evidence.");
    const hash = createHash("sha256").update(body).digest("hex");
    pages.push({ body, descriptor: { url: `${hash}.json`, sha256: hash, bytes: body.length, count } });
    bytes += body.length;
    offset += count;
  }
  const manifest = { schemaVersion: 1, mode: full.mode, generatedAt: full.generatedAt,
    scope: { days: FEED_DAYS, since: new Date(now - FEED_DAYS * DAY).toISOString(),
      dateBasis: "sourceObservedAt, otherwise publishedDate, otherwise reportedDate; collection time is not a breach date" },
    totalReports: reports.length, sources: full.sources, pages: pages.map(p => p.descriptor) };
  const encoded = Buffer.from(JSON.stringify(manifest));
  if (encoded.length > MANIFEST_BUDGET || encoded.length + bytes > FEED_BUDGET || pages.length > 100) {
    throw new Error("Recent agent feed exceeds its bounded size; publication stopped without truncating results.");
  }
  const items = reports.slice(0, 100).map(r => {
    const claim = r.signalType === "ransomware_claim";
    const source = full.sources.find(s => s.id === r.sourceId);
    const attribution = source?.attribution;
    const description = [claim ? "Unverified ransomware group claim." : "Public source report; not a distinct-incident count.",
      r.summary, attribution ? `Source: ${attribution.name} (${attribution.url}), ${attribution.license} (${attribution.licenseUrl}). ${attribution.changes}` : ""].filter(Boolean).join(" ");
    return `<item><title>${xml(`${claim ? "Unverified claim: " : ""}${r.organization}`)}</title><link>${xml(r.sourceUrl)}</link><guid isPermaLink="false">${xml(`${r.id}:revision:${r.revision}`)}</guid><pubDate>${new Date(signalTime(r)).toUTCString()}</pubDate><description>${xml(description)}</description></item>`;
  }).join("");
  const rss = `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Breach Watch recent reports and claims</title><link>https://bd4l.github.io/breach-dashboard-v2/</link><description>Latest 100 source-dated reports in the last 30 days. Ransomware claims are unverified. Times describe public reporting or source observation, not necessarily when a breach happened.</description><lastBuildDate>${new Date(now).toUTCString()}</lastBuildDate>${items}</channel></rss>`;
  return { manifest, encoded, pages, rss };
}

export async function publishAgentFeed(path) {
  const result = makeAgentFeed(JSON.parse(await readFile(path, "utf8")));
  const directory = join(dirname(path), "agent");
  await rm(directory, { recursive: true, force: true });
  await mkdir(directory, { recursive: true });
  for (const page of result.pages) await writeFile(join(directory, page.descriptor.url), page.body);
  await writeFile(join(directory, "index.json"), result.encoded);
  await writeFile(join(dirname(path), "recent.xml"), result.rss);
  return result;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await publishAgentFeed(resolve(process.argv[2] || "dist/data/dashboard.json"));
  console.log(`Agent feed: ${result.manifest.totalReports} recent reports in ${result.pages.length} verified pages.`);
}
