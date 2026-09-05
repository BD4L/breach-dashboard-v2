# Published snapshots

Ingestion still exports schema 1 to `public/data/dashboard.json`. `npm run build`
copies that complete file unchanged into `dist/data/dashboard.json`, then creates
`dist/data/snapshot.json`. The existing public URL and older dashboard clients
continue to receive the complete schema 1 export. No workflow or ingestion change
is required. The development server can continue using the unsplit source file.

The schema 2 index contains up to 200 whole reports in the dashboard's default
collection-change order, all source outcomes, and count summaries for the entire
export. It stays below 1 MB by reducing the number of included reports when
needed; report evidence and history are never truncated. The full export and
index together must stay below 49 MB, leaving room inside the existing 50 MB site
budget. The index is written atomically after the full file is present.

The frontend requests the index first, falling back to schema 1 only when the
index returns 404. The initial New & updated view labels its loaded subset;
Today and New & updated totals use whole-snapshot summaries evaluated at the
current UTC time. All, Today, Saved, searches, filters and alternate sort orders
require the full export before displaying results. Device bookmarks are retained
even when a saved ID is absent from the current snapshot. Download fetches and
verifies the full export before creating the file.

The index identifies the exact full export by SHA-256, byte length, generation
time and record count. The loader also validates source metadata and initial
report equality. It serializes refresh/archive requests and swaps data and
metadata together. A mixed deployment, stale cache, invalid response or timeout
keeps the previous usable snapshot and exposes a retry. Once a full archive has
loaded, refresh verifies the next archive before replacing it; an unchanged hash
reuses the already verified reports.

`npm test` exercises legacy compatibility, summary accuracy, byte bounds,
filters, archive failures, cancellation, concurrency and atomic refresh.
