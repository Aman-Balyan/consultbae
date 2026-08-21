"""
run_pipeline.py
Runs the full pipeline in sequence: clean -> merge -> load into DB.

Each stage is fully independent and reads/writes its own folder, so if you
change a cleaning rule in normalize.py/clean.py, you only need to rerun this
whole pipeline (or just rerun clean.py then merge.py then load_db.py by
hand) -- merge.py and load_db.py never need to change just because a
formatting rule changed upstream, since they only care about the *shape* of
the previous stage's output folder, not how it was produced.

    data/            (raw input CSVs, untouched)
        |
        v   clean.py
    output/stage1/   (cleaned per-source CSVs + issues_log.csv)
        |
        v   merge.py
    output/stage2/   (persons.csv, person_sources.csv, match_log.csv)
        |
        v   load_db.py
    output/stage3/   (consultbae.db -- the actual deliverable database)

Usage:
    python3 src/run_pipeline.py
"""
import subprocess
import sys

STAGES = [
    ("Stage 1: clean", "src/clean.py"),
    ("Stage 2: merge", "src/merge.py"),
    ("Stage 3: load into SQLite", "src/load_db.py"),
]

if __name__ == "__main__":
    for label, script in STAGES:
        print(f"\n{'='*60}\n{label}\n{'='*60}")
        result = subprocess.run([sys.executable, script])
        if result.returncode != 0:
            print(f"\n[run_pipeline] {label} FAILED, stopping.")
            sys.exit(1)
    print(f"\n{'='*60}\nPipeline complete. Database at output/stage3/consultbae.db\n{'='*60}")
