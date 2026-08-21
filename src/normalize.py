"""
normalize.py
Shared, source-agnostic normalization helpers.
Each function takes a raw messy value and returns a clean value (or None if unusable).
Keeping these separate from the per-source cleaners so the same logic is reused
consistently everywhere phone/email/city/etc. show up, instead of drifting.
"""
import re
from datetime import datetime


def norm_phone(raw):
    """Strip everything but digits, keep the last 10 (Indian mobile numbers).
    Handles: +919000000254, 919000000254, 9000000237, +91-9000000131, 09000000287
    Returns None if we can't get a plausible 10-digit number.
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) < 10:
        return None
    return digits[-10:]


def norm_email(raw):
    """Lowercase + trim. Returns None for missing/blank."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s == "nan":
        return None
    # very loose sanity check, we are not validating deliverability
    if "@" not in s or "." not in s.split("@")[-1]:
        return None
    return s


def norm_name(raw):
    """Trim whitespace, collapse internal double-spaces, Title Case.
    Keeps 'R.' style initials as-is rather than guessing the full name.
    """
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip())
    if not s or s.lower() == "nan":
        return None
    return s.title()


# Known city synonym clusters -> one canonical name.
# Delhi / New Delhi / Delhi NCR are treated as one canonical "Delhi" bucket
# since the source files use them interchangeably for the same metro area.
# Gurgaon / Gurugram are the same city (official rename), unified to "Gurugram".
_CITY_SYNONYMS = {
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "new delhi": "Delhi",
    "delhi ncr": "Delhi",
    "delhi": "Delhi",
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "pune": "Pune",
    "noida": "Noida",
}


def norm_city(raw):
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip()).lower()
    if not s or s == "nan":
        return None
    return _CITY_SYNONYMS.get(s, s.title())


def norm_status(raw):
    """Lowercase enum: active / inactive / paused / unknown."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("active", "inactive", "paused"):
        return s
    return "unknown" if s and s != "nan" else None


def norm_bool(raw):
    """Map Y/N/Yes/No/yes/No -> True/False. Returns None if unrecognized."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("y", "yes", "true", "1"):
        return True
    if s in ("n", "no", "false", "0"):
        return False
    return None


def norm_date(raw):
    """Parse several date formats seen in source1 into ISO YYYY-MM-DD.
    Formats observed: 24-07-2026 (DD-MM-YYYY), 2026-08-08 (YYYY-MM-DD), 7 Jul 2026 (D Mon YYYY)
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    # NOTE on ambiguity: slash-separated dates are assumed MM/DD/YYYY (US-style),
    # distinct from the dash-separated DD-MM-YYYY values elsewhere in this column.
    # Justification: other slash values in this file (e.g. 08/19/2026) have a
    # day-of-month > 12, which is only valid if the first number is the month.
    # A few values (e.g. 07/03/2026) are inherently ambiguous either way; this
    # assumption is applied consistently and documented in the data issues report.
    fmts = ["%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None  # unparseable, log and move on rather than guessing


def norm_rate_to_hourly(raw, hours_per_month=160):
    """Source2 'rate' mixes ₹/hr and ₹/month (k/month) units.
    Convert everything to a consistent ₹/hr figure so rates are comparable.
    Assumption: 160 working hours/month for the k/month -> /hr conversion
    (documented here + in the data issues report, this is a judgment call).
    Returns (hourly_rate: float|None, was_converted: bool)
    """
    if raw is None:
        return None, False
    s = str(raw).strip().lower().replace(" ", "")
    if not s or s == "nan":
        return None, False
    m = re.match(r"^([\d.]+)/hr$", s)
    if m:
        return float(m.group(1)), False
    m = re.match(r"^([\d.]+)k/month$", s)
    if m:
        monthly = float(m.group(1)) * 1000
        return round(monthly / hours_per_month, 2), True
    return None, False


def norm_ctc(raw, lakh_threshold=100):
    """source1 'Current CTC' mixes units: most rows are absolute rupees
    (e.g. 417964), but a chunk of rows (21 of 42) are in Lakhs (e.g. 4.2 = 4.2L).
    Any value under lakh_threshold is assumed to be Lakhs and converted to
    absolute rupees for consistency. Returns (value, was_converted).
    """
    if raw is None:
        return None, False
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None, False
    if v < lakh_threshold:
        return round(v * 100000, 2), True
    return v, False


def norm_skills(raw):
    """Split a comma-separated skills/tags string into a clean, deduped,
    lowercase, sorted list. Casing varies wildly across sources
    (e.g. 'REST APIs' vs 'rest apis') so we lowercase for matching but
    could re-title-case for display later.
    """
    if raw is None:
        return []
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return []
    parts = [re.sub(r"\s+", " ", p.strip().lower()) for p in s.split(",")]
    parts = [p for p in parts if p]
    return sorted(set(parts))
