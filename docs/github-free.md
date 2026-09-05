# GitHub Free constraints

Checked against official GitHub documentation on September 5, 2026. This pilot remains local and does not enable a scraper schedule or Pages deployment.

## Hosting

GitHub Pages serves static files. It cannot run Python collectors, store a private server-side session, or safely hold administrative credentials. GitHub Free supports Pages from public repositories. Published sites have a 1 GB limit, a soft 100 GB monthly bandwidth limit, and a deployment timeout of 10 minutes. The soft limit of 10 builds per hour does not apply to a custom Actions publishing workflow. [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

Pages has restrictions on using it to run an online business or commercial SaaS. Firm use alone does not prove a violation, but the intended public research site and any future commercial/private product must be assessed against the actual terms before publication. Keep confidential firm workflows out of public hosting. [Pages usage limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

The pilot uses a 5 MB export budget and 25 MB built-site budget, deliberately well below hosting ceilings. It renders a collection timestamp and source failures because static snapshots are not real-time monitoring.

## Actions

Standard GitHub-hosted runners are free for public repositories. Larger runners are billed even for public repositories. Private-repository GitHub Free includes 2,000 minutes per month; that private allowance should not be described as a cap on standard public-repository compute. Artifact/cache storage has separate accounting: keep retention short and do not treat public compute as unlimited free storage. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

The Free plan supports 20 concurrent standard hosted jobs, and an individual hosted job can run for at most six hours. The pilot validation job has a 15-minute timeout and cancels superseded validation runs. A future collector should keep source concurrency low and bound its own requests, response sizes, and runtime. [Actions limits](https://docs.github.com/en/actions/reference/limits)

Schedules run from the default branch, may be delayed or dropped under load, and are disabled in public repositories after 60 days without repository activity. They cannot guarantee a precise notification deadline. A future schedule should avoid the start of an hour, expose stale data, and support manual dispatch. [Scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

GitHub-hosted jobs are ephemeral. The local SQLite file cannot simply be left on a runner between jobs. Before enabling a collector, choose durable storage for the **public** normalized records and revision history, define retention, and serialize writes. Public data commits are a possible free approach; Actions cache alone is not the source of truth. Do not put private data in a public state branch or workflow artifacts.

A push using `GITHUB_TOKEN` does not trigger a Pages build. Use an explicit Pages build/deploy workflow when the user authorizes publication. Keep collector write permission separate from read-only validation, and restrict Pages deployment to the intended BD4L repository/environment. [Creating a Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)

## Remaining publication gates

1. Create the intended new repository under BD4L with appropriate access; verify its actual name/base path.
2. Decide durable public collection-state storage and history retention; add serialized collection and deployment workflows.
3. Resolve Massachusetts report access and validate current real PDF layouts. Decide whether to expand California beyond the current bounded window and HHS beyond its current dataset.
4. Review the exact public export, hosting terms, source request policy, and CI execution in the new repository.
5. Add any private firm workspace only behind a separately authenticated backend with independently verified authorization. It is outside the local public dashboard pilot.
