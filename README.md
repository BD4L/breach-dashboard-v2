# Breach Watch

A recent breach aggregator for research teams, with public notices, explicitly unverified ransomware claims, evidence links, source health, and device-local bookmarks. Python collects records; Astro/React serves static snapshots. The default Latest view prioritizes source dates over historical imports.

[Live dashboard](https://bd4l.github.io/breach-dashboard-v2/) · [Repository](https://github.com/BD4L/breach-dashboard-v2)

This is an isolated successor to the original application, which remains preserved. New clones contain 12 synthetic demo reports; collected state, dependencies, and build output are ignored by Git.

## Run locally

Use Python 3.11+ and Node 22.12+; a supported Node LTS release is preferred.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
npm run dev
```

Open the URL printed by Astro. The demo exercises corrections, unknown counts, uncertain dates, and a failed source retaining earlier records.

From the repository root, collect public sources into a separate local database, or export existing state without fetching again:

```sh
.venv/bin/python -m ingestion.cli collect --source all --db state/live.sqlite --export frontend/public/data/dashboard.json
.venv/bin/python -m ingestion.cli export --db state/live.sqlite --export frontend/public/data/dashboard.json
```

Replace `all` with a source ID from [`ingestion/models.py`](ingestion/models.py) or [`ingestion/source_catalog.py`](ingestion/source_catalog.py). The local CLI runs HTTP collectors sequentially; NH, NJ and SEC also have a separate [Chrome collection command](docs/local-browser-collection.md).

Exit `0` means complete collection, `1` means partial or failed collection with usable data retained, and `2` means a command or storage error. Keep the database: it preserves first-seen times, revisions, and source-run history. Demo and live data cannot share a database. To generate a fresh demo timeline, use a new database filename:

```sh
.venv/bin/python -m ingestion.cli demo --db state/fresh-demo.sqlite --export frontend/public/data/dashboard.json
```

## Verify and build

```sh
.venv/bin/python -m unittest discover -s tests -v
cd frontend
npm test
npm run check
npm run build
cd ..
.venv/bin/python scripts/check_public_boundary.py
```

For the GitHub project site, run `BASE_PATH=/breach-dashboard-v2/ npm run build` from `frontend/`. Static output is in `frontend/dist/`; preview it with the same `BASE_PATH` and `npm run preview`. A local root build needs no base path. The UI uses [Open Props with an Anthropic-inspired palette](docs/design-tokens.md).

## Collection and refresh

GitHub Actions checks all 19 sources every 30 minutes, at minutes 17 and 47 UTC. Up to eight independent collectors run concurrently, with RansomLook and SEC started first. Each worker has a 600-second deadline inside a 12-minute job budget, plus bounded requests and pages. RansomLook has a smaller 60-second metadata budget. Failures do not cancel other sources. NH, NJ and SEC use headed Chrome on standard Ubuntu runners; Wisconsin uses standard macOS; the remaining collectors use HTTP.

SEC discovery checks three UTC calendar days instead of repeatedly scanning a month. The 00:17 UTC scheduled run reconciles 30 days; a manual run can select either window. One bounded retry handles transient SEC server errors. Access denials and rate limits remain visible failures.

Run **Collect public sources and publish** in Actions to collect all sources or one source manually. **Publish preserved public history** rebuilds Pages without scraping. GitHub may delay or drop scheduled runs; this is periodic collection, not guaranteed immediate monitoring. See [GitHub Free limits and storage](docs/github-free.md).

The merge job restores checksummed public history from the `collection-state` branch, applies valid results transactionally, and saves state before building Pages. Missing or failed sources retain prior records. Full revisions remain in durable state; caches contain dependencies and one-day artifacts are transport only. A shared concurrency group serializes collection, history writes, and publication. Partial coverage or a failed source keeps the workflow red even when retained data publishes successfully.

The visible browser checks for a published snapshot every five minutes, when returning to the tab, and on manual refresh. Browser refresh does not trigger collection. Failed refreshes retain the last valid snapshot. The first load includes up to 200 reports; full searches, filters, saved reports, and downloads load the archive on demand. See [snapshot compatibility](frontend/SNAPSHOTS.md).

**Today · official only** resets other filters and shows official notices and filings dated today UTC, excluding unverified claims. Checkbox dropdowns support multiple sources, report types, affected-count ranges and statuses, with Select all and Clear. Choices within one dropdown match any selected option; different dropdowns combine. Search can target organization names, report IDs, summaries, data involved and source names. Source options also have their own search. Selecting no options produces no matches.

## Data meaning and public boundary

- Rows are source reports, not deduplicated incidents. Latest uses the last seven days of source observation/publication/reporting dates; importing an old report does not make it recent. All retains older and undated records.
- Today uses UTC source dates, including the provider's observation time for ransomware claims. It does not establish when a breach occurred or confirm a claim.
- RansomLook contributes public claim metadata only. Claims remain explicitly unverified throughout the UI, RSS, JSON, MCP and alerts. Data is attributed to [RansomLook](https://www.ransomlook.io/about) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with normalization disclosed. No leak dumps, credentials, screenshots or onion content are collected.
- Counts retain their scope and qualifiers; missing counts remain unknown. Corrections create revisions without changing first-seen time. Disappearing source rows are not deleted from history.
- Coverage varies by source and collection window. See the [original-source status audit](docs/source-status-2026-09-07.md), [coverage findings](docs/current-coverage.md), [source rediscovery](docs/collector-rediscovery.md), and [hosted access evidence](docs/source-access-diagnosis.md).
- Everything in the repository and Pages deployment is public. Do not add firm notes, assignments, client data, or credentials. Bookmarks store report IDs in this browser only. `noindex` is not access control.

The public-boundary check validates selected private-field, link, and size constraints; it is not a general secret scanner. The [data contract](docs/data-contract.md) defines record and history semantics. [Verification evidence](docs/verification.md) and the [original baseline](docs/BASELINE.md) record completed checks and preservation boundaries.

## Agent access and alerts

Use the public [RSS feed](https://bd4l.github.io/breach-dashboard-v2/data/recent.xml),
[recent JSON manifest](https://bd4l.github.io/breach-dashboard-v2/data/agent/index.json),
or the small [local MCP connector](agent/README.md). The JSON/MCP feed covers 30
source-dated days and includes publication age and source outcomes.

The [private email worker](docs/alerts.md) uses Resend and a durable Supabase outbox
with verified staff recipients. Preview is offline by default. Production delivery
requires private schema, sender/recipient configuration, repository secrets and an
explicit enable flag. Retire the old email path before enabling the successor to
avoid duplicate notices across the two systems. Recipient details never go to Pages.

Free source feeds can surface claims before official notices, but no earliest-discovery
guarantee is established. Faster paid feeds or remote MCP hosting require a separate
service and suitable data redistribution rights; see [monitoring scope](docs/recent-monitoring.md).
