# Data contract

The executable contracts are [`Report` and `Collection`](../ingestion/models.py), [record validation](../ingestion/validation.py), [SQLite storage and export](../ingestion/store.py), and [frontend types](../frontend/src/lib/dashboard.ts).

## Collection

Adapters return a `Collection` containing normalized `Report` records, parsed/rejected counts, coverage information, and bounded retrieval evidence. They do not write the database. The source registry is `SOURCES` in `ingestion/models.py`, extended by `ingestion/source_catalog.py` and `ingestion/additional_sources.py`. `ACTIVE_SOURCE_IDS` excludes reference-only entries from routine collection.

Source errors must not become empty successful results. An empty filtered feed is accepted only when explicitly validated with `empty_is_valid`. Partial collections retain valid records and report their limits. Sparse secondary listings can set `new_records_only` to add identities without overwriting richer stored evidence.

Dates use `YYYY-MM-DD` or null. Native IDs identify individual source reports, not a shared annual document. Counts retain scope (`state`, `national`, `reported`, `unknown`) and qualifier (`exact`, `at_least`, `less_than`, `unknown`). Missing values stay unknown; reported dates do not imply breach dates, and state counts do not imply national totals.

RansomLook records require `signal_type=ransomware_claim` and an aware
`source_observed_at` timestamp no later than collection time. These export as
`signalType` and `sourceObservedAt`; absence on existing official reports preserves
their previous normalized hashes. Claim IDs derive from group, title and full
provider discovery timestamp because the metadata endpoint supplies no stable ID.
Source metadata carries attribution, license links and a normalization notice.

Source category is `official` (the default for legacy state/federal entries), `claims`, `secondary`, or `reference`. Claims require `signalType=ransomware_claim`; news, company-page discoveries and HIBP require `secondary_report`. Reference sources cannot emit breach reports. This classification is validated in Python, the UI and the agent reader. `Today · official only` excludes every secondary report and claim.

RSS/Atom dates use per-entry publication metadata, never a channel build/updated timestamp. At most three same-host article dates are enriched per feed. An explicit article byline date has calendar-day precision only; `sourceObservedAt` stays absent. Undated headlines remain in All but cannot enter Recent/Today. HIBP's catalog addition time describes publication, not incident occurrence; its account count does not populate a people count.

Independent workers write validated result envelopes for the merge job. Request, page, response-size, and worker limits bound collection. Access denials and rate limits remain explicit errors. Source-run diagnostics retain selected retrieval metrics, never response bodies, headers, or credentials.

## State and revisions

SQLite stores reports, immutable revisions, and source runs transactionally. Report identity derives from the source and native ID. The normalized content hash ignores retrieval metadata; identical content updates observation timestamps without creating another revision. Corrections preserve `firstSeen` and increment `revision`. Missing or failed source results never delete prior reports.

Sources expose `healthy`, `unchanged`, `partial`, `failed`, or `disabled`, with `lastAttempt`, `lastSuccess`, a message, and parsed/accepted/rejected/new/changed counts. Only `healthy` and `unchanged` advance `lastSuccess`. `lastCollected` also advances for a usable partial collection, while `latestReportDate` is the newest nonfuture source observation/publication/report date among retained records. These are separate from source completeness and from breach occurrence. `collectionEnabled=false` keeps reference datasets visible without fetching them. Demo and live modes cannot be mixed in one database.

The `collection-state` branch persists all revisions and source-run history as checksummed JSON Lines. Restore rejects missing or corrupt state instead of starting a new history. Actions artifacts and dependency caches are not durable record storage.

## Public snapshots

The complete `data/dashboard.json` export uses schema 1: `schemaVersion`, `mode`, `generatedAt`, `sources`, and `reports`. JSON field names are camelCase. Each report includes normalized source fields, identity, observation timestamps, revision number, quality flags, evidence, and history.

Public report history contains the latest 20 revisions, newest first, with changed fields and before/after values. Complete revision content remains in durable state. `evidence.contentHash` fingerprints normalized fields, not an archived source document. Report evidence also includes retrieval time and parser version.

The static build adds a schema 2 index with up to 200 complete reports, whole-snapshot counts, and the hash/size/generation of the full schema 1 export. The loader verifies an archive before replacing usable data. See [snapshot loading and compatibility](../frontend/SNAPSHOTS.md) for the wire format and refresh behavior.

The UI must preserve source-report meaning, unknown counts, source health, and visible demo status. It computes staleness from the current time and permits only safe source links. No organization-name-only incident merging or private firm metadata belongs in the public export; device-local bookmarks contain report IDs only.

The static build also emits a bounded 30-day [agent feed](../agent/README.md) and
latest-100 RSS feed. Latest and these feeds use source observation/publication/report
time, excluding future and undated records. They do not use import time as a breach
date. Claims must remain unverified and attributed in every consumer.
