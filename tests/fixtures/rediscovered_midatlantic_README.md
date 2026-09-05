# Rediscovered Mid-Atlantic source fixtures

Reviewed September 5, 2026. These are public source fixtures, not client records.

- `rediscovered_midatlantic_catalog.json` is the actual anonymous Maryland catalog
  response, restricted to public, non-hidden lists whose names start with
  `Security-Breach-Notices`. It exposes annual list counts for 2022–2025 and an
  unversioned older list. No 2026 annual list was present. The collector follows
  the two latest actually published annual lists and validates their row counts.
  Official endpoint:
  `https://oag.maryland.gov/resources-info/_api/web/lists?$select=Title,Hidden,ItemCount&$filter=startswith(Title,'Security-Breach-Notices')%20and%20Hidden%20eq%20false`
- `rediscovered_midatlantic_wisconsin_archive.html` retains selected labeled
  fields from two actual archived notices, including one older notice whose
  affected-person prose gives a national total but no dedicated Wisconsin count.
  Official linked archive:
  `https://datcp.wi.gov/Pages/Programs_Services/DataBreachArchive.aspx`
  The current 2026 page remains `DataBreaches.aspx`. The separately indexed
  `DataBreachDatabase.aspx` contains old 2019–2020 records and was not adopted as a
  current replacement. Anonymous SharePoint Pages API access returned 401 and
  was not used.
- `rediscovered_midatlantic_rss_synthetic.xml` is explicitly a synthetic RSS
  contract fixture. It does not establish live NJ feed schema fidelity. The
  official New Jersey navigation, captured by the New Jersey State Library,
  links both `https://www.cyber.nj.gov/rss.xml` and the newer
  `/threat-center/public-data-breaches` route. Archived official navigation:
  `https://dspace.njstatelib.org/bitstreams/8eb598d0-7280-40b4-bf9d-accaf6238801/download`
  Anonymous live RSS access returned HTTP403; the current listing returned an
  access challenge. No live NJ reports were manufactured from archive screenshots,
  third-party summaries, or guessed documents. No access challenge was bypassed.

Tests also reuse the prior actual Maryland item-schema and current Wisconsin
prose fixtures. The mocked transport demonstrates that Maryland discovery no
longer depends on loading the HTML landing page, while preserving existing IDs.
