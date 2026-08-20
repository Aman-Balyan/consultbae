# ConsultBae Assignment — Task 1: Merge

## Status
Stages 1, 2, 3 complete: clean -> merge -> load into SQLite. One clean database
now exists at `output/stage3/consultbae.db`, ready for Task 3 (audio app) to write into.

## Pipeline structure
Each stage reads a dedicated input folder and writes a dedicated output folder.
Stages are fully decoupled: changing a cleaning rule only requires editing
`normalize.py`/`clean.py` and rerunning from there — `merge.py` and `load_db.py`
never need to change, they just re-read whatever is sitting in the previous
stage's output folder.

```
data/                      raw input CSVs (untouched)
   |
   v   src/clean.py
output/stage1/             cleaned per-source CSVs + issues_log.csv
   |
   v   src/merge.py
output/stage2/             persons.csv, person_sources.csv, match_log.csv
   |
   v   src/load_db.py
output/stage3/consultbae.db   the actual deliverable database
```

## Structure
```
consultbae/
├── data/                          raw source CSVs (as provided)
├── src/
│   ├── normalize.py               reusable field-cleaning helpers
│   ├── clean.py                   Stage 1: clean each source independently, log every issue found
│   ├── merge.py                   Stage 2: match people across sources (tiered phone/email/name+city), merge
│   ├── load_db.py                 Stage 3: load merged output into a real SQLite database
│   └── run_pipeline.py            runs all 3 stages in sequence, one command
└── output/
    ├── stage1/                    cleaned per-source CSVs + issues_log.csv
    ├── stage2/                    persons.csv, person_sources.csv, match_log.csv
    └── stage3/consultbae.db       final SQLite database
```

## How to run
```bash
pip install pandas
python3 src/run_pipeline.py          # runs all 3 stages in order
```
Or run any stage individually (previous stage's output folder must already exist):
```bash
python3 src/clean.py       # -> output/stage1/
python3 src/merge.py       # -> output/stage2/
python3 src/load_db.py     # -> output/stage3/consultbae.db
```
Run from the project root (`consultbae/`) — all scripts use relative paths.

## Stage 1 — clean (per source, independent)
Cleans and normalizes each of the 3 raw CSVs **independently** (no cross-file
matching yet). For each source:
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
- Removes exact duplicates within the same file

Every fix is logged to `output/stage1/issues_log.csv`.

## Stage 2 — merge (match people across sources)
Matches records using **tiered confidence**, applied in strict order via a
union-find structure so matches are transitive:
1. **Tier 1 (high)**: exact normalized phone match
2. **Tier 2 (high)**: exact normalized email match
3. **Tier 3 (low)**: name + city fallback — ONLY applied to records tier 1/2 could
   not match to anyone, and always flagged as low confidence

This ordering matters: the raw data contains multiple real, distinct people
named "Arjun Mehta" in the same city with different phone numbers. If name+city
were used as a primary key they'd be wrongly merged; using it only as a last
resort keeps them correctly separate while still catching genuine matches that
lack a shared phone/email.

Result: 102 raw records -> 55 unique people (26 high-confidence merges, 5
low-confidence merges flagged for review, 24 records that only appear once).

## Stage 3 — load into SQLite
Loads Stage 2's output into `output/stage3/consultbae.db` with 4 tables:
`persons`, `person_sources` (traceability back to raw rows), `match_log`
(which rule matched which records), and an empty `audio_submissions` table
(foreign-keyed to `persons`, ready for Task 3 to populate).

## Data issues found (summary — see output/stage1/issues_log.csv for full detail)
1. Phone formats inconsistent across all sources → normalized
2. Source2 has **no phone column at all** → matching for these people relies on email/name+city
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
13. **Name collisions across sources**: multiple distinct real people share the exact
    same name (e.g. "Arjun Mehta") → tiered matching (phone/email first) prevents
    wrongly merging them; only merged via low-confidence name+city fallback when
    no stronger signal exists, and flagged as such

## Next
Task 2 (n8n automation), Task 3 (audio app writing into `audio_submissions`).

## Stuck log
(to be filled in as we go — required in final submission)
