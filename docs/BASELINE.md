# Baseline and isolation

This pilot derives its product scope, Astro/React toolchain and adapter requirements from `BD4L/Breaches` commit `db9ed9e892a12c2d91f2283035214ad07b31934e` (the deployment inspected September 5, 2026). The original checkout is preserved separately.

The new repo selectively carries forward the frontend package manifest/lock and replaces the reviewed UI and ingestion paths behind an explicit versioned contract. It does not copy production workflows, credentials, database fallbacks, unfinished AI functions, or firm records. The source checkout is retained unchanged.

Original tracked changes were saved as a private patch outside this repository. Untracked work remains in the original folder, with a separate private preservation archive. These backups are not part of the new repository.

User direction began **local first**, with repository owner **BD4L**. On September 5, 2026, the user authorized the new GitHub repository, `BD4L/breach-dashboard-v2`. Its public source and read-only validation workflow are separate from the original application. Repository creation does not enable Pages hosting or unattended collection.

Local SQLite is the development store for this stage. Demo and live stores are separate, and neither has a path to the existing Supabase project. The read-only browser loads a local static export. Device-local bookmarks store report IDs only; private notes and firm workspaces are outside this pilot.
