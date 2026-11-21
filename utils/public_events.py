"""Approved, upcoming public events from the Sheets Events tab (only non-personal columns)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

PUBLIC_COLS = ["event_id", "event_name", "event_city", "event_country", "event_start", "event_end", "event_format",
               "event_website", "community_alignment", "event_description", "opportunity_type", "slot_status",
               "cfp_deadline"]
SPEAKER_SLOT, CFP = "Speaker slot", "CFP invitation"
OPEN, PENDING_REVIEW, FILLED, CANCELED = "Open", "Pending review", "Filled", "Canceled"
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


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
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
    raw = raw.fillna("")                    # short sheet rows leave trailing cells as NaN
    df = raw.loc[raw["status"].astype(str).str.strip().eq("Approved"),
                 [c for c in PUBLIC_COLS if c in raw]].copy()
    df["start"] = df["event_start"].map(parse_date) if "event_start" in df else None
    today = today or datetime.now(timezone.utc).date()
    df = df[df["start"].map(lambda d: d is not None and d >= today)].sort_values("start")
    return df.head(limit) if limit else df


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].astype(str).str.strip() if name in df else pd.Series("", index=df.index)


def speaker_slots(today: date | None = None, statuses=(OPEN, PENDING_REVIEW)) -> pd.DataFrame | None:
    """Upcoming partner speaker slots in the given slot_status values (default: still claimable or awaiting review)."""
    df = upcoming(today=today)
    if df is None or df.empty:
        return df
    return df[_col(df, "opportunity_type").eq(SPEAKER_SLOT) & _col(df, "slot_status").isin(statuses)]


def cfp_invitations(today: date | None = None) -> pd.DataFrame | None:
    """Upcoming CFP invitations whose deadline hasn't passed. Untyped rows count as CFP invitations;
    a blank or non-date deadline (e.g. "Rolling") stays listed."""
    df = upcoming(today=today)
    if df is None or df.empty:
        return df
    today = today or datetime.now(timezone.utc).date()
    df = df[~_col(df, "opportunity_type").eq(SPEAKER_SLOT)]
    deadline = _col(df, "cfp_deadline").map(parse_date)
    return df[deadline.map(lambda d: d is None or d >= today)]
