# Collector and runner repair

Reviewed September 5, 2026. Changes apply only to the public successor repository. The original application, its database, schedules, and email integrations are unchanged.

## Why the old workflow could look green

The [original parallel run](https://github.com/BD4L/Breaches/actions/runs/33986568190) marked every collector step successful despite HTTP errors, missing table headers, zero parsed records, invalid dates, and duplicate database inserts. The [California run on September 2](https://github.com/BD4L/Breaches/actions/runs/33617352040) spent 330 minutes in a successful scraper job, then failed in its database summary. Its timeout/page environment variables were not read by the scraper. A later [California run](https://github.com/BD4L/Breaches/actions/runs/33977505992) swallowed a CSV timeout and exited successfully.

The replacement does not reuse those main functions or their shared database clients. Public adapters return structured records. An isolated supervisor enforces a wall-clock deadline, including parser time, and emits either a collection or an explicit error artifact. Sources execute in independent matrix jobs with `fail-fast: false`. A single merge job validates counts/identities, applies each source transactionally, and publishes retained records even if another source is unavailable. New/changed counts come from that source's actual writes, not a global before/after database count.

## Coverage and source-specific changes

| Source ID | Repair and coverage boundary |
|---|---|
| `california` | Verified listing pagination through the actual terminal page; default budget 120 pages replaces six. No routine per-report PDF enrichment. Missing IDs or conflicting rows remain explicit rejections. |
| `hhs` | Uses the actual JSF navigation and named headers; validates page offsets, total counts, and selected HIPAA Under Investigation tab. Archived/Part 2 records are outside this source view. |
| `massachusetts` | Discovers current/prior-year official reports and parses the current `15-Jul-26` date format. Official index/report returned 403; actual current PDF extraction remains unverified and unavailable. |
| `indiana` | Discovers the actual 2026 annual PDF instead of hardcoding 2025; parses named columns and validates page/text row agreement. Counts are Indiana residents. Consumer notification dates are not mislabelled as publication dates. Annual scope remains partial; derived identities have an explicit caveat. |
| `iowa` | Discovers current/prior linked annual notices and validates named table columns. Ordinary official access returned 403; live parser fidelity is unverified. |
| `maine` | Uses the current official page and detects its explicit statement that the public database is offline while reporting abuse is reviewed. This is an unavailable source, not an empty successful collection. |
| `north_dakota` | Rejects the old endpoint's 404 and validates any returned page as an actual notice directory. No current replacement public directory was verified. |
| `oklahoma` | Reads the JSON feed used by the current official page. Scope is Oklahoma state-government cybersecurity incidents, not comprehensive private-company breach filings. |
| `maryland` | Discovers annual list names from the current page and reads its anonymous public-list JSON with pagination. Current page advertises historical years through 2025; no 2026 list was verified, so coverage stays partial. |
| `new_jersey` | Rejects the HTTP 200 challenge response as unavailable. It does not mistake a challenge page for an empty listing. |
| `wisconsin` | Replaces the table assumption with the actual labelled-prose records. Historical archives remain outside the current-page scope. |
| `montana` | Reads the full published listing once, uses native row IDs, and relies on idempotent local upserts. Avoids thousands of duplicate-key failures and per-notice enrichment. |
| `washington` | Follows the actual Drupal paginator, uses notice identities, and preserves revisions. It no longer silently stops at 50 rows. |
| `south_carolina` | Normalizes the observed `12/19,2024` separator typo with an evidence flag. Conflicting records sharing an identity are withheld and counted, without crashing storage or choosing a count. |
| `delaware` | Handles annotated dates conservatively, ignores blank formatting rows, and preserves ambiguous dates as unknown with evidence flags. |
| `new_hampshire` | Uses the official listing; 403 remains an explicit failure. No Firebase dependency, guessed ten-document fallback, or search-service credential. |
| `texas` | Uses the same anonymous Visualforce read action invoked by the official page. Processes all 625 returned current-version reports with Salesforce IDs; no date-sort click or 50-row browser truncation. Only fields rendered in the public table are normalized. |
| `sec` | Uses accession IDs and actual filing-document links for Item 1.05; no mandatory XBRL or guessed document URL. Recent-feed scope is bounded to 200 filings. Uses the honest project identity without a contact address, as requested. Ordinary SEC access returned 403; parsing is fixture-tested, not live-proven. |

Hawaii and Vermont were also inspected in the original logs. Zero new inserts alone did not establish a failed scraper: Hawaii's date filter excluded its 55 parsed rows, and Vermont's 493 parsed rows were skipped without parser/fetch errors. These two sources are not migrated into the successor's 18-source repair set. They should be verified for freshness before a future coverage expansion.

An unavailable source cannot be made healthy through an error-code change. Source access and publication policy can change; the next scheduled run rechecks ordinary official access. No challenge solving, proxy bypass, disabled TLS validation, or private data service is used.

## Persistence and failure boundaries

- `collection-state` retains normalized records, full immutable revisions, source runs, and retrieval metrics. Its checksum manifest validates restore on a fresh runner. A missing/corrupt state archive fails instead of starting a new history.
- Source artifacts are transport with one-day retention. Dependency caches are disposable. Neither is the collection history store.
- Database writes are serialized by workflow concurrency and a single merge process. A source correction preserves its first-seen timestamp; identical data does not create a revision. Missing source rows never delete historical records.
- State is persisted before building. A failed build/deployment preserves collected history. A source failure keeps the workflow visibly incomplete while allowing successful data and current health to deploy.
- Source workers have a 600-second hard deadline, jobs a 12-minute cap, and at most three source jobs run concurrently. Manual and four-hour scheduled runs cannot overlap their durable writes.
- Routine collection and optional enrichment are separate. The workflow has no AI, subscriber email, global database summary, or pre-collection database snapshot dependency.

Snapshot data is compact JSON, with a 40 MB public snapshot and 50 MB site budget. Full state has explicit per-file and aggregate size guards. Reaching a guard requires a reviewed archival change; records are never silently discarded.
