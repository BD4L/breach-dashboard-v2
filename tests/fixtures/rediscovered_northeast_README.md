# Massachusetts and New Hampshire recovered publication fixtures

Captured September 5, 2026 from current public government sources. These fixtures
contain source publication fields only. They omit cookies, browser keys,
authorization state, contacts, cache tags, account metadata, and unrelated page
application state. Network access is mocked in every test.

## Massachusetts: annual reports preferred

The canonical [annual index](https://www.mass.gov/lists/data-breach-notification-reports)
links the current and previous annual PDFs. Ordinary requests with the project's
truthful declared identity successfully collected both years in 3 requests,
2,727,529 bytes, and approximately 20.5 seconds:

- 2026: 1,507 reports, zero rejected; 150 pages.
- 2025: 2,198 reports, zero rejected.

The full [2026 PDF](https://www.mass.gov/doc/data-breach-report-2026/download)
was 1,143,752 bytes; SHA-256
`950fcf90df76f2a160d8927cb85ea91e693ef14fc1354d3461661643ea4f99fa`.
`rediscovered_ma_pdf_geometry.pdf` contains only source pages 67 and 100 from that
PDF, copied with pypdfium2. It is a real source fixture, not a generated table:

- Page 67's last row (2026-694) has vertical column borders and bottom endpoint
  marks, but lacks a full bottom horizontal rule. Default table extraction drops
  that row. The parser adds only the bottom boundary established by that source
  geometry and then requires all source ID-column values to reconcile.
- Page 100 wraps four-digit native IDs across lines. The parser reads the named
  ID column independently and normalizes that line wrapping only in ID cells.
- If source IDs and tables still disagree, or the necessary source geometry is
  absent, the annual document fails. Text heuristics do not establish complete
  historical coverage. The resulting annual collection remains partial because
  no independent source record total is available.

The collector discovers actual current/prior-year links, honors `max_pages` as
an annual-document limit, keeps a 500-page cap per PDF, and preserves a successfully
parsed current annual batch if the next annual document fails. Native breach
numbers are retained, so records can revise existing annual observations.

## Massachusetts: official letter fallback

The [letter archive](https://www.mass.gov/archive/data-breach-notification-letters)
loaded ordinary HTTP200 HTML and actually linked nine 2026 month pages and all
twelve 2025 month pages at capture time. `rediscovered_ma_archive.html` retains
only its heading and those real month links.

`rediscovered_ma_september_2026.html` is reduced from a normal Chrome DOM capture
of the [September page](https://www.mass.gov/lists/data-breach-notification-letters-september-2026).
It retains the heading and 35 actual letter anchors with native breach numbers,
organizations, and official document URLs. The source's absent number 2026-1474
is not filled in. The monthly page also subsequently loaded through ordinary
public HTTP with the project identity.

This archive explicitly excludes notices delivered without a letter. Month
membership does not establish a complete receipt/publication date or affected
resident count. Letter records therefore leave those fields unknown, declare
partial coverage, and set `new_records_only=True` so richer existing annual rows
are preserved. A default run visits at most 24 actual current/prior-year month
links. The fallback is used only when the annual route produces no usable batch.

## New Hampshire: current public document API

The [current official listing](https://www.doj.nh.gov/citizens/consumer-protection-antitrust-bureau/security-breach-notifications)
loads its grid with an actual browser GET to
[the public document API](https://www.doj.nh.gov/content/api/documents?iterate_nodes=true&q=%40field_document_category%7C%3D%7C2146&textsearch=&sort=field_date_posted%7Cdesc%7CALLOW_NULLS&filter_mode=inclusive&type=document&page=1&size=15).
The observed category `2146` is the breach category. The default UI page size is
15; the visible UI also offers 25, used by the bounded collector.

`rediscovered_nh_api.json` retains all 15 rows from one actual HTTP200 JSON response
captured in normal local Chrome. The source declared 9,937 documents and 663 pages
at size 15. The fixture retains only the envelope counts and the row fields used
by the parser: native node ID, title, published moderation state, breach category,
explicit date posted, and actual PDF URI. Other nested metadata is omitted.

Native IDs come from agreeing `id` and `fields.nid` fields. Publication dates come
only from `fields.field_date_posted`; filenames and generic creation timestamps
are not dates for the dashboard. PDFs on `mm.nh.gov` are linked, never downloaded
by this collector; counts remain unknown. Collection defaults to 30 pages of 25
rows (at most 750 documents), validates counts and IDs on every page, and declares
partial coverage unless it reconciles the complete source total. An error after
valid pages retains that partial batch; an initial denial is a source failure.

The parser and API contract are recovered, but unattended access remains limited:
ordinary HTTP returned 403 locally and on the parent integration's GitHub-hosted
operating-system probes; its Linux headless Chrome probe was also denied. Normal
local Chrome returned 200. These results do not establish that the publication
was withdrawn. No proxy, challenge solving, authentication workaround, search
provider key, or guessed document path is used by the collector.

`rediscovered_northeast_discovery.json` records the final reduced source contracts
and evidence. Synthetic pagination and malformed-response variants are clearly
constructed inside the tests around these captured schemas.
