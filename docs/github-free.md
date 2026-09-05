# GitHub Free constraints

Checked against official GitHub documentation on September 5, 2026. The source is in the public `BD4L/breach-dashboard-v2` repository; scheduled collection and Pages deployment use a separate, repository-guarded workflow.

## Hosting

GitHub Pages serves static files. It cannot run Python collectors, store a private server-side session, or safely hold administrative credentials. GitHub Free supports Pages from public repositories. Published sites have a 1 GB limit, a soft 100 GB monthly bandwidth limit, and a deployment timeout of 10 minutes. The soft limit of 10 builds per hour does not apply to a custom Actions publishing workflow. [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

Pages has restrictions on using it to run an online business or commercial SaaS. Firm use alone does not prove a violation, but the intended public research site and any future commercial/private product must be assessed against the actual terms before publication. Keep confidential firm workflows out of public hosting. [Pages usage limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

Expanded coverage uses compact JSON with a 30 MB snapshot budget and a 50 MB built-site budget, below hosting ceilings. A size violation fails the build; it never silently drops records. It renders a collection timestamp and source failures because static snapshots are not real-time monitoring.

## Actions

Standard GitHub-hosted runners are free for public repositories. Larger runners are billed even for public repositories. Private-repository GitHub Free includes 2,000 minutes per month; that private allowance should not be described as a cap on standard public-repository compute. Artifact/cache storage has separate accounting: keep retention short and do not treat public compute as unlimited free storage. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

The Free plan supports 20 concurrent standard hosted jobs, and an individual hosted job can run for at most six hours. The pilot validation job has a 15-minute timeout and cancels superseded validation runs. The collector runs at most three source jobs at once, with 600-second worker deadlines and 12-minute job caps. The merge/build job has a 20-minute cap and Pages deployment a 10-minute cap. [Actions limits](https://docs.github.com/en/actions/reference/limits)

Schedules run from the default branch, may be delayed or dropped under load, and are disabled in public repositories after 60 days without repository activity. They cannot guarantee a precise notification deadline. The schedule runs at :17 every four hours, exposes stale data, and supports manual dispatch. [Scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

GitHub-hosted jobs are ephemeral. The local SQLite file cannot simply be left on a runner between jobs. The `collection-state` branch stores **public** normalized records and full revision history as diffable JSON Lines, protected by checksums. A shared workflow concurrency group serializes writes. Cache is used only for dependencies. Source and Pages artifacts retain one day of transport data; the branch is the durable source of truth. A corrupt or missing branch fails restore instead of resetting history. Archive files have a 90 MB cap and combined state a 200 MB cap; reaching either requires a reviewed archival change, not automatic deletion. Do not put private data in a public state branch or workflow artifacts.

A branch-based Pages build is not triggered by a push using `GITHUB_TOKEN`. Use an explicit Pages build/deploy workflow when the user authorizes publication. Keep collector write permission separate from read-only validation, and restrict Pages deployment to the intended BD4L repository/environment. [Creating a Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)

## Operational limits

The target is only `BD4L/breach-dashboard-v2`, with project path `/breach-dashboard-v2/`. No workflow dispatches or writes to the original application. Standard public Ubuntu runners are used; no larger runners or paid storage are requested.

A source can still deny automated access, remove its public database, or return incomplete historical coverage. Those states remain visible in the snapshot and workflow outcome. See [source-specific evidence](collector-repair.md). Pages cannot provide private firm notes, authenticated collaboration, or guaranteed immediate alerts; those need a separately designed backend.
