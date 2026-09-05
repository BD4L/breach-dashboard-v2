# Breach Watch

A static public-source review dashboard for a law firm's breach research. This isolated repository replaces the original dashboard's large summary cards with a searchable report table, evidence details, changed-field history, source health, and device-local bookmarks. A Python collector retains source records and revisions in local SQLite, then exports a public JSON snapshot for Astro/React.

**Live dashboard:** [Breach Watch](https://bd4l.github.io/breach-dashboard-v2/).

**Repository:** [BD4L/breach-dashboard-v2](https://github.com/BD4L/breach-dashboard-v2). This is the isolated successor repository. The original application is preserved; see [baseline](docs/BASELINE.md). GitHub Actions validates changes and runs independent public collectors every four hours, with manual dispatch. The collection workflow persists history to `collection-state` and explicitly deploys snapshots to GitHub Pages.

New clones start with 12 synthetic demo reports. Public-source collection is available through the CLI below; collected state and locally built previews are ignored by Git.

## Run locally

Use Python 3.11+ and Node 22.12+ (a supported Node LTS release is preferred).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Astro. The checked-in dataset contains 12 **synthetic examples**, with a prominent demo label. It exercises revisions, unknown counts, questionable dates, and a failed source retaining earlier records. Dates belong to the original seed time, so the source status will correctly become stale as the fixture ages.

The following commands run from the repository root. Use a new database filename to regenerate the demo with a fresh timeline:

```sh
.venv/bin/python -m ingestion.cli demo --db state/fresh-demo.sqlite --export frontend/public/data/dashboard.json
```

Collect public sources into a separate durable local database:

```sh
.venv/bin/python -m ingestion.cli collect --source all --db state/live-pilot.sqlite --export frontend/public/data/dashboard.json
```

Select a source ID instead of `all` to refresh one source. The local CLI supervises one isolated process at a time; Actions runs up to three independent source jobs concurrently. Each worker has a hard 600-second deadline covering fetching and parsing, plus request, response-size, and page limits. Access denial and rate limits stop a source immediately. `--timeout` and `--max-pages` explicitly override supported limits. On this Mac, the successful live smoke run used the trusted system CA bundle:

```sh
REQUESTS_CA_BUNDLE=/etc/ssl/cert.pem .venv/bin/python -m ingestion.cli collect --source hhs --db state/live-pilot.sqlite --export frontend/public/data/dashboard.json
```

Only set that variable when the file is the appropriate trusted CA bundle for your machine. TLS verification remains enabled.

Exit `0` means all requested sources completed, `1` means at least one source failed or was partial, and `2` means a command/storage error. Exit `1` still exports valid collected and retained data with the source failures visible. Demo seeding intentionally includes a simulated source failure and exits successfully.

Export an existing database without another network request:

```sh
.venv/bin/python -m ingestion.cli export --db state/live-pilot.sqlite --export frontend/public/data/dashboard.json
```

To return to the original demo, export `state/preview.sqlite` if using the prepared local checkout, or seed a new demo database. Demo/live mode cannot be mixed within one database. Keep the SQLite files: they preserve first-seen times, revisions, and source-run history. Deleting the database starts a new observation history.

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

For the GitHub project site, build with its base path:

```sh
cd frontend
BASE_PATH=/breach-dashboard-v2/ npm run build
npm run preview
```

The static output is `frontend/dist/`. Use the same `BASE_PATH` when previewing a build that requires it. A local root build needs no `BASE_PATH`. The read-only validation workflow checks code and the public boundary. The separate collection workflow merges public data and deploys the static build.

The UI uses the locally bundled [Open Props token pack](docs/design-tokens.md) with an Anthropic-inspired brand palette. Color roles, typography, spacing, and interaction decisions live in `frontend/src/styles/tokens.css`; the three brand primitives live in `frontend/src/lib/theme.ts`.

## Today counter and refresh

The top-bar counter means source reports published today in **UTC**, using the reported-to-source date only when publication date is absent. It does not count historical reports merely imported today, establish when an actual breach occurred, or deduplicate incidents across sources. Select the counter to review its reports.

While visible, the browser checks the same-origin JSON snapshot every five minutes, checks again when you return to the tab, and supports manual refresh. This refreshes a published snapshot; it does not run the collector. The snapshot timestamp and source-health state remain visible, and a failed refresh retains the last valid data. For a new source collection, run **Collect public sources and publish** in GitHub Actions, selecting `all` or one source ID. The public browser never receives an administrative token.

## Data meaning and current coverage

- Rows are **source reports**, not deduplicated incidents. A first collection marks historical reports as newly observed; “new” does not establish a recent breach date.
- Counts retain their source scope and qualifiers. Massachusetts counts are state residents; a federal portal count is labeled “reported” unless a stronger scope is supported. Missing counts remain unknown and stay in the default view.
- Source corrections create a new revision while preserving first-seen time. The detail pane shows changed fields and before/after values. The fingerprint describes normalized fields, not an archived document.
- HHS covers **HIPAA Under Investigation**, including pagination. Archived cases and Part 2 reports are outside this adapter.
- California follows the listing through its verified last page, with a configurable 120-page default budget. A September 5 run fetched 106 pages / 5,295 rows in about a minute; malformed or conflicting rows are reported separately. Counts and notice enrichment absent from the listing remain unknown.
- Massachusetts collects the current/prior-year annual PDFs: 3,705 verified rows in the September 5 recovery. Independent ID-column extraction checks each page, including observed table-border and wrapped-ID problems. Earlier years are outside this collection window. Letter fallback can add new identities without replacing richer stored evidence.

These are public research records. Source links support review; the dashboard does not establish legal deadlines or automatically merge organizations. It does not remove reports merely because they disappear from a source's current listing.

## Public/private boundary

Everything in a Pages deployment and a public repository is public. This pilot publishes source fields only. It has no firm notes, assignments, client data, credentials, authenticated workspace, or private API. Bookmarks store report IDs in this browser only, without cross-device or team synchronization. `noindex` is a search hint, not access control.

Local state, build output, dependencies, and environment files are ignored by Git. The boundary check catches selected production references, private field names, unsafe report links, and size-budget violations; it is not a general secret scanner or an authorization system.

See [collector coverage and repair evidence](docs/collector-repair.md), [GitHub Free constraints](docs/github-free.md), and [verification evidence](docs/verification.md).

## Independent collection and durable history

Source IDs: `massachusetts`, `hhs`, `california`, `indiana`, `iowa`, `maine`, `north_dakota`, `oklahoma`, `maryland`, `new_jersey`, `wisconsin`, `montana`, `washington`, `south_carolina`, `delaware`, `new_hampshire`, `texas`, `sec`. Coverage and known external failures are documented per source; having an adapter does not mean a source is currently accessible.

The schedule is `:17` every four hours in UTC. GitHub can delay or drop scheduled runs. Manual and scheduled collection share one concurrency group, so durable writes cannot overlap. Each source job has a 12-minute Actions cap and a 10-minute worker deadline; one source's failure does not cancel another. Collector jobs have no database credentials or write permission.

NH, NJ and SEC use the ordinary headed Chrome collector in separate standard Ubuntu jobs. Full hosted collections verified 747 NH reports across 30 pages, all 56 NJ notices across four pages, and SEC's complete 5,425-hit rolling search window. Only those jobs install browser dependencies; the remaining 15 sources use HTTP and Wisconsin retains its standard macOS runner. Collection keeps the existing page/window limits and reports partial coverage explicitly. See [hosted collection proof](docs/source-access-diagnosis.md#full-hosted-collection-and-publication).

A separate merge job downloads source results, restores public state from the `collection-state` branch, and applies valid records transactionally. Missing, malformed, empty, or failed results retain previous records and record a failure. Only an explicitly validated empty filtered feed may report no matches. A failed source or partial coverage keeps the workflow red, while the deploy job can still publish retained data and current source health. A summary service, email service, or pre-run database snapshot is never a prerequisite for collection.

The state branch contains JSON Lines tables with full revisions and observation history, plus a checksum manifest. Restore rejects missing/corrupt history instead of silently resetting the database. Actions artifacts expire after one day and are only transport; caches hold dependencies. State is committed before the Pages build so a deployment failure cannot lose successful collection. Per-file/state size guards stop publication instead of deleting old history. All persisted state is public normalized source data.

For an isolated source artifact without touching a database:

```sh
.venv/bin/python -m ingestion.runner fetch --source california --output state/results/california.json --timeout 600
```

Listing collection is separate from optional document enrichment: routine runs do not download every notice PDF, invoke AI, or fetch SEC XBRL. Indiana and Massachusetts use their annual source reports because those documents are the listings themselves.

Current recovery evidence and source limitations: [September 5 source rediscovery](docs/collector-rediscovery.md).

The follow-up [current-coverage investigation](docs/current-coverage.md) records the initial local recovery and remaining publisher limitations. The later [source access diagnosis](docs/source-access-diagnosis.md) established that the same browser collector can reach NH, NJ and SEC on standard GitHub runners. The manual **Publish preserved public history** workflow can rebuild Pages from verified `collection-state` history without running the scrapers or changing recorded source outcomes.

Optional [local Chrome collection](docs/local-browser-collection.md) produces independent NH, NJ and SEC result envelopes without changing GitHub or scheduling a background job.

[Source access diagnosis](docs/source-access-diagnosis.md) distinguishes publisher denials from runner timeouts and compares the same bounded browser client on local and standard GitHub runners. The manual diagnostic's `matched-browser` mode collects first-page metadata only and does not publish or change history.

The dashboard initially loads up to 200 complete reports from a small snapshot index. Counts describe the whole published snapshot; the report list explicitly identifies its loaded subset. All reports, search, filters, saved records and full download fetch and validate the complete archive on demand. The original full JSON URL remains compatible. See [snapshot loading and compatibility](frontend/SNAPSHOTS.md).
