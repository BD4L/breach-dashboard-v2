# Verification evidence — September 5, 2026

The first sections record the original local milestone. Later UI and GitHub milestones are recorded below; references to local-only state in the original milestone are historical.

## Collection evidence

The full local smoke run used a separate live SQLite database and official public endpoints. It made no calls to the existing application's database or integrations.

| Source | Result | Accepted | Evidence limit |
| --- | --- | ---: | --- |
| HHS | Healthy | 733 | All 733 entries in the current HIPAA Under Investigation table; archive and Part 2 excluded |
| California | Partial | 300 | Six listing pages reached the configured collection window; older pages excluded |
| Massachusetts | Failed | 0 | HTTP 403 at the report index; no bypass attempted |

Total: **1,033 public source reports** in ignored local state. The collector exited `1`, correctly signaling partial/failing coverage while exporting valid data. This is one observed collection run, not proof of unattended reliability or all-source completeness.

The separate 12-report synthetic demo exercises a corrected count (8,200 → 12,480), newly observed reports, unknown counts, a questionable future publication date, and a failed source retaining its previous records. It does not represent actual incidents.

## Automated checks

- Python: **46 offline tests passed** (22 adapter/network tests, 24 persistence/validation/CLI tests). Final execution used a temporary virtual environment at `/tmp/breach-pilot-check-20260905`, installed from the same `requirements.lock`, after dependency reads in the Documents folder stalled. No network calls occur in these tests.
- Dependency resolution: `pip check` passed. PDF parsing dependencies were updated to pdfplumber 0.11.10 and pdfminer.six 20260107; this avoids the inherited vulnerable pdfminer pin. Resolution checks alone are not a security audit.
- Frontend: **11 domain tests passed**, including minimum-count qualifiers, source-date ordering, future timestamps, malformed contracts, safe links, and revision ordering.
- `npm run check`: zero errors, warnings, or hints. Root-path and `/breach-dashboard-v2/` static builds passed. Astro's React integration emits upstream Vite deprecation notices during builds; these are distinct from project diagnostics.
- `npm audit --audit-level=moderate`: zero known vulnerabilities at verification time. This does not establish absence of all vulnerabilities.
- Public-boundary check passed for public source, demo/live exports, and built assets. The live export was 1,281,565 bytes; the root static site was 1,678,558 bytes.
- Original tracked changes have the same SHA-256 as their preservation patch, and original working-tree status matches the saved baseline. At that local milestone, the new repository had no remote.

## Browser inspection

Inspected the running application with the in-app browser at desktop size (1280 × 720) and mobile size (390 × 844); reset the viewport afterward.

- Demo: search returned both distinct same-name reports; unknown-count filter retained three records; corrected count showed 8,200 → 12,480 before the original collection entry; future publication date was withheld and explained.
- Bookmarks: saving updated the Saved view, persisted across reload, and was removed after the test. The UI explicitly states device-only storage.
- Mobile: report list fit the viewport; selecting a report opened readable evidence, and Escape returned to the list.
- Live: all 1,033 reports rendered; page 2 showed reports 11–20; HHS filtering reset pagination to 1–10 of 733; largest-count sorting worked; source health showed MA failure, HHS current coverage, and CA partial coverage.
- Final source-date refinement: recent source dates break initial-import ties and rows explicitly distinguish “Reported” from “Published.” “New” is visibly explained as newly collected, including older reports on initial import.
- Recovery: a nonmatching search showed a useful empty state; reset restored all reports. Temporarily withholding the local JSON showed a 404 error with “Try again”; restoring it and retrying recovered the dashboard.

These checks are practical browser verification, not a complete screen-reader audit or proof on every physical mobile device. The project base-path build was verified locally; no GitHub Pages deployment was made.

## Prepared preview

The live snapshot is built into ignored `frontend/dist/` and can be viewed with `cd frontend && npm run preview -- --port 4326`. The source-controlled default `frontend/public/data/dashboard.json` is restored to the 12-record synthetic demo. Running `npm run build` replaces that prepared live build with whichever JSON is currently selected. The live database and original live export remain in ignored `state/`.

MA table fixtures are synthetic; reduced HHS and California fixtures came from observed official responses. Parser fixtures do not prove Massachusetts production PDF fidelity. The source-run table records bounded coverage diagnostics; normalized-record fingerprints do not authenticate original documents.

Final review hardened the collector against ambient `.netrc` authentication and incomplete PDF extraction. The expanded offline regressions passed; the live smoke collection preceded these final two fixes. MA PDF text/table agreement remains partial unless an independent annual count is supplied and validated.

## Scope

The original application was preserved. The initial local milestone included no remote repository, push, publication, migration, authenticated firm workspace, email service, or AI integration. GitHub Actions configuration had only local review at that stage.

## UI token pass

Replaced the ad hoc palette and accumulated CSS overrides with Open Props 1.7.23 and the semantic roles documented in `docs/design-tokens.md`. The component stylesheet now contains no literal palette colors. Working text renders at 14 px and metadata at 12 px; mobile inputs render at 16 px with 44 px controls. Pack imports, variable aliases, and the build-time favicon were independently reviewed.

Typechecking passed with zero project diagnostics. Root and `/breach-dashboard-v2/` static builds passed, as did the public-boundary check and whitespace checks. npm reported zero known vulnerabilities after installation. Existing upstream Vite deprecation notices remain.

Browser checks confirmed the rendered type/color values and no page-wide horizontal overflow at desktop width 1167 px or mobile widths 390 px and 320 px. All four view tabs fit at 390 px; narrower navigation remains horizontally scrollable. At 320 px, the save target and its column both measure 44 px and the target is contained. Source-status colors, mobile evidence navigation, and Escape-to-return were visually checked. The exact 1,033-report live preview snapshot was retained, and the checked-in demo export was restored byte-for-byte after building.

## Anthropic-inspired UI

Applied the three-color brand palette and Open Props scales described in `design-tokens.md`, removed decorative dots, added accessible icon controls, and set 12 px controls and 16 px panels. Browser checks passed at 1167 px desktop and 390 / 320 px mobile, including 44 px bookmark controls and the Saved view. The current narrow navigation fits without page overflow. DM Sans 700 is bundled and verified loaded. Commit `7a598a2` records this completed pass.

## Today counter and GitHub repository

Created the separate public repository [BD4L/breach-dashboard-v2](https://github.com/BD4L/breach-dashboard-v2) with the user's authorization. The source-controlled dataset remains the 12-report synthetic demo; local live state, build output, and preservation archives are excluded. A bounded review of the original three commits and 58 unique blobs found no credential or private-firm-data publication blockers. The existing application remains separate.

Added the UTC notification-date Today counter and a corresponding view. Historical records imported today are excluded unless their source publication date (reported-date fallback) is today. Related source reports count separately. Snapshot revalidation runs every five minutes while visible, on visibility return, and by manual refresh. Failed checks retain the last valid dataset and collection timestamp.

- **21 frontend tests passed**, covering notification-date semantics, UTC rollover, historical imports, source-report identity, loader coalescing, timeouts, malformed data, disposal, and recovery.
- **46 offline Python tests passed**.
- Astro type checking reported zero project diagnostics. Root and `/breach-dashboard-v2/` static builds passed; existing upstream Vite deprecation notices remain.
- Browser verification confirmed the actual local live snapshot has 1,033 reports and zero notification dates matching September 5, 2026 UTC. The Today view shows an explicit empty state and source-coverage limitations.
- A simulated 404 during manual refresh retained all 1,033 reports and displayed the failed-check state. Restoring the JSON and refreshing cleared the error and recovered without reloading the page.
- The header and report view fit desktop width 1167 px and mobile widths 390 / 320 px; the mobile manual-refresh target measures 44 px.

Remote checks are available in [GitHub Actions](https://github.com/BD4L/breach-dashboard-v2/actions). This step publishes repository source and validation only. Pages hosting and unattended source collection remain pending; browser snapshot checks alone do not collect new source data.

The first GitHub validation run exposed an npm 10 clean-install mismatch in the inherited lock: React's Vite required its own compatible esbuild peer entry. Added the missing esbuild 0.28.2 subtree and platform entries, preserving every existing dependency version and libc selector. A clean temporary install passed with the same Node 22.23.2 / npm 10.9.8 versions used by GitHub. This repair changes the lockfile only; the dependency manifest and CI runtime remain unchanged.

## Independent collector repair and durable workflow

The September 5 repair adds 18 independent source adapters and a separate merge/publish workflow. All 114 Python tests passed, including hard worker timeout, portable result contracts, missing-artifact isolation, exact/conflicting duplicate accounting, archive checksum rejection, fresh-runner history restoration, and repeat-merge idempotency. All 21 frontend tests and Astro typechecking passed. Actionlint 1.7.12 validated both workflow files.

The bounded local source smoke merged **17,420 public reports** into a separate database copied from the existing 1,033-report live pilot, preserving those records' first-seen timestamps. It did not query or copy the original application's database. The initial compact export was 17.9 MB and full textual state 34.3 MB, below the configured budgets. The frontend contract validated all records and all 18 source entries.

| Source | Accepted | Local result |
|---|---:|---|
| California | 5,293 | 106 pages; two nameless source rows withheld |
| HHS | 733 | Complete current HIPAA Under Investigation table |
| Indiana | 784 | 25 annual PDF pages; two duplicates rejected; annual scope partial |
| Oklahoma | 9 | Complete within the state-government incident feed |
| Maryland | 257 | Latest declared 2025 list; no 2026 list exposed by the page |
| Wisconsin | 21 | Current page; historical archive excluded |
| Montana | 6,650 | Full embedded listing in one request |
| Washington | 1,849 | All 38 pages; eight exact overlaps at page boundaries; partial |
| South Carolina | 877 | Two conflicting source rows withheld |
| Delaware | 322 | Complete listing; blank formatting row ignored |
| Texas | 625 | All current-view public rows in two requests |
| MA / IA / ME / ND / NJ / NH / SEC | 0 | Access denied, withdrawn database, missing directory, or challenge; explicit failures |

CA's two rejected rows are `sb24-194945` and `sb24-183108`: both listing and detail pages omit an organization name. Washington's eight repeats occur across page boundaries, so health remains partial even though every numbered page was requested. South Carolina's two rows share organization, date, and notice URL but disagree on count; no count was arbitrarily selected. These are data-quality limits, not silently swallowed failures.

The original application remains unchanged. See [repair scope and per-source limits](collector-repair.md). Wisconsin public-notification dates are retained as report context and excluded from publication/receipt fields and the Today counter. Root and project-path builds passed with the full live dataset; the tracked 12-report demo was restored byte-for-byte. The public-boundary regression distinguishes official South Carolina notice URLs containing a Breaches directory from actual original-application coupling. Browser verification rendered all 17,420 reports and 18 source entries. Remote deployment evidence is recorded after the first actual Actions execution.

### GitHub runner and Pages proof

[Validation run 33991423853](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33991423853) passed on commit `6937622`, using GitHub's clean Node 22 / Python 3.11 environment.

[First collection run 33991456254](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33991456254) ran all 18 source jobs. Every result artifact uploaded, and all returned row counts matched the bounded local reads. Collector steps took 0–56 seconds; California fetched 106 pages in 56 seconds. No worker approached its hard deadline.

The merge job and Pages deployment **succeeded**. Overall collection health intentionally remained failed because unavailable/partial sources are not marked healthy. Two runner-specific availability failures were observed: Maryland returned 403 and Wisconsin timed out after 41 seconds. The published snapshot retained their 257 and 21 previously collected records.

The [live site](https://bd4l.github.io/breach-dashboard-v2/) and its JSON both returned HTTP 200, serving 17,420 reports and 18 source entries in live mode. A fresh restore from the actual remote state branch preserved every first-seen timestamp for the original 1,033 pilot records; full state contained 17,441 revisions after the Wisconsin date correction.

[Texas-only follow-up run 33991654414](https://github.com/BD4L/breach-dashboard-v2/actions/runs/33991654414) completed successfully, including merge and deployment. It restored the prior Actions state, accepted the same 625 reports, and recorded **zero new / zero changed**. Comparing both published snapshots confirmed all 17,420 report identities, first-seen timestamps, and revision numbers were preserved. This verifies persistence across separate actual Actions runs, not only a local round-trip test.
