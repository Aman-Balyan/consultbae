# ConsultBae Assignment — Task 1: Merge

## Status
Stage 1 (per-source cleaning) complete. Stage 2 (cross-source matching/merge into one DB) in progress.

## Structure
```
consultbae/
├── data/                     raw source CSVs (as provided)
├── src/
│   ├── normalize.py          reusable field-cleaning helpers
│   └── clean.py              Stage 1: clean each source independently, log every issue found
└── output/
    ├── clean_source1.csv     cleaned Naukri applicants
    ├── clean_source2.csv     cleaned gig workers
    ├── clean_source3.csv     cleaned CBNexus contacts
    └── stage1_issues_log.csv every data quality issue found + what was done about it
```

## How to run
```bash
pip install pandas
python3 src/clean.py
```
Run from the project root (`consultbae/`) — `clean.py` uses relative paths (`data/...`, `output/...`).

## What Stage 1 does
Cleans and normalizes each of the 3 raw CSVs **independently** (no cross-file matching yet —
that's Stage 2). For each source:
- Drops junk rows (fully blank rows, an embedded duplicate header row mid-file)
- Repairs a column-shifted row (source2, row 18) by classifying each value by content
  pattern (regex for email/rate, keyword match for status, comma-presence for skill tags,
  known-city lookup) rather than trusting column position
- Normalizes phone → digits-only, last 10 digits
- Normalizes email → lowercase, trimmed
- Normalizes city → trimmed/cased, known synonyms unified (Gurgaon=Gurugram, New Delhi=Delhi=Delhi NCR, Bangalore=Bengaluru)
- Normalizes status → lowercase enum; Verified → boolean
- Normalizes Applied Date → ISO format (handles 4 different input formats, one ambiguous slash-format assumed MM/DD/YYYY, documented in code)
- Normalizes rate → converts `k/month` values to `/hr` using a documented 160 hrs/month assumption
- Normalizes Current CTC → converts Lakhs-unit values (21 of 42 rows!) to absolute rupees
- Normalizes skills/skill_tags → clean lowercase deduped list

Every fix is logged to `output/stage1_issues_log.csv` with the source, row, what was wrong,
and what action was taken — this feeds directly into the Task 4 data issues report.

## Data issues found (summary — see stage1_issues_log.csv for full detail)
1. Phone formats inconsistent across all sources → normalized
2. Source2 has **no phone column at all** → later matching for these people relies on email/name+city
3. Exact duplicate person within source1 (`R. Verma` vs `Rohit Verma`, same email+phone) → deduped
4. Fully blank row in source2 → dropped
5. Column-shifted row in source2 (all 6 fields scrambled into wrong columns) → repaired
6. Embedded duplicate header row mid-file in source3 → dropped
7. City name chaos (casing, spacing, synonyms) → unified to canonical names
8. Status/Verified encoded inconsistently → normalized to enum/boolean
9. Applied Date in 4 different formats → normalized to ISO
10. Rate mixes ₹/hr and ₹k/month units → converted to consistent hourly rate
11. Current CTC mixes Lakhs and absolute-rupee units (half the rows!) → converted to consistent absolute rupees
12. Skills/tags inconsistent casing → normalized

## Next (Stage 2, not yet in this drop)
Match people across the 3 cleaned tables into one `persons` table using tiered logic:
phone match (strongest) → email match → name+city fallback (logged as low-confidence).
Will specifically guard against merging different real people who share a name
(e.g. multiple "Arjun Mehta" records with different phone numbers found in the raw data).

## Stuck log
(to be filled in as we go — required in final submission)
