The official Delaware AG parent page currently links its Data Security Breach
Database to `https://data.delaware.gov/Public-Safety/Data-Security-Breach-Database/dir6-wx8v/data_preview`.
The old HTML database contains 322 records ending in July 2025.

Metadata and three reduced public rows were captured anonymously on September 5,
2026 from `/api/views/dir6-wx8v.json` and the published SODA 2.1 resource
`/resource/dir6-wx8v.json` on `data.delaware.gov`. The complete dataset had 459
rows, independently confirmed with `$select=count(*)`, and notice dates through
August 12, 2026. No access token or authenticated API was used.

`ingestion/delaware_legacy_ids.json` preserves 137 one-to-one matches between the
new source's published `:id` and the old collector's native ID plus reported date.
Matches required an identical canonical notice document URL and an organization
name identical after punctuation/whitespace/case normalization. Both old and new
match groups had to contain exactly one record. Ambiguous and unmatched records
were not merged. The mapping contains public identifiers, match fingerprints,
and verified legacy source dates, breach ranges and resident counts.
All mapped IDs/dates were independently compared with the actual published first
recovery snapshot. A stored match fingerprint is checked on every current row;
changed document/organization pairs are withheld instead of inheriting old data.

Verified legacy breach ranges and affected counts are also retained in the map.
A missing current end-date field is filled only when the current start exactly
matches the legacy start. Conflicting starts retain the old range as explicit
historical context, never as a synthesized current range. A genuinely absent
current original affected count can retain its verified legacy value, explicitly
marked as prior evidence. New nonempty counts take precedence; malformed values
never trigger a legacy substitution. No dates or counts are summed.
Current Date of Notice values are not promoted to AG receipt/publication dates.
