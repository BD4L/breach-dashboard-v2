# Recent monitoring

The operating priority is recent source discovery. Existing collection history is
retained for evidence and corrections; expanding historical archives is secondary.
Latest sorts by `sourceObservedAt`, then `publishedDate`, then `reportedDate`, using
the first present field. It does not substitute initial import time for a source date.

RansomLook's `/api/posts` metadata supplies group, claim title and provider discovery
time. The collector requests three UTC calendar days, validates the exact response
shape and follows no claim links. Reports have unknown affected counts and the
classification `ransomware_claim`. A provider observation is not independent proof
of a breach or a promise that the claim preceded every other source.

The provider grants commercial reuse with attribution under CC BY 4.0. Attribution
and a normalization notice travel with the source metadata, details, feeds and
emails. Its hosted service describes continuous collection; no measured delay or
contractual availability guarantee has been established here.
[RansomLook API and license](https://github.com/RansomLook/RansomLook#usage-of-the-api-and-license),
[about the service](https://www.ransomlook.io/about).

SEC's three-day discovery window reduces search pages and exposure to transient
HTTP 500 errors. Once daily, the existing schedule checks 30 days for missed notices
or amendments. This improves bounded collection, but cannot make SEC's endpoint
available during a denial or outage.

Collection stays at 30-minute intervals for this free first release. Standard public
GitHub runners do not charge compute minutes, but shared artifact storage, Pages
publication time/cache and scheduler delays still constrain useful frequency.
Reducing the cron interval alone cannot guarantee fast discovery. Measure provider
observation → dashboard firstSeen → publication lag before increasing frequency.
[GitHub limits and measured storage](github-free.md).

Potential additions should be judged by current publication delay and commercial
redistribution rights:

| Candidate | Fit and current constraint |
| --- | --- |
| Direct company/SEC announcements | Authoritative confirmation; publication can follow the incident or earlier claims. |
| Have I Been Pwned breach metadata | Useful corroboration and discovery dates; not a guaranteed first-discovery feed. Follow its attribution requirements. |
| Ransomware.live | Commercial use and raw feed republication require appropriate permission; free API access alone is insufficient. |
| DarkOwl ransomware intelligence | Possible paid supplement. Verify latency, endpoint access and rights covering public JSON/MCP and staff alerts before purchasing. |

[HIBP API](https://haveibeenpwned.com/API/v3),
[Ransomware.live terms](https://ransomware.live/t%26c),
[DarkOwl ransomware fields](https://support.darkowl.com/knowledge-base/description-of-ransomware-api-fields).

A hosted Streamable HTTP MCP endpoint, webhooks or continuously running collection
needs a backend beyond GitHub Pages. The current release offers public static feeds
and an optional local stdio MCP connector; it does not pretend a static URL is an
MCP server. Private alert subscriptions and delivery state remain in Supabase.
