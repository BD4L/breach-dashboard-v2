# Local verification — September 5, 2026

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
- Original tracked changes have the same SHA-256 as their preservation patch, and original working-tree status matches the saved baseline. New repository has no remote.

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

The original application is preserved. There is no remote repository, push, publication, migration, authenticated firm workspace, email service, or AI integration in this milestone. GitHub Actions workflow syntax/configuration has only local review until the workflow runs in a future repository.

## UI token pass

Replaced the ad hoc palette and accumulated CSS overrides with Open Props 1.7.23 and the semantic roles documented in `docs/design-tokens.md`. The component stylesheet now contains no literal palette colors. Working text renders at 14 px and metadata at 12 px; mobile inputs render at 16 px with 44 px controls. Pack imports, variable aliases, and the build-time favicon were independently reviewed.

Typechecking passed with zero project diagnostics. Root and `/breach-dashboard-v2/` static builds passed, as did the public-boundary check and whitespace checks. npm reported zero known vulnerabilities after installation. Existing upstream Vite deprecation notices remain.

Browser checks confirmed the rendered type/color values and no page-wide horizontal overflow at desktop width 1167 px or mobile widths 390 px and 320 px. All four view tabs fit at 390 px; narrower navigation remains horizontally scrollable. At 320 px, the save target and its column both measure 44 px and the target is contained. Source-status colors, mobile evidence navigation, and Escape-to-return were visually checked. The exact 1,033-report live preview snapshot was retained, and the checked-in demo export was restored byte-for-byte after building.
