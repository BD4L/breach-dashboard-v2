# Source inventory and restoration - September 12, 2026

All 51 configured sources across the two original directories and added RansomLook are represented in the successor catalog. There are 48 collection targets and three reference-only datasets. Presence in the catalog is not a claim that all sources are currently accessible or complete.

Inventory compared with `Breaches/config.yaml`, its scraper modules, SQL seed and parallel workflow, plus `breach-dash-clean/scrapers/config.yaml` and scraper/workflow files. Original numeric IDs that collide are replaced with distinct textual IDs. Neither original project was modified.

The [hosted collection run](https://github.com/BD4L/breach-dashboard-v2/actions/runs/34702194153) verified all 48 targets using implementation `79076ff`. It ran from 15:25:35 to 15:29:21 UTC (3 minutes 46 seconds); merge, build, public-boundary validation, Pages deployment and artifact cleanup succeeded. [CI validation](https://github.com/BD4L/breach-dashboard-v2/actions/runs/34702190584) passed. The published snapshot is dated September 12 at 15:28:14 UTC. The staff-alert workflow stayed skipped.

**Hosted outcomes: 22 complete/unchanged, 21 limited, five failed and three reference-only.** The overall collection run remains red for source health. All five failures have explicit results; no worker timed out or silently lost its artifact. The four ISMG feeds work locally but return HTTP 403 from GitHub. North Dakota remains HTTP 404. The table below uses hosted outcomes, which supersede local access observations.

Durable state advanced from `96b9f0dcbeb577bb28d42b50cc3540675dbada45` to `b8e7c7bc93af07a11112448c6c372114a0f13c15`. All **28,197 earlier report IDs and first-seen timestamps, plus all 28,357 immutable revisions**, were preserved byte-for-byte at the record level. The published archive holds 29,568 reports. Counts below are latest accepted rows, not distinct incidents or total retained history. Consumed source/Pages transport artifacts were verified deleted after deployment (zero remain for this run).

| Source / ID | Result | Accepted | Latest retained report date |
| --- | --- | ---: | --- |
| [Alphabet IR](https://abc.xyz/investor/) (`ir_alphabet`) | Limited coverage | 0 | Unknown / no matched report |
| [Amazon IR](https://ir.aboutamazon.com/) (`ir_amazon`) | Limited coverage | 0 | Unknown / no matched report |
| [Apple IR](https://investor.apple.com/investor-relations/default.aspx) (`ir_apple`) | Limited coverage | 0 | Unknown / no matched report |
| [BankInfoSecurity.com](https://www.bankinfosecurity.com/rssFeeds.php?type=main) (`news_bankinfosecurity`) | Failed | 0 | Unknown / no matched report |
| [BleepingComputer](https://www.bleepingcomputer.com/feed/) (`news_bleepingcomputer`) | Complete current window | 6 | 2026-09-11 |
| [Breachsense](https://www.breachsense.com/breaches/) (`breachsense`) | Limited coverage | 913 | 2026-09-11 |
| [California](https://oag.ca.gov/privacy/databreach/list) (`california`) | Limited coverage | 5297 | 2026-09-09 |
| [CISA Cybersecurity Alerts](https://www.cisa.gov/cybersecurity-advisories/all.xml) (`cisa_advisories`) | Complete current window | 1 | 2026-09-10 |
| [CISA Known Exploited Vulnerabilities](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) (`cisa_kev`) | Reference only | 0 | Unknown / no matched report |
| [CISA News](https://www.cisa.gov/news.xml) (`cisa_news`) | Unchanged current window | 0 | Unknown / no matched report |
| [Cybernews](https://cybernews.com/) (`news_cybernews`) | Limited coverage | 1 | 2026-09-12 |
| [Cybersecurity Ventures](https://cybersecurityventures.com/feed/) (`news_cybersecurityventures`) | Complete current window | 1 | 2026-09-09 |
| [Dark Reading](https://www.darkreading.com/rss.xml) (`news_darkreading`) | Complete current window | 5 | 2026-09-11 |
| [DataBreaches.net](https://databreaches.net/feed/) (`news_databreaches`) | Complete current window | 8 | 2026-09-11 |
| [DataBreachToday.com](https://www.databreachtoday.com/rssFeeds.php?type=main) (`news_databreachtoday`) | Failed | 0 | Unknown / no matched report |
| [Delaware](https://data.delaware.gov/Public-Safety/Data-Security-Breach-Database/dir6-wx8v/data_preview) (`delaware`) | Unchanged current window | 459 | 2025-07-11 |
| [Have I Been Pwned](https://haveibeenpwned.com/PwnedWebsites) (`hibp`) | Complete current window | 8 | 2026-09-10 |
| [Have I Been Pwned — latest breaches feed](https://feeds.feedburner.com/HaveIBeenPwnedLatestBreaches) (`hibp_feed`) | Complete current window | 8 | 2026-09-10 |
| [Hawaii](https://cca.hawaii.gov/ocp/notices/security-breach/) (`hawaii`) | Limited coverage | 53 | 2024-04-01 |
| [HealthcareInfoSecurity.com](https://www.healthcareinfosecurity.com/rssFeeds.php?type=main) (`news_healthcareinfosecurity`) | Failed | 0 | Unknown / no matched report |
| [HHS Office for Civil Rights](https://ocrportal.hhs.gov/ocr/breach/breach_frontpage.jsf) (`hhs`) | Unchanged current window | 745 | 2026-08-28 |
| [Indiana](https://www.in.gov/attorneygeneral/consumer-protection-division/id-theft-prevention/security-breaches/) (`indiana`) | Limited coverage | 784 | Unknown / no matched report |
| [InfoRiskToday.com](https://www.inforisktoday.com/rssFeeds.php?type=main) (`news_inforisktoday`) | Failed | 0 | Unknown / no matched report |
| [Iowa](https://www.iowaattorneygeneral.gov/for-consumers/security-breach-notifications) (`iowa`) | Limited coverage | 677 | 2026-08-13 |
| [KrebsOnSecurity](https://krebsonsecurity.com/feed/) (`news_krebs`) | Unchanged current window | 0 | Unknown / no matched report |
| [Maine](https://www.maine.gov/ag/consumer-protection/data-security-breaches) (`maine`) | Limited coverage | 2981 | 2020-09-11 |
| [Maryland](https://oag.maryland.gov/resources-info/Pages/security-breach-notices.aspx) (`maryland`) | Limited coverage | 2030 | 2025-03-21 |
| [Massachusetts](https://www.mass.gov/lists/data-breach-notification-reports) (`massachusetts`) | Limited coverage | 3705 | 2026-09-04 |
| [Meta IR](https://investor.atmeta.com/) (`ir_meta`) | Limited coverage | 0 | Unknown / no matched report |
| [Microsoft IR](https://www.microsoft.com/en-us/investor/default) (`ir_microsoft`) | Limited coverage | 0 | Unknown / no matched report |
| [Montana](https://dojmt.gov/office-of-consumer-protection/reported-data-breaches/) (`montana`) | Complete current window | 6659 | 2026-05-15 |
| [New Hampshire](https://www.doj.nh.gov/citizens/consumer-protection-antitrust-bureau/security-breach-notifications) (`new_hampshire`) | Limited coverage | 746 | 2026-09-03 |
| [New Jersey](https://www.cyber.nj.gov/threat-landscape/public-data-breaches) (`new_jersey`) | Unchanged current window | 56 | 2026-08-20 |
| [NIST National Vulnerability Database](https://nvd.nist.gov/) (`nvd`) | Reference only | 0 | Unknown / no matched report |
| [North Dakota](https://attorneygeneral.nd.gov/consumer-resources/data-breach-notices) (`north_dakota`) | Failed | 0 | Unknown / no matched report |
| [Oklahoma state government](https://oklahoma.gov/omes/divisions/information-services/cyber-command/notices/cybersecurity-breaches.html) (`oklahoma`) | Unchanged current window | 9 | 2026-04-07 |
| [Privacy Rights Clearinghouse](https://privacyrights.org/data-breaches) (`privacy_rights`) | Reference only | 0 | Unknown / no matched report |
| [RansomLook](https://www.ransomlook.io/) (`ransomlook`) | Limited coverage | 40 | 2026-09-12 |
| [Reddit r/cybersecurity](https://www.reddit.com/r/cybersecurity.rss) (`reddit_cybersecurity`) | Complete current window | 2 | 2026-09-12 |
| [Reddit r/databreaches](https://www.reddit.com/r/databreaches.rss) (`reddit_databreaches`) | Limited coverage | 0 | Unknown / no matched report |
| [SANS Internet Storm Center](https://isc.sans.edu/rssfeed.xml) (`news_sans`) | Unchanged current window | 0 | Unknown / no matched report |
| [SEC EDGAR](https://www.sec.gov/edgar/search/) (`sec`) | Unchanged current window | 0 | 2026-09-08 |
| [Security Magazine Cybersecurity](https://www.securitymagazine.com/rss/topic/2236-cybersecurity-news) (`news_securitymagazine`) | Complete current window | 10 | 2026-09-11 |
| [SecurityWeek](https://www.securityweek.com/feed/) (`news_securityweek`) | Complete current window | 1 | 2026-09-11 |
| [South Carolina](https://consumer.sc.gov/identity-theft-unit/security-breach-notices) (`south_carolina`) | Limited coverage | 877 | 2026-09-04 |
| [Texas](https://oag.my.site.com/datasecuritybreachreport/apex/DataSecurityReportsPage) (`texas`) | Unchanged current window | 622 | 2026-09-11 |
| [The Hacker News](https://feeds.feedburner.com/TheHackersNews) (`news_hackernews`) | Complete current window | 5 | 2026-09-12 |
| [Threatpost](https://threatpost.com/feed/) (`news_threatpost`) | Limited coverage | 0 | Unknown / no matched report |
| [Vermont](https://ago.vermont.gov/categories/security-breach-notices) (`vermont`) | Complete current window | 348 | 2026-09-11 |
| [Washington](https://www.atg.wa.gov/data-breach-notifications) (`washington`) | Limited coverage | 1860 | 2026-09-09 |
| [Wisconsin](https://datcp.wi.gov/Pages/Programs_Services/DataBreaches.aspx) (`wisconsin`) | Limited coverage | 230 | Unknown / no matched report |

## Material limits and repairs

- **vermont:** Current table restored: all 348 rows through September 11. One repeated date separator normalized explicitly; older document archives excluded.
- **hawaii:** All 55 listed rows inspected; two conflicting counts withheld. Latest listed date is April 2024, not the 2026 PDF upload path. No current statewide coverage claim.
- **maine:** Official notice says the public database is offline. A newer navigation link redirects back to the same withdrawn page; retained Excel archives end in 2020.
- **maryland:** Published catalog still exposes 2024/2025 lists; no verified 2026 replacement was found.
- **north_dakota:** Original public notice URL still fails; no verified replacement identified.
- **indiana:** Current annual PDF works, but source publication/report dates are absent. Consumer notification dates are not substituted.
- **wisconsin:** Public current/archive listings work on standard macOS; publication/report dates remain unavailable.
- **delaware:** The official API is accessible, but the latest retained dated notice is from 2025. Collection success does not prove current reporting.
- **montana:** Accessible full table; latest retained source date is May 2026.
- **oklahoma:** State-government incident notices only, not statewide private-sector coverage.
- **hibp:** Public metadata API, no account key or account searches. Eight catalog additions within 30 days; account counts are not people counts. CC BY 4.0.
- **breachsense:** Two monthly public indexes cover the recent 30-day window. Claims are unverified; no leak content. A failed later page preserves earlier usable results.
- **news_threatpost:** RSS responds, but its newest dated entry is August 2022. No current matching reports.
- **reddit_databreaches:** The hosted feed is accessible but its newest entry is April 2024; it returns no recent matches. Local access was intermittently rate-limited.
- **reddit_cybersecurity:** Accessible in the bounded run, but an earlier request was rate-limited. Hosted access can differ.
- **news_cybernews:** Old RSS path returned 404. Restored the public homepage cards, supporting two observed layouts and their calendar dates. Window remains limited.
- **news_healthcareinfosecurity:** Local check recovered two article byline dates, with one entry undated. Hosted collection receives HTTP 403. No feed build time or invented timestamp.
- **news_bankinfosecurity:** Local check recovered two article byline dates, with one entry undated. Hosted collection receives HTTP 403. No feed build time or invented timestamp.
- **news_databreachtoday:** Local check recovered publication dates from article bylines because RSS omits them. Hosted collection receives HTTP 403; day precision is retained when available.
- **news_inforisktoday:** Local check recovered publication dates from article bylines because RSS omits them. Hosted collection receives HTTP 403; day precision is retained when available.
- **Five company IR pages:** Microsoft, Apple, Amazon, Alphabet and Meta remain distinct sources. Microsoft and Meta URLs were updated. Verified page scans found no breach-related links; all are marked limited because a shallow IR page cannot establish complete security-announcement coverage.
- **CISA KEV and NVD:** preserved as reference links; vulnerability records do not establish an organization breach.
- **Privacy Rights Clearinghouse:** public page offers a purchased database and historical samples; the original CSV importer has no verified current free feed. No dataset was purchased or configured.
- **News/community sources:** public headlines and links are filtered for breach terms in the current feed/window. This can include court coverage, investigations or other incident-related reporting. Secondary reports are explicitly distinct from official filings and claims. Missing dates stay missing.
- **Existing official collectors:** California remains beyond the old 300-row cap; Massachusetts access and SEC ordinary-browser transport remain operational. The [earlier audit](source-status-2026-09-07.md) documents retained scope limits for the other official sources. No historical expansion was added to those collectors.

## Operation

New collectors have a 60-second network budget and a 120-second worker deadline. Sources execute independently, retain prior results on failure, and stop on access denials/rate limits. Full collection is requested every 30 minutes, with recent-source requests between those events; GitHub can delay or drop them. An authenticated external trigger is supported but no external timer has been connected. See [GitHub Free constraints](github-free.md).

The Sources view is searchable and separates last attempt, last usable collection, last complete run and latest report date. Reference entries stay out of breach counts. Secondary reports and claims stay out of Today official only. Agent/RSS exports retain classifications and HIBP attribution. Supabase, recipients and live email enablement remain deferred.

## Provider references

Current public structures were inspected directly: [Vermont table](https://ago.vermont.gov/categories/security-breach-notices), [Hawaii table](https://cca.hawaii.gov/ocp/notices/security-breach/), [HIBP public API documentation](https://haveibeenpwned.com/API/V3), [Breachsense monthly index](https://www.breachsense.com/breaches/2026/september/), [Cybernews public cards](https://cybernews.com/), [Maine withdrawal notice](https://www.maine.gov/ag/consumer-protection/data-security-breaches), and [Privacy Rights offering](https://privacyrights.org/data-breaches).

## Local verification

Python collector, history, boundary and offline alert tests pass; two optional browser fixture tests are skipped. All 49 frontend tests and 15 MCP tests pass, including a real stdio handshake. Astro type checking and production build pass; actionlint reports no workflow errors. The expanded live preview is 36.53 MB against a 50 MB site cap, with a 2.44 MB recent agent feed against its 4 MB cap. Browser inspection verified 51 source cards, catalog search, reference labels and the official-only Today exclusion after full archive loading.

Existing open tabs and older local MCP clients need the updated reader for secondary report types. Reload the dashboard page or update the local connector. The live browser was reloaded and verified with 51 sources and no browser errors.
