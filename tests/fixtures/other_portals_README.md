# Other public portal parser fixtures

Captured from official public pages on September 5, 2026 with an identifiable,
anonymous request and certificate validation. HTML fixtures retain a small number
of rows/paragraphs for schema regression tests; they are not complete collections.

- `other_portals_montana.html`: first two rows and named headers from
  https://dojmt.gov/office-of-consumer-protection/reported-data-breaches/.
  `data-row_id` values are original. The real table configuration explicitly sets
  `defer_row_limit: false`; the fixture retains that field in a minimal script.
- `other_portals_washington.html`: first two rows and original Drupal pager from
  https://www.atg.wa.gov/data-breach-notifications. Terminal-page and loop variants
  are deliberately constructed in tests from the observed pager structure.
- `other_portals_south_carolina.html`: current first row, the actual `12/19,2024`
  typo, and two real Morgan Stanley rows with the same organization, date, and
  notice URL but conflicting counts. Both ambiguous rows must be withheld; neither
  summing nor choosing one has source support.
  https://consumer.sc.gov/identity-theft-unit/security-breach-notices
- `other_portals_delaware.html`: initial rows including addendum annotations, a
  multiple-reported-date row and one ordinary older row from
  https://attorneygeneral.delaware.gov/fraud/cpu/securitybreachnotification/database/.
- `other_portals_wisconsin.html`: original labeled paragraphs for the first two
  organizations, limited to organization, incident date, public notification date,
  and Wisconsin count, from
  https://datcp.wi.gov/Pages/Programs_Services/DataBreaches.aspx. The real source is
  prose, not the table expected by the old collector.
- `other_portals_new_jersey.html`: the actual HTTP200 Incapsula response body from
  https://www.cyber.nj.gov/threat-landscape/public-data-breaches. HTTP200 does not
  establish that the response contains breach records. No challenge was bypassed.

The New Hampshire official listing returned HTTP403. It has no guessed-document
fixture and no hard-coded fallback list. A mock proves the access error propagates
without PDF discovery attempts.
