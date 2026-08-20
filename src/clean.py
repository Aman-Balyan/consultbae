"""
clean.py
Stage 1 of the pipeline: clean + normalize each source CSV independently.
No cross-file matching happens here on purpose -- that's Stage 2 (merge.py).
Each clean_sourceN() function:
  - reads the raw CSV
  - drops junk rows (blank rows, embedded header rows) with a logged reason
  - repairs/handles structurally broken rows (shifted columns) where possible
  - normalizes every field via normalize.py helpers
  - returns (clean_df, issues: list[dict])
"""
import re
import pandas as pd
from normalize import (
    norm_phone, norm_email, norm_name, norm_city,
    norm_status, norm_bool, norm_date, norm_rate_to_hourly, norm_ctc, norm_skills,
)

ISSUES = []  # global log, one dict per issue found, dumped to CSV at the end


def _log(source, row_ref, issue, action):
    ISSUES.append({"source": source, "row_ref": row_ref, "issue": issue, "action": action})


# ---------------------------------------------------------------------------
# Source 1: Naukri applicants
# ---------------------------------------------------------------------------
def clean_source1(path="data/source1_naukri_applicants.csv"):
    raw = pd.read_csv(path)
    rows = []
    for idx, r in raw.iterrows():
        name = norm_name(r.get("Full Name"))
        email = norm_email(r.get("Email"))
        phone = norm_phone(r.get("Phone"))
        city = norm_city(r.get("City"))
        exp = r.get("Experience (Years)")
        ctc, ctc_converted = norm_ctc(r.get("Current CTC"))
        if ctc_converted:
            _log("source1", idx, f"Current CTC given in Lakhs ({r.get('Current CTC')}), converted to absolute rupees", "converted")
        applied = norm_date(r.get("Applied Date"))
        if r.get("Applied Date") and applied is None:
            _log("source1", idx, f"unparseable Applied Date: {r.get('Applied Date')!r}", "set to null")
        skills = norm_skills(r.get("Skills"))

        if phone is None:
            _log("source1", idx, f"unusable phone: {r.get('Phone')!r}", "set to null")
        if email is None:
            _log("source1", idx, f"unusable/missing email: {r.get('Email')!r}", "set to null")

        rows.append({
            "source": "source1_naukri", "source_row_id": idx,
            "name": name, "email": email, "phone": phone, "city": city,
            "experience_years": exp, "current_ctc": ctc,
            "applied_date": applied, "skills": skills,
        })
    df = pd.DataFrame(rows)

    # exact duplicate rows within this source (same email+phone) e.g. "R. Verma" / "Rohit Verma"
    dupe_mask = df.duplicated(subset=["email", "phone"], keep="first") & df["email"].notna()
    for idx in df[dupe_mask].index:
        _log("source1", idx, f"exact duplicate of an earlier row (same email+phone), name={df.loc[idx,'name']!r}", "dropped")
    df = df[~dupe_mask].reset_index(drop=True)

    return df, ISSUES


# ---------------------------------------------------------------------------
# Source 2: Gig workers
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_source2(path="data/source2_gig_workers.csv"):
    raw = pd.read_csv(path, dtype=str)  # keep everything as string first, we validate/repair manually
    rows = []
    for idx, r in raw.iterrows():
        vals = r.to_dict()

        # fully blank row -> drop
        if all(pd.isna(v) or str(v).strip() == "" for v in vals.values()):
            _log("source2", idx, "fully blank row", "dropped")
            continue

        email_id = vals.get("email_id")
        worker_name = vals.get("worker_name")
        rate = vals.get("rate")
        location = vals.get("location")
        status = vals.get("status")
        skill_tags = vals.get("skill_tags")

        # Column-shift detection: if email_id column does NOT look like an email
        # but one of the other columns does, the row's fields have slid over.
        # Repair by re-mapping using content pattern instead of column position.
        if email_id and not _EMAIL_RE.match(str(email_id).strip()):
            str_vals = [str(v).strip() for v in vals.values() if pd.notna(v) and str(v).strip()]

            # Classify every value by content pattern -- never rely on leftover
            # positional order, since that's what caused the shift in the first
            # place and blindly re-using position just relocates the bug.
            fixed_email = next((v for v in str_vals if _EMAIL_RE.match(v)), None)
            rate_guess = next((v for v in str_vals if re.match(r"^[\d.]+(/hr|k/month)$", v.replace(" ", ""))), None)
            status_guess = next((v for v in str_vals if v.lower() in ("active", "inactive", "paused")), None)
            # skill_tags is the only field that is a comma-separated list of >=2 items
            tags_guess = next((v for v in str_vals if "," in v), None)
            used = {fixed_email, rate_guess, status_guess, tags_guess}
            remaining = [v for v in str_vals if v not in used]
            # of what's left, a known city name is the location; the other is the person's name
            known_cities = {"pune", "noida", "delhi", "new delhi", "gurgaon", "gurugram",
                             "bengaluru", "bangalore", "delhi ncr"}
            loc_guess = next((v for v in remaining if v.lower() in known_cities), None)
            name_guess = next((v for v in remaining if v != loc_guess), None)

            if fixed_email:
                _log("source2", idx,
                     f"column-shifted row detected (email found in wrong column): raw={vals}",
                     "repaired by content-pattern classification of every field")
                email_id, worker_name, rate = fixed_email, name_guess, rate_guess
                location, status, skill_tags = loc_guess, status_guess, tags_guess
            else:
                _log("source2", idx, f"row structurally broken, no email found anywhere: {vals}", "dropped")
                continue

        email = norm_email(email_id)
        name = norm_name(worker_name)
        city = norm_city(location)
        status_n = norm_status(status)
        hourly_rate, was_converted = norm_rate_to_hourly(rate)
        if was_converted:
            _log("source2", idx, f"rate given as monthly ({rate}), converted to hourly using 160 hrs/month assumption", "converted")
        if rate and hourly_rate is None:
            _log("source2", idx, f"unparseable rate: {rate!r}", "set to null")
        tags = norm_skills(skill_tags)

        if email is None:
            _log("source2", idx, f"unusable/missing email: {email_id!r}", "set to null")

        rows.append({
            "source": "source2_gig", "source_row_id": idx,
            "name": name, "email": email, "phone": None,  # source2 has no phone field at all
            "city": city, "status": status_n, "hourly_rate": hourly_rate, "skills": tags,
        })
    if not any(r.get("phone") for r in rows):
        _log("source2", "ALL", "source file has no phone number column at all", "matching for this source relies on email/name+city only")

    return pd.DataFrame(rows), ISSUES


# ---------------------------------------------------------------------------
# Source 3: CBNexus contacts
# ---------------------------------------------------------------------------
def clean_source3(path="data/source3_cbnexus_contacts.csv"):
    raw = pd.read_csv(path, dtype=str)
    rows = []
    for idx, r in raw.iterrows():
        name_raw = r.get("Name")
        # embedded header row repeated mid-file (literal header values as data)
        if str(name_raw).strip() == "Name" and str(r.get("Phone Number")).strip() == "Phone Number":
            _log("source3", idx, "embedded duplicate header row found mid-file", "dropped")
            continue

        name = norm_name(name_raw)
        phone = norm_phone(r.get("Phone Number"))
        city = norm_city(r.get("City"))
        verified = norm_bool(r.get("Verified"))
        projects = r.get("Projects Completed")
        try:
            projects_n = int(projects)
        except (TypeError, ValueError):
            projects_n = None
            if projects and str(projects).strip():
                _log("source3", idx, f"unparseable Projects Completed: {projects!r}", "set to null")

        if phone is None:
            _log("source3", idx, f"unusable phone: {r.get('Phone Number')!r}", "set to null")

        rows.append({
            "source": "source3_cbnexus", "source_row_id": idx,
            "name": name, "email": None, "phone": phone, "city": city,
            "verified": verified, "projects_completed": projects_n,
        })
    return pd.DataFrame(rows), ISSUES


if __name__ == "__main__":
    d1, _ = clean_source1()
    d2, _ = clean_source2()
    d3, _ = clean_source3()

    d1.to_csv("output/clean_source1.csv", index=False)
    d2.to_csv("output/clean_source2.csv", index=False)
    d3.to_csv("output/clean_source3.csv", index=False)
    pd.DataFrame(ISSUES).to_csv("output/stage1_issues_log.csv", index=False)

    print(f"source1: {len(d1)} clean rows")
    print(f"source2: {len(d2)} clean rows")
    print(f"source3: {len(d3)} clean rows")
    print(f"issues logged: {len(ISSUES)}")
