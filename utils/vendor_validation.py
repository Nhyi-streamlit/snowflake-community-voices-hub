"""Validation for vendor event submissions (single form and bulk upload). Pure functions, no Streamlit."""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse

import pandas as pd

FORMATS = [
    "In-person conference", "Hybrid conference", "Virtual conference",
    "Community meetup (in-person)", "Community meetup (virtual)", "University / academic", "Other",
]

# field -> (label, max length)
FIELDS = {
    "organizer_name": ("Your full name", 200),
    "organizer_org": ("Organization", 200),
    "event_name": ("Event name", 300),
    "event_website": ("Event website", 500),
    "event_start": ("Start date", 10),
    "event_end": ("End date", 10),
    "event_city": ("City", 200),
    "event_country": ("Country", 100),
    "event_format": ("Format", 100),
    "expected_audience": ("Expected audience", 50),
    "event_description": ("Event description", 2000),
    "speaker_topic": ("Speaker topic", 2000),
    "cfp_link": ("CFP link", 500),
    "cfp_deadline": ("CFP deadline", 10),
}

STEP_FIELDS = {
    1: ["organizer_name", "organizer_org"],
    2: ["event_name", "event_start", "event_end", "event_city", "event_country", "event_format",
        "event_website", "expected_audience", "event_description"],
    3: ["speaker_topic", "cfp_link", "cfp_deadline"],
}
REQUIRED = {"organizer_name", "organizer_org", "event_name", "event_start", "event_city",
            "event_country", "event_format", "speaker_topic"}
URL_FIELDS = ("event_website", "cfp_link")
DATE_FIELDS = ("event_start", "event_end", "cfp_deadline")

BULK_COLUMNS = ["organizer_name", "organizer_org", "event_name", "event_start", "event_city",
                "event_country", "event_format", "speaker_topic", "event_end", "event_website",
                "cfp_link", "cfp_deadline"]
EXAMPLE_ROW = {
    "organizer_name": "Ada Lovelace", "organizer_org": "Data Community Lagos",
    "event_name": "Lagos Data Summit 2027", "event_start": "2027-03-14", "event_city": "Lagos",
    "event_country": "Nigeria", "event_format": "In-person conference",
    "speaker_topic": "Building AI apps on Snowflake", "event_end": "2027-03-15",
    "event_website": "https://example.com/summit", "cfp_link": "https://example.com/cfp",
    "cfp_deadline": "2027-01-31",
}


def is_url(value: str) -> bool:
    p = urlparse(value.strip())
    return p.scheme in ("http", "https") and bool(p.netloc) and "." in p.netloc


def to_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def validate(draft: dict, fields=None, today: date | None = None) -> dict[str, str]:
    """Return {field: error message} for the given fields (default: all)."""
    today = today or date.today()
    fields = list(fields or FIELDS)
    errors: dict[str, str] = {}
    for f in fields:
        v = draft.get(f)
        label, cap = FIELDS[f]
        if f in REQUIRED and _blank(v):
            errors[f] = f"{label} is required."
            continue
        if _blank(v):
            continue
        if f in DATE_FIELDS:
            if to_date(v) is None:
                errors[f] = f"{label} must be a date (YYYY-MM-DD)."
            continue
        s = str(v).strip()
        if len(s) > cap:
            errors[f] = f"{label} must be {cap} characters or fewer."
        elif f in URL_FIELDS and not is_url(s):
            errors[f] = f"{label} must be a full link starting with https://"
        elif f == "event_format" and s not in FORMATS:
            errors[f] = f"{label} must be one of: {', '.join(FORMATS)}."
    start, end, cfp = (to_date(draft.get(k)) for k in DATE_FIELDS)
    if "event_start" in fields and "event_start" not in errors and start and start < today:
        errors["event_start"] = "Start date can't be in the past."
    if "event_end" in fields and "event_end" not in errors and start and end and end < start:
        errors["event_end"] = "End date must be on or after the start date."
    if "cfp_deadline" in fields and "cfp_deadline" not in errors and start and cfp and cfp > start:
        errors["cfp_deadline"] = "CFP deadline must be on or before the event start date."
    return errors


def dedupe_key(name, start, email) -> tuple:
    return (str(name or "").strip().lower(), str(to_date(start) or ""), str(email or "").strip().lower())


def read_upload(name: str, data) -> pd.DataFrame:
    if name.lower().endswith(".csv"):
        df = pd.read_csv(data, dtype=str)
    else:
        df = pd.read_excel(data, dtype=str)
    df = df.fillna("")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def validate_bulk(df: pd.DataFrame, today: date | None = None):
    """Return (valid_rows: list[dict], errors: DataFrame[row, column, problem], missing_columns)."""
    missing = sorted(REQUIRED - set(df.columns))
    if missing:
        return [], pd.DataFrame(columns=["row", "column", "problem"]), missing
    valid, problems = [], []
    for i, rec in enumerate(df.fillna("").to_dict(orient="records"), start=2):   # row 1 is the header
        draft = {k: str(rec.get(k, "") or "").strip() for k in FIELDS}
        errs = validate(draft, today=today)
        if errs:
            problems += [{"row": i, "column": k, "problem": v} for k, v in errs.items()]
        else:
            draft["_row"] = i
            valid.append(draft)
    return valid, pd.DataFrame(problems, columns=["row", "column", "problem"]), []
