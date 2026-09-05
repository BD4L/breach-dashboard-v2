# Official source rediscovery — September 5, 2026

This pass re-established publication locations and record formats for the nine failed sources. It changed only `BD4L/breach-dashboard-v2`; the original `BD4L/Breaches` application and database were not used or modified.

## Recovered publishing surfaces

| Source | Verified records | Recovery and remaining coverage limit |
| --- | ---: | --- |
| Massachusetts | 3,705 | Current/prior annual PDFs: 1,507 in 2026 and 2,198 in 2025. Fixed a missing bottom table border on page 67 and wrapped four-digit report IDs. Independent ID-column extraction checks every PDF page. Letter fallback can add new identities without downgrading richer stored records. |
| Iowa | 677 | All 16 published annual card archives, 2011–2026. Follow the official sitemap where the year-selector script contains stale URLs; parse nested cards, related entities and supplemental-only notices. Eleven broken or conflicting rows are withheld. |
| Maine | 2,981 | Two official historical Excel archives through September 14, 2020. The current database remains offline. Seventy-four ambiguous, conflicting or contaminated rows are withheld; contact/address fields are not exported as organizations or data types. |
| Maryland | 2,030 | Anonymous SharePoint catalog and paginated public lists, avoiding the blocked landing page. Independently reconciled 257 rows in 2025 and 1,774 in 2024; one invalid row withheld. No 2026 list is published in the catalog. |
| Wisconsin | 230 | Current listing plus its linked 2012–2023 archive. The archived source often lacks a dedicated Wisconsin count; unknown counts remain unknown. The scheduled collector uses a standard macOS runner because Ubuntu requests time out. |
| New Hampshire | 746 captured | Rediscovered the public document API, category 2146. A normal local browser retrieved 750 rows across 30 pages of a declared 9,937 notices; one duplicate and three unresolved `public://` links were withheld. Captured records are partial. GitHub access remains denied. |
| New Jersey | 56 captured | Actual Granicus news listing: 21 current and 35 archived notices across four pages. Native news IDs and explicit publication dates replace the obsolete parser assumptions. Normal browser navigation redirects the `/threat-center/` alias back to `/threat-landscape/`; the latter is still current. GitHub access remains denied. |
| SEC | 2 captured | The current EDGAR full-text search API exposes primary 8-K/8-K/A Item 1.05 metadata. The new parser scans a bounded 30-day form window, filters actual filing items, uses accession IDs, and verifies pagination. The retained browser capture is only a 64-hit keyword-search subset containing two qualifying filings. GitHub access remains denied. |
| North Dakota | 0 | The old register and an indexed historical PDF return 404. Current navigation, public WordPress searches and all four declared page/post sitemaps (532 URLs) did not reveal a replacement register. Search-engine indexing alone was not treated as proof of a working document. |

Every retained count is a source report count, not a cross-jurisdiction count of unique incidents. Partial coverage is explicitly retained as partial; none of these counts establishes all historical breaches.

## Actual GitHub runner evidence

[Standard-runner probe 33993384961](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993384961) tested fixed official URLs on Ubuntu, Windows and macOS, with additional ordinary headless Chromium checks on Ubuntu. Massachusetts, Iowa, Maine and Maryland returned valid responses on all three operating systems. Wisconsin's current/archive pages timed out on Ubuntu and returned valid data on Windows and macOS.

[Normal Chrome probe 33993792504](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993792504) additionally tested ordinary headed Chrome on macOS and Ubuntu/Xvfb. New Hampshire, New Jersey and SEC still returned HTTP 403. No proxy, challenge solving, impersonation, invented contact address or persistent browser authentication was added. Parser recovery and local browser access do not establish unattended GitHub access.

The manual diagnostic workflow has read-only permissions, fixed destinations, per-endpoint 60-second process deadlines and 6 MB limits. Artifacts contain response metadata and schema counts, not raw response bodies or session state, and expire after one day. No diagnostic writes collection state or deploys Pages.

## Data and runner integrity

A reviewed local merge contains **27,569 reports** in a **30,457,874-byte** compact snapshot. All 17,420 previously published report IDs, first-seen timestamps and revision numbers are unchanged. Browser captures retain actual capture timestamps and explicit source/coverage evidence; their inclusion does not mark GitHub transport as repaired.

The initial 30 MB snapshot guard was raised to 40 MB to fit the verified archive recovery. The full static site remains capped at 50 MB, far below Pages' hosting ceiling. No records were dropped to fit a build. Splitting archive data into lazy-loaded snapshots is a separate future performance improvement.

Source workers remain independent. Timeout cleanup now snapshots and terminates detached descendant process groups, including children that ignore SIGTERM; a real subprocess regression proves this behavior. Failed scheduled sources retain earlier valid records. Sparse letter fallback cannot replace stored rich records or advance their retrieval provenance.

Validation: 21 frontend tests and 208 Python tests passed; the frontend runtime contract accepted all 27,569 reports and 18 source entries. The full project-path build and public boundary check passed, and the tracked 12-report demo was restored byte-for-byte.

Regression fixtures are reduced official public structures or explicitly labeled synthetic cases. Tests cover real MA PDF geometry, Iowa historical navigation, bounded Excel parsing and contaminated fields, Maryland source totals, Wisconsin older layouts, New Jersey pagination, NH overlap/unresolved links, SEC classification/pagination, and detached process cleanup.

## Publication verification

Deployment evidence is appended after the repaired collectors run on GitHub. The four-hour schedule, manual source refresh, durable `collection-state` history and static Pages deployment remain in the successor repository.
