# Baseline and isolation

This pilot derives its product scope, Astro/React toolchain and adapter requirements from `BD4L/Breaches` commit `db9ed9e892a12c2d91f2283035214ad07b31934e` (the deployment inspected September 5, 2026). Original checkout: `/Users/sebastienbell/Breaches`.

The new repo selectively carries forward the frontend package manifest/lock and replaces the reviewed UI and ingestion paths behind an explicit versioned contract. It does not copy production workflows, credentials, database fallbacks, unfinished AI functions, or firm records. The source checkout is retained unchanged.

Original tracked changes were saved as a private patch outside this repo in `../breaches-original-work-preservation/`. Untracked work remains in the original folder, with an additional private archive alongside the patch. No original application data is published by this pilot.

User direction: **local first**, eventual repository owner **BD4L**. No remote is configured and no deployment is performed. The currently authenticated GitHub account lacks write permission on `BD4L/Breaches`; this is irrelevant to local work and must be resolved with the intended owner before future publication. Do not silently publish to another account.

Local SQLite is the development store for this stage. Demo and live stores are separate, and neither has a path to the existing Supabase project. The read-only browser loads a local static export. Device-local bookmarks store report IDs only; private notes and firm workspaces are outside this pilot.
