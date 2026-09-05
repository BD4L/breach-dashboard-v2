# Pilot contract (v1)

All agents use this contract. Local-only pilot; no production URLs, credentials, database writers, email, or paid AI integrations. Retain Astro/React and Python. Root owns integration/docs/config and final verification.

## Python source adapter interface

`ingestion.adapters.collect(source_id: str) -> Collection` for `massachusetts`, `hhs`, `california`. `Collection` and `Report` dataclasses defined in `ingestion/models.py` (root owned). Source failures raise `SourceError` and never return an empty successful collection. No direct database calls in adapters. Unit parser functions accept captured source text/bytes. Adapters may fetch bounded public official source pages only, respect 403/429 and never bypass controls. Normalize dates to YYYY-MM-DD or None, preserve dubious raw values in quality_flags. SourceReport native_id must not be the common annual document URL. Do not infer breach date from reported date, or national victims from state counts.

## Database and exported JSON

Pipeline owns `ingestion/store.py`, `ingestion/cli.py`, tests/test_store.py, and tests/test_cli.py. SQLite local state persists reports/revisions and source runs; saves should be transactional. Idempotent content hash ignores retrieval metadata. Failure preserves last known good reports. Distinguish changed from new, firstSeen never changes, revision history retained. Exports use camelCase JSON in frontend/public/data/dashboard.json. JSON schema version 1:

```
{schemaVersion:1, mode:"demo"|"live", generatedAt:ISO,
 sources:[{id,label,jurisdiction,method,homepage,status:"healthy"|"unchanged"|"partial"|"failed"|"disabled",
 lastAttempt:ISO|null,lastSuccess:ISO|null,message:string,
 counts:{parsed,accepted,rejected,new,changed}}],
 reports:[{id,sourceId,nativeId,organization,
 publishedDate:string|null,reportedDate:string|null,breachStart:string|null,breachEnd:string|null,discoveryDate:string|null,
 firstSeen:ISO,lastSeen:ISO,lastChanged:ISO,revision:number,
 affected:{count:number|null,scope:"state"|"national"|"reported"|"unknown",jurisdiction:string|null,qualifier:"exact"|"at_least"|"less_than"|"unknown"},
 dataTypes:string[],sourceUrl:string,noticeUrl:string|null,summary:string,
 qualityFlags:[{code,message}],
 evidence:{retrievedAt:ISO,contentHash:string,parserVersion:string},
 history:[{observedAt:ISO,changedFields:string[],changes:[{field:string,before:unknown,after:unknown}]}]}]}
```

Sources registry root defines constants `SOURCES` in models.py. UI must calculate staleness from current time, show data mode prominently, render safe source links only, keep unknowns in default views, and not label source reports as deduplicated incidents. No auto-merging solely by organization. Pilot review queue = source reports with evidence; explicit incident-grouping is future unless confidently supported. Device-local bookmarks of report IDs allowed with honest label; no notes or firm metadata in localStorage or public files.

History is newest first, with the most recent 20 revisions exported; complete snapshots remain in SQLite. `contentHash` fingerprints normalized report fields, not the original source document. Partial collection retains accepted reports and earlier data but does not advance `lastSuccess`; it must not be presented as full source coverage. Source-run diagnostics are stored separately from public report fields.

CLI desired commands:
`python -m ingestion.cli demo --db state/demo.sqlite --export frontend/public/data/dashboard.json`
`python -m ingestion.cli collect --source all --db state/pilot.sqlite --export frontend/public/data/dashboard.json`
`python -m ingestion.cli export --db state/pilot.sqlite --export frontend/public/data/dashboard.json`
Live collection defaults explicit source/all with jobs sequential locally (<=3 later). Exit nonzero when any source fails but still export healthy/last valid data and current health. Demo generated deterministic relative to supplied `--now` or current UTC; independent database cannot mix demo/live silently. Tests must not call network. Root provides demo records.
