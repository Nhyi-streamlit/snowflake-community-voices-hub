"""Approved, upcoming public events from the Sheets Events tab (only non-personal columns)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

PUBLIC_COLS = ["event_name", "event_city", "event_country", "event_start", "event_end", "event_format"]
_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y")

# Tests set OVERRIDE["events"] to a DataFrame shaped like the Events tab.
OVERRIDE: dict = {}


def parse_date(value) -> date | None:
    s = str(value or "").strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


@st.cache_data(ttl=600, max_entries=4, show_spinner=False)
def _approved_from_sheet() -> pd.DataFrame:
    from utils.sheets import read_tab
    return read_tab("Events")


def upcoming(limit: int | None = None, today: date | None = None) -> pd.DataFrame | None:
    """Approved events starting today or later, soonest first. None if the sheet can't be read."""
    try:
        raw = OVERRIDE["events"] if "events" in OVERRIDE else _approved_from_sheet()
    except Exception:
        return None
    if raw is None or raw.empty or "status" not in raw:
        return pd.DataFrame(columns=PUBLIC_COLS + ["start"])
    df = raw.loc[raw["status"].astype(str).str.strip().eq("Approved"),
                 [c for c in PUBLIC_COLS if c in raw]].copy()
    df["start"] = df["event_start"].map(parse_date) if "event_start" in df else None
    today = today or datetime.now(timezone.utc).date()
    df = df[df["start"].map(lambda d: d is not None and d >= today)].sort_values("start")
    return df.head(limit) if limit else df
