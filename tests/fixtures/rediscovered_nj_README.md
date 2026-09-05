# Verified NJCCIC HTML publication fixtures

Captured September 5, 2026 by the parent task through ordinary interactive Chrome. These fixtures contain only the visible `Public Data Breaches` heading and its `News List` widget: no scripts, challenge state, cookies, reporter contact fields, or unrelated navigation. They are not synthetic RSS contracts.

The actual current [public breach listing](https://www.cyber.nj.gov/threat-landscape/public-data-breaches) remains under `threat-landscape`. In the observed normal browser, the newer `threat-center` route redirects to this page; earlier ordinary-request HTTP 403 responses did not establish that the old route was obsolete.

| Fixture | Actual published page | Verified range |
|---|---|---|
| `rediscovered_nj_current.html` | [Current page 1](https://www.cyber.nj.gov/threat-landscape/public-data-breaches) | 1–20 of 21 |
| `rediscovered_nj_page2.html` | [Current page 2](https://www.cyber.nj.gov/threat-landscape/public-data-breaches/-npage-2) | 21–21 of 21; Next disabled |
| `rediscovered_nj_archive.html` | [Archive page 1](https://www.cyber.nj.gov/threat-landscape/public-data-breaches/-arch-1) | 1–20 of 35 |
| `rediscovered_nj_archive-page2.html` | [Archive page 2](https://www.cyber.nj.gov/threat-landscape/public-data-breaches/-arch-1/-npage-2) | 21–35 of 35; Next disabled |

All 56 rows parse to distinct native news IDs. Titles come directly from `.item-title`; `.item-date` supplies publication dates and the title link's accessible label corroborates them. A real historical item includes the time `12/28/2023 12:39 PM`; the parser preserves that local calendar date. It does not infer breach occurrence, discovery, affected people, or a source receipt date from publication dates.

Notice links use `/Home/Components/News/News/{native ID}/216` and may carry `arch=1` or `npage=2` navigation-return context. Those narrowly validated query parameters are omitted from canonical URLs and identities. No query tokens or unexpected destinations are accepted. Published Next/Archive links are followed; no numbered URLs are generated. Every requested range must reconcile with extracted rows, adjacent ranges must join, and scope totals must stay stable. The default collection budget is 40 pages; a smaller explicit budget produces partial coverage.

The parent also opened the [Paylogix notice](https://www.cyber.nj.gov/Home/Components/News/News/2120/216). Its further details are prose, not a structured count/date export. The routine adapter retains the verified listing title, publication date and source link; it does not run speculative prose extraction or request attached notices.

This capture proves the public listing and parser shape. It does **not** prove unattended GitHub access: ordinary HTTP and tested headless transports were denied while normal local Chrome loaded the content. `collect()` retains the standard honest public client and exits on denial, rather than solving a challenge or substituting an empty/guessed feed. The parent task separately verifies hosted browser transport. Full collection replay tests use these four captured pages without network reads.
