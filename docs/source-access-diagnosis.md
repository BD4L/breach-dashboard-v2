# Source access diagnosis — September 5, 2026

The remaining NH, NJ and SEC automatic collection failures happen before parsing: the publishers refuse the requests or return a challenge instead of publication data. They are separate from the earlier worker timeouts and from successful Pages publication.

## Observed responses

In [collection run 33994739013](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33994739013), NH and SEC returned HTTP 403 within the same recorded second; NJ returned 403 in approximately one second. Each failed at its first request. The client spaces requests by at least 0.4 seconds and stops immediately on 401, 403 or 429. Increasing timeout or retry counts would not address these observed failures.

[Earlier HTTP diagnostics](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993384961) found denials on standard Ubuntu, Windows and macOS runners. The [earlier headed Chrome diagnostic](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33993792504) received access-denial titles from NH/NJ; SEC's search page reported a rate threshold and its search API reported an undeclared automated tool. These titles identify the response category, not proof that this individual run exceeded a request limit.

A fresh local comparison at `2026-09-05T23:31:24Z` used the regular HTTP client against the exact canonical first-page URLs used by production collection: NH category 2146, page 1, size 25; NJ's `/threat-landscape/public-data-breaches`; and SEC's August 6–September 5 full 8-K search window. NH returned 403 in 0.232 seconds; NJ returned HTTP 200 with only a 212-byte challenge and no notice data in 0.290 seconds; SEC returned 403 in 0.325 seconds. There was one request per source. This rules out a GitHub-only failure: the regular HTTP client is also refused from the local environment where ordinary Chrome collection succeeded.

## What the evidence can establish

The publishers distinguish between request environments. Automated-client classification, browser/network protocol differences and origin reputation are possible causes. Their filtering rules are not visible to us. Local Chrome success alone does not prove the IP address is the deciding factor or that hosted Chrome will work.

The earlier GitHub browser comparison was not equivalent to the successful local collector: it appended the project identifier to Chrome's User-Agent, enabled JavaScript, and used different first-page queries/routes. The new `matched-browser` mode of **Probe official publishing endpoints** reuses the exact local browser client and production URL builders. It makes one request per source and leaves collection history and publication untouched. Fixed metadata and parser counts are retained for one day; response bodies, headers and network addresses are not exported.

The local matched run at `2026-09-05T23:33:53Z` returned HTTP 200 and valid production-parser results for all three sources: NH 25 rows of 9,937; NJ 20 rows of 21 current notices; SEC 100 document hits of 5,425. Each made exactly one request and completed in 1.2–1.7 seconds. These are first-page transport/schema checks, not complete collections. The runtime was ordinary headed Chrome 152.0.7977.82 and Playwright 1.62.0 on macOS arm64, with JavaScript disabled and no supplied profile, proxy, credentials or User-Agent override. GitHub runs the same script on standard Ubuntu and macOS runners.

## Hosting and SEC policy

GitHub documents that [standard hosted runners are free for public repositories](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories). It also documents that [Ubuntu/Windows runners use Azure address ranges and macOS uses GitHub's macOS cloud](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#ip-addresses). A source returning 403 is not evidence that the repository exhausted its Actions allowance. A paid runner alone would not prove access either.

SEC's [developer guidance](https://www.sec.gov/about/developer-resources) describes automated-client classification and a maximum of 10 requests per second. Its [access documentation](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) asks automated collectors to declare their operator and contact in the User-Agent. The project's HTTP client identifies the project URL; no contact has been invented or added. Permission to collect and recognition by a publisher's request filter are separate technical considerations. SEC's [FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions#developers) directs access-denial reports to its webmaster; no external message has been sent.

Previously verified records remain available. A denied request cannot erase retained reports, establish that a source has no new reports, or count as a successful automated refresh.
