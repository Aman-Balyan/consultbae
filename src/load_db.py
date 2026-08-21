"""
load_db.py
Stage 3 of the pipeline: load Stage 2's merged output into a real SQLite
database with a proper schema. This is the "one clean database" the
assignment asks for -- everything before this point was CSVs for easy
inspection/debugging, this is the actual deliverable database.

Reads from:  output/stage2/  (persons.csv, person_sources.csv, match_log.csv)
Writes to:   output/stage3/consultbae.db

Schema:
  persons          one row per real, deduplicated person
  person_sources   traceability: which raw source rows fed into each person
  match_log        which matching rule (phone/email/name+city) merged which records
  audio_submissions  (created empty here, populated later by the Task 3 audio app)
"""
import os
import sqlite3
import ast
import pandas as pd

IN_DIR = "output/stage2"
OUT_DIR = "output/stage3"
DB_PATH = f"{OUT_DIR}/consultbae.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    person_id           TEXT PRIMARY KEY,
    name                TEXT,
    email               TEXT,
    phone               TEXT,
    city                TEXT,
    sources             TEXT,     -- comma-separated list of source files this person appeared in
    num_source_records  INTEGER,
    match_confidence    TEXT,     -- 'high' (phone/email matched), 'low' (name+city fallback), 'unmatched' (single source)
    experience_years    REAL,
    current_ctc         REAL,
    applied_date        TEXT,
    status              TEXT,
    hourly_rate         REAL,
    verified            INTEGER,  -- 0/1/NULL
    projects_completed  INTEGER,
    skills              TEXT      -- comma-separated tag list
);

CREATE TABLE IF NOT EXISTS person_sources (
    person_id       TEXT,
    source          TEXT,
    source_row_id   INTEGER,
    FOREIGN KEY (person_id) REFERENCES persons(person_id)
);

CREATE TABLE IF NOT EXISTS match_log (
    tier        INTEGER,   -- 1=phone, 2=email, 3=name+city fallback
    key_type    TEXT,
    key_value   TEXT,
    uids        TEXT,      -- which source records were merged by this rule
    confidence  TEXT
);

CREATE TABLE IF NOT EXISTS audio_submissions (
    submission_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       TEXT,           -- links back to persons table (Task 3 requirement)
    name            TEXT,
    phone           TEXT,
    audio_path      TEXT,
    duration_sec    REAL,
    sample_rate_hz  INTEGER,
    bitrate_kbps    REAL,
    loudness_db     REAL,
    quality_note    TEXT,
    submitted_at    TEXT,
    FOREIGN KEY (person_id) REFERENCES persons(person_id)
);
"""


def load():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # rebuild fresh each run so the pipeline stays idempotent

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    persons = pd.read_csv(f"{IN_DIR}/persons.csv", dtype={"phone": "string", "person_id": "string"})
    persons["phone"] = persons["phone"].str.replace(r"\.0$", "", regex=True)
    # flatten the python-list-as-string skills column into a comma-separated string for SQL
    def flatten_skills(v):
        if pd.isna(v):
            return None
        try:
            items = ast.literal_eval(v) if isinstance(v, str) and v.startswith("[") else v
            return ",".join(items) if isinstance(items, list) else str(items)
        except (ValueError, SyntaxError):
            return str(v)
    persons["skills"] = persons["skills"].apply(flatten_skills)
    persons["verified"] = persons["verified"].map({True: 1, False: 0, "True": 1, "False": 0})

    person_sources = pd.read_csv(f"{IN_DIR}/person_sources.csv")
    match_log = pd.read_csv(f"{IN_DIR}/match_log.csv")

    persons.to_sql("persons", conn, if_exists="append", index=False)
    person_sources.to_sql("person_sources", conn, if_exists="append", index=False)
    match_log.to_sql("match_log", conn, if_exists="append", index=False)

    conn.commit()
    return conn


if __name__ == "__main__":
    conn = load()
    cur = conn.cursor()

    print(f"[stage3] read merged output from {IN_DIR}/, built database at {DB_PATH}")
    for table in ("persons", "person_sources", "match_log", "audio_submissions"):
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"[stage3] table '{table}': {n} rows")

    print()
    print("[stage3] sample query -- people matched with LOW confidence (need review):")
    for row in cur.execute("SELECT person_id, name, email, phone, city FROM persons WHERE match_confidence='low'"):
        print("  ", row)

    conn.close()
