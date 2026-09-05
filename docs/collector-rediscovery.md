# Official source rediscovery — September 5, 2026

This pass re-established publication locations and record formats for the nine failed sources, then investigated a Delaware timeout uncovered by the repaired GitHub run. It changed only `BD4L/breach-dashboard-v2`; the original `BD4L/Breaches` application and database were not used or modified.

For later transport results, see the [matched source access diagnosis](source-access-diagnosis.md). Its successful Chrome checks on standard GitHub runners supersede this earlier phase's broad GitHub-access limitation for NH, NJ and SEC.

## Recovered publishing surfaces

| Source | Verified records | Recovery and remaining coverage limit |
| --- | ---: | --- |
| Massachusetts | 3,705 | Current/prior annual PDFs: 1,507 in 2026 and 2,198 in 2025. Fixed a missing bottom table border on page 67 and wrapped four-digit report IDs. Independent ID-column extraction checks every PDF page. Letter fallback can add new identities without downgrading richer stored records. |
| Iowa | 677 | All 16 published annual card archives, 2011–2026. Follow the official sitemap where the year-selector script contains stale URLs; parse nested cards, related entities and supplemental-only notices. Eleven broken or conflicting rows are withheld. |
| Maine | 2,981 | Two official historical Excel archives through September 14, 2020. The current database remains offline. Seventy-four ambiguous, conflicting or contaminated rows are withheld; contact/address fields are not exported as organizations or data types. |
| Maryland | 2,030 | Anonymous SharePoint catalog and paginated public lists, avoiding the blocked landing page. Independently reconciled 257 rows in 2025 and 1,774 in 2024; one invalid row withheld. A follow-up check of all 26 nonhidden lists and current navigation found no 2026 replacement. Two additional generic historical lists exist outside current coverage; both were last modified in 2025. |
| Wisconsin | 230 | Current listing plus its linked 2012–2023 archive. The 21 current entries span 2024–July 2026; this is a curated consumer-notice list, not a comprehensive filing register. The archived source often lacks a dedicated Wisconsin count; unknown counts remain unknown. The scheduled collector uses a standard macOS runner because Ubuntu requests time out. |
| Delaware | 459 current dataset rows | The official AG parent now links the public `dir6-wx8v` open-data dataset, containing notices through August 12, 2026. The old 322-row HTML table stops in July 2025. Independent counts and dataset revision markers are checked before and after collection. A reviewed one-to-one map preserves 137 existing identities; unmatched historical records remain stored. Date of Notice is not treated as an AG receipt or publication date. |
| New Hampshire | 746 captured | Rediscovered the public document API, category 2146. A normal local browser retrieved 750 rows across 30 pages of a declared 9,937 notices; one duplicate and three unresolved `public://` links were withheld. Captured records are partial. GitHub access remains denied. |
| New Jersey | 56 captured | Actual Granicus news listing: 21 current and 35 archived notices across four pages. Native news IDs and explicit publication dates replace the obsolete parser assumptions. Normal browser navigation redirects the `/threat-center/` alias back to `/threat-landscape/`; the latter is still current. GitHub access remains denied. |
| SEC | 2 captured | The current EDGAR full-text search API exposes primary 8-K/8-K/A Item 1.05 metadata. The new parser scans a bounded 30-day form window, filters actual filing items, uses accession IDs, and verifies pagination. The retained browser capture is only a 64-hit keyword-search subset containing two qualifying filings. GitHub access remains denied. |
| North Dakota | 0 | The old register and an indexed historical PDF return 404. Current navigation, public WordPress searches and all four declared page/post sitemaps (532 URLs) did not reveal a replacement register. Search-engine indexing alone was not treated as proof of a working document. |

Every retained count is a source report count, not a cross-jurisdiction count of unique incidents. Partial coverage is explicitly retained as partial; none of these counts establishes all historical breaches.

## Actual GitHub runner evidence

[Standard-runner probe 33993384961](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993384961) tested fixed official URLs on Ubuntu, Windows and macOS, with additional ordinary headless Chromium checks on Ubuntu. Massachusetts, Iowa, Maine and Maryland returned valid responses on all three operating systems. Wisconsin's current/archive pages timed out on Ubuntu and returned valid data on Windows and macOS.

[Normal Chrome probe 33993792504](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993792504) additionally tested ordinary headed Chrome on macOS and Ubuntu/Xvfb. New Hampshire, New Jersey and SEC still returned HTTP 403. No proxy, challenge solving, impersonation, invented contact address or persistent browser authentication was added. Parser recovery and local browser access do not establish unattended GitHub access.

The manual diagnostic workflow has read-only permissions and fixed destinations. Standard/browser probes use per-endpoint 60-second deadlines and 6 MB limits; their artifacts contain response metadata and schema counts rather than raw bodies or session state. The Delaware diagnostic runs its bounded collector with a 120-second deadline and saves normalized public records for inspection. All diagnostic artifacts expire after one day. No diagnostic writes collection state or deploys Pages.

## Data and runner integrity

A reviewed local merge contains **27,569 reports** in a **30,457,874-byte** compact snapshot. All 17,420 previously published report IDs, first-seen timestamps and revision numbers are unchanged. Browser captures retain actual capture timestamps and explicit source/coverage evidence; their inclusion does not mark GitHub transport as repaired.

The initial 30 MB snapshot guard was raised to 40 MB to fit the verified archive recovery. The full static site remains capped at 50 MB, far below Pages' hosting ceiling. No records were dropped to fit a build. Splitting archive data into lazy-loaded snapshots is a separate future performance improvement.

Source workers remain independent. Timeout cleanup now snapshots and terminates detached descendant process groups, including children that ignore SIGTERM; a real subprocess regression proves this behavior. Failed scheduled sources retain earlier valid records. Sparse letter fallback cannot replace stored rich records or advance their retrieval provenance.

Validation: 21 frontend tests and 208 Python tests passed; the frontend runtime contract accepted all 27,569 reports and 18 source entries. The full project-path build and public boundary check passed, and the tracked 12-report demo was restored byte-for-byte.

Regression fixtures are reduced official public structures or explicitly labeled synthetic cases. Tests cover real MA PDF geometry, Iowa historical navigation, bounded Excel parsing and contaminated fields, Maryland source totals, Wisconsin older layouts, New Jersey pagination, NH overlap/unresolved links, SEC classification/pagination, and detached process cleanup.

## Publication verification

[Collection run 33994739013](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33994739013) collected the repaired Massachusetts, Iowa, Maine, Maryland and Wisconsin sources on GitHub and successfully merged history and deployed Pages. Washington added one record: the published snapshot contains **27,570 reports**, with all 27,569 reviewed seed IDs, first-seen timestamps and revision numbers preserved. HTTP and frontend runtime validation accepted the actual published snapshot (30,458,039 bytes).

The overall run correctly remains red because collection health is evaluated separately from publication: partial coverage and failed sources do not become green merely because Pages deployed. This run additionally exposed a Delaware connection timeout. [Delaware diagnostic 33994995620](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33994995620) subsequently retrieved the old table on both Ubuntu and macOS; the freshness audit then discovered the replacement open-data dataset described above.

The four-hour schedule, manual source refresh, durable `collection-state` history and static Pages deployment remain in the successor repository. New Hampshire, New Jersey and SEC still reject GitHub runners; their reviewed browser captures remain preserved with explicit partial coverage. No working North Dakota replacement was found.

The Delaware replacement's reviewed merge restores the latest published state and produces **27,892 reports** (31,155,934 bytes): 322 new identities and 137 updated Delaware records. All 27,570 earlier identities and first-seen timestamps survive; each changed record retains its earlier revision history. Fifty-five compatible historical end dates and one otherwise missing count keep explicit legacy provenance. Five conflicting ranges remain historical context rather than being combined into inferred dates. The final Python suite passes 220 tests, including 12 Delaware tests, and the frontend accepts all 27,892 reports.

[Replacement collector probe 33995755431](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33995755431) collected all 459 Delaware rows on both standard Ubuntu and macOS runners. Both normalized outputs match the reviewed local records exactly, including the preserved historical fields. [CI 33995755793](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33995755793) passed on the shipped collector commit `942a1f1`.

[Delaware collection and publication 33995802190](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33995802190) passed all five jobs: plan, collect, merge, health and deploy. Durable state advanced to `9a7cd481ea5272edd22cb5954dd4462f72a31ade`. The actual [Pages site](https://bd4l.github.io/breach-dashboard-v2/) and [published snapshot](https://bd4l.github.io/breach-dashboard-v2/data/dashboard.json) returned HTTP 200. The snapshot generated at `2026-09-05T22:24:38Z` contains **27,892 reports**, including 644 retained Delaware identities (459 present in the current dataset plus 185 unmatched historical records), and passes the frontend runtime validator. Every earlier first-seen timestamp remains unchanged; the 137 expected Delaware revisions append to their existing history, and all other reports are unchanged.

Final source status is four failed, nine partial, four unchanged and one healthy. Partial means limited or unverified coverage; failed means the latest automatic attempt could not collect usable records. The four failed sources are North Dakota, New Hampshire, New Jersey and SEC. Previously verified browser records for the last three remain published, without implying that their unattended collection works.
