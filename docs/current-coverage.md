# Current coverage and local collection — September 5, 2026

This follow-up checks current publication coverage after the initial [source rediscovery](collector-rediscovery.md). All code, state and deployment changes belong to `BD4L/breach-dashboard-v2`.

Later on September 5, the [matched access diagnosis and full hosted collection](source-access-diagnosis.md#full-hosted-collection-and-publication) verified NH, NJ and SEC collection in ordinary Chrome on standard GitHub runners and connected them to the four-hour workflow. The local-only access conclusions below describe the earlier collection phase and are superseded by that follow-up.

## Verified publication limits

Maine's current public database remains withdrawn. Its live [Data Breach Notices menu destination](https://www.maine.gov/ag/news-and-library/data-breach-notices) redirects to the [official offline notice](https://www.maine.gov/ag/consumer-protection/data-security-breaches). The linked [June 12 statement](https://www.maine.gov/ag/news-and-library/press-releases/statement-office-maine-attorney-general-abuse-data-breach-reporting) explains the withdrawal following false submissions; the current site does not announce a reopened database. The [archives](https://www.maine.gov/ag/news-and-library/archives) still provide only the two workbooks ending in September 2020. Insurance reporting pages expose intake forms and an older advisory, not a current public register. The existing 2,981 reviewed historical records remain retained. Retired pages and search-engine snippets were not used to reconstruct the withdrawn database.

North Dakota's current [insurance reporting page](https://www.insurance.nd.gov/companies/cybersecurity-reporting) and [NDIT incident-reporting page](https://www.ndit.nd.gov/support/report-cybersecurity-incident) link submission services. Neither is a public breach listing. Current Attorney General navigation and additional official-domain discovery did not identify a replacement register. Two more indexed historical documents returned actual HTTP 404 despite cached search text. Current public coverage remains unverified; this does not establish that the state permanently stopped publishing notices.

Maryland's current [official notices page](https://oag.maryland.gov/resources-info/Pages/security-breach-notices.aspx) still binds older annual lists. A deeper anonymous public-list scan reconciled all 5,608 `Security-Breaches` rows (dates in 2022–2024) and all 4,016 `Security-Breach-Notices` rows (3,733 parseable dates through June 2024; 283 unknown). The currently collected 2025 list contains 257 rows dated January 2–March 21, 2025. Unknown dates were not guessed.

The separate public SBN document library has 2022–2025 folders and a 2026 modification timestamp, but no verified 2026 notice date. Its 2025 folder has 418 files, including 161 paths outside the collected annual list. Bounded text probes from four linked PDFs yielded only 2024/2025 dates or no dates; they were not exhaustive PDF/OCR reviews. The library remains a possible historical backfill, not established current coverage. No filename-only records were added merely to raise the report count.

## Collection outside GitHub

A fresh, ordinary local Chrome session returned HTTP 200 with the expected public content for New Hampshire's document API, New Jersey's breach news listing and SEC's current full-text search API. The experiment used an isolated context, disabled page JavaScript and service workers, and did not import cookies, a user profile, authentication or browser state. The first pages contained 25 NH document rows and 100 SEC filing-search hits; first-page access alone does not prove a complete collection.

The optional local collector is separate from the existing four-hour GitHub schedule. Successful local collection does not establish GitHub transport access or an unattended local schedule. The browser must be installed and the local machine must be awake for a local run.

The full local SEC collection on September 5 inspected **5,425 of 5,425** declared document hits across **55 pages** in the August 6–September 5 window. It found two primary Item 1.05 filings, with zero rejected qualifying reports. The window total reconciles; earlier filings and other disclosure items remain out of scope. This is stronger coverage evidence than the earlier 64-hit keyword capture, even though the resulting filing identities are the same.

The local NH run processed 750 rows from the newest 30 pages, accepting 747 and withholding three unresolved Drupal document links. Its declared archive has 9,937 rows across 398 pages, so coverage remains explicitly partial. Its current usable set adds two identities absent from the previous capture; one previously retained identity falls outside this run and remains in history. NJ reconciled all 56 published current/archive news-list rows across four pages. Its linked notice contents are outside collection scope.

The reviewed merge contains **27,894 reports**. All 27,892 previously published IDs, first-seen timestamps, revision numbers and existing history entries remain unchanged. Only two NH identities are new. Current source messages explicitly identify these local browser observations; they do not claim that GitHub now reaches these sources. See [local collector commands and boundaries](local-browser-collection.md).

## Publishing preserved history

The manual **Publish preserved public history** workflow restores and validates the existing `collection-state` archive, exports it, builds the static app and deploys Pages. It does not scrape sources, alter records or turn prior failed outcomes into success. It uses the same deployment concurrency group as the scheduled collection workflow. This supports publishing reviewed local recovery without immediately repeating the blocked GitHub collectors.

## Faster initial loading and validation

The final reviewed 27,894-report export is 31,159,264 bytes. The new `data/snapshot.json` entry point contains 200 whole reports, source outcomes and whole-snapshot count summaries in **552,123 bytes**, reducing the initial data transfer by about **98.2%**. The existing `data/dashboard.json` stays byte-for-byte complete schema 1 for older clients and existing download links. The full static site is 32,148,446 bytes, inside the unchanged 50 MB limit. No archive record or history entry was deleted to achieve this reduction.

All/Today/Saved, searches, filters and alternate sort orders wait for the complete archive. Hash, size, generation, source metadata and initial-record checks prevent mixed snapshots from being displayed. A failed download retains the usable initial records and offers a retry. The full-download button verifies the complete export first. [Snapshot format and compatibility](../frontend/SNAPSHOTS.md) describes these contracts.

Validation passed: 231 Python tests (two optional browser checks skipped in the default suite and passed separately), 35 frontend tests, type checking, the project-path build, workflow lint and the public-boundary check. Controlled Chrome tests establish that redirected destinations, frames and subresources received zero requests and cookies did not carry between pages. Browser UI checks observed only the small index on initial load; search fetched the full archive, Saved retained the selected record, and the downloaded JSON exactly matched the full source dataset. An injected HTTP 503 produced an archive error without false empty results, and retry recovered all records. Desktop and 390-pixel mobile layouts were inspected; long evidence URLs now wrap inside their notice box.

## Verified deployment

Code commit `f9c5e4cb7d6cf06987298d6faed39b9e4fff87de` passed [CI run 33997688247](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33997688247). The reviewed history was committed to `collection-state` as `70bc340ae5fbaac548d87c304deeb702d3e5af7e`. [Publication run 33997743173](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33997743173) successfully built and deployed that state to [GitHub Pages](https://bd4l.github.io/breach-dashboard-v2/).

The published snapshot is dated `2026-09-05T23:06:17Z` and contains 27,894 reports. The page, 552,123-byte bootstrap and 31,159,264-byte complete export each returned HTTP 200. The bootstrap's archive hash, size and generation matched the full export; the published reports and source outcomes exactly matched the reviewed local merge. A fresh browser on the deployed site requested only `data/snapshot.json` initially. Selecting **All reports** then requested the preserved `data/dashboard.json` endpoint and displayed **Full archive loaded · 27,894 reports**. The original dashboard repository and deployment were not changed.
