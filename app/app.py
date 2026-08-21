"""
app.py
Task 3 -- mini audio collection app.

A person enters their name + phone, records audio in the browser (MediaRecorder
API) or uploads an audio file, submits -- the file is stored, its properties
(duration, sample rate, bitrate, loudness, rough quality note) are extracted
via audio_utils.py, and a row is written into the SAME database Task 1 built
(output/stage3/consultbae.db), linking to an existing person by phone if one
already exists, or creating a new minimal person record if not.

Run with:  python3 app.py
Then open: http://localhost:5000
"""
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import Flask, request, render_template, redirect, url_for, send_from_directory, flash

from audio_utils import analyze_audio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "..", "output", "stage3", "consultbae.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "dev-only-secret"  # fine for a local take-home demo, not for real prod use


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def norm_phone(raw):
    """Same normalization rule as src/normalize.py's norm_phone, kept as a
    small local copy so this app doesn't need to import from ../src -- the
    two are logically the same rule, duplicated deliberately for simplicity
    of a standalone demo app rather than sharing a package across folders.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[-10:] if len(digits) >= 10 else None


def find_or_create_person(conn, name, phone):
    """Look up an existing person by normalized phone; reuse if found.
    Otherwise create a new minimal person record so every audio submission
    is always linked to a person row in Task 1's database, per the
    assignment's requirement.
    """
    cur = conn.cursor()
    row = cur.execute("SELECT person_id FROM persons WHERE phone = ?", (phone,)).fetchone()
    if row:
        return row["person_id"]

    max_id = cur.execute(
        "SELECT person_id FROM persons WHERE person_id LIKE 'P%' ORDER BY person_id DESC LIMIT 1"
    ).fetchone()
    next_num = int(max_id["person_id"][1:]) + 1 if max_id else 1
    new_id = f"P{next_num:04d}"

    cur.execute(
        """INSERT INTO persons (person_id, name, phone, sources, num_source_records, match_confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (new_id, name, phone, "audio_app", 1, "app_submission"),
    )
    conn.commit()
    return new_id


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    name = (request.form.get("name") or "").strip()
    phone_raw = (request.form.get("phone") or "").strip()
    audio_file = request.files.get("audio")

    if not name or not phone_raw or not audio_file or audio_file.filename == "":
        flash("Name, phone, and an audio recording/file are all required.")
        return redirect(url_for("index"))

    phone = norm_phone(phone_raw)
    if phone is None:
        flash("Phone number doesn't look valid -- need at least 10 digits.")
        return redirect(url_for("index"))

    # figure out a sane file extension from whatever the browser/upload sent
    original_name = audio_file.filename
    ext = os.path.splitext(original_name)[1]
    if not ext:
        mime_to_ext = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/mpeg": ".mp3"}
        ext = mime_to_ext.get(audio_file.mimetype, ".webm")
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, stored_filename)
    audio_file.save(filepath)

    try:
        props = analyze_audio(filepath)
    except RuntimeError as e:
        os.remove(filepath)
        flash(f"Couldn't process that audio file: {e}")
        return redirect(url_for("index"))

    conn = get_db()
    person_id = find_or_create_person(conn, name, phone)

    conn.execute(
        """INSERT INTO audio_submissions
           (person_id, name, phone, audio_path, duration_sec, sample_rate_hz,
            bitrate_kbps, loudness_db, quality_note, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (person_id, name, phone_raw, stored_filename, props["duration_sec"],
         props["sample_rate_hz"], props["bitrate_kbps"], props["loudness_db"],
         props["quality_note"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    flash("Submitted! Your recording has been saved.")
    return redirect(url_for("submissions"))


@app.route("/submissions")
def submissions():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audio_submissions ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()
    return render_template("submissions.html", submissions=rows)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        raise SystemExit(
            f"Database not found at {DB_PATH}. Run the Task 1 pipeline first:\n"
            f"  python3 ../src/run_pipeline.py"
        )
    app.run(debug=True, host="0.0.0.0", port=5000)
