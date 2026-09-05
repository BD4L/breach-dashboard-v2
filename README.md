# Breach Watch — local pilot

A static public-source review dashboard for a law firm's breach research. This isolated repository replaces the original dashboard's large summary cards with a searchable report table, evidence details, changed-field history, source health, and device-local bookmarks. A Python collector retains source records and revisions in local SQLite, then exports a public JSON snapshot for Astro/React.

**Local first.** No Git remote, production connection, deployment, email, or AI service is configured. The eventual GitHub owner is **BD4L**. The original application and its uncommitted work are preserved; see [baseline](docs/BASELINE.md).

This prepared checkout also has a built preview of the 1,033-report live smoke snapshot: run `cd frontend && npm run preview -- --port 4326` and open `http://127.0.0.1:4326`. The source default remains the synthetic demo; another build replaces the prepared preview with the currently selected export.

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

Select `massachusetts`, `hhs`, or `california` instead of `all` to refresh one source. Collection is sequential, bounded, and stops on access denial or rate limits. On this Mac, the successful live smoke run used the trusted system CA bundle:

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

For a future GitHub project site, build with its actual base path:

```sh
cd frontend
BASE_PATH=/breach-dashboard-v2/ npm run build
npm run preview
```

The static output is `frontend/dist/`. Use the same `BASE_PATH` when previewing a build that requires it. A local root build needs no `BASE_PATH`. The included GitHub workflow only validates code and the public boundary; it neither collects data nor publishes a site.

The UI uses the locally bundled [Open Props token pack](docs/design-tokens.md). Color, typography, spacing, and interaction decisions live in `frontend/src/styles/tokens.css`; component styles consume semantic roles from that file.

## Data meaning and current coverage

- Rows are **source reports**, not deduplicated incidents. A first collection marks historical reports as newly observed; “new” does not establish a recent breach date.
- Counts retain their source scope and qualifiers. Massachusetts counts are state residents; a federal portal count is labeled “reported” unless a stronger scope is supported. Missing counts remain unknown and stay in the default view.
- Source corrections create a new revision while preserving first-seen time. The detail pane shows changed fields and before/after values. The fingerprint describes normalized fields, not an archived document.
- HHS covers **HIPAA Under Investigation**, including pagination. Archived cases and Part 2 reports are outside this adapter.
- California currently takes six listing pages, up to 300 reports. Older reports are outside that bounded window, so coverage is explicitly partial. Counts and notice enrichment absent from the listing remain unknown.
- Massachusetts discovers current/prior-year annual reports. Its parser is fixture-tested, but the live index returned HTTP 403 during this pilot. Real PDF fidelity remains unverified until an accessible current report can be tested. Even a parsed PDF remains partial until an independent annual report count is validated; table/text agreement alone does not prove completeness. There is no access-control workaround.

These are public research records. Source links support review; the dashboard does not establish legal deadlines or automatically merge organizations. It does not remove reports merely because they disappear from a source's current listing.

## Public/private boundary

Everything in a Pages deployment and a public repository is public. This pilot publishes source fields only. It has no firm notes, assignments, client data, credentials, authenticated workspace, or private API. Bookmarks store report IDs in this browser only, without cross-device or team synchronization. `noindex` is a search hint, not access control.

Local state, build output, dependencies, and environment files are ignored by Git. The boundary check catches selected production references, private field names, unsafe report links, and size-budget violations; it is not a general secret scanner or an authorization system.

See [GitHub Free constraints and next-stage design](docs/github-free.md) and [verification evidence](docs/verification.md) before enabling unattended collection or publishing.
