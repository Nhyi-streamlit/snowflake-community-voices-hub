"""Sheet-backed records for the ops automation (Recaps, Triage, Triage_Rules, Digest tabs).

The Google Sheet is the hand-off between the Mac cron jobs and the Community Cloud app.
Tests set OVERRIDE["sheets"] to a MemorySheets.
"""
from __future__ import annotations

import pandas as pd

HEADERS = {
    "Recaps": ["recap_id", "week_start", "week_end", "created_at", "status", "doc_url", "slack_text", "email_html",
               "approved_by", "approved_at", "sent_at", "send_result"],
    "Triage": ["event_id", "checked_at", "completeness", "duplicate_of", "conflicts", "fit_score", "fit_reasons",
               "ai_rationale", "decision_draft"],
    "Triage_Rules": ["key", "value"],
    "Digest": ["generated_at", "key", "value", "link"],
    "Content_Review": ["review_key", "item_id", "version", "checked_at", "ai_note"],
    "Conference_Approvals": ["key", "name", "email", "conference", "dates", "submitted_at", "status", "notified_at",
                             "decided_by", "decided_at", "navan_sent_at", "notes"],
    "Program_Feedback": ["feedback_id", "submitted_at", "name", "email", "community", "event", "topic", "rating",
                         "went_well", "improve", "follow_up_ok"],
}

DRAFT, APPROVED, SENT, DISCARDED = "Draft", "Approved", "Sent", "Discarded"

OVERRIDE: dict = {}


class GoogleSheets:
    """Thin adapter over utils.sheets (reads/writes the configured spreadsheet)."""

    def read(self, tab: str) -> pd.DataFrame:
        from utils.sheets import read_tab
        return read_tab(tab)

    def append(self, tab: str, row: list) -> bool:
        from utils.sheets import append_row
        return append_row(tab, row)

    def update(self, tab: str, sheet_row: int, row: list) -> bool:
        from utils.sheets import update_row
        return update_row(tab, sheet_row, row)

    def replace(self, tab: str, rows: list[list]) -> bool:
        from utils.sheets import replace_tab
        return replace_tab(tab, [HEADERS[tab]] + rows)


class MemorySheets:
    def __init__(self, tabs: dict[str, pd.DataFrame] | None = None):
        self.tabs = {k: v.copy() for k, v in (tabs or {}).items()}
        self.writes = []

    def read(self, tab):
        if tab not in self.tabs:
            return pd.DataFrame()
        return self.tabs[tab].copy()

    def append(self, tab, row):
        cols = HEADERS.get(tab) or list(self.tabs.get(tab, pd.DataFrame()).columns)
        df = self.tabs.get(tab, pd.DataFrame(columns=cols))
        if df.empty and not len(df.columns):
            df = pd.DataFrame(columns=cols)
        row = [str(x) for x in row] + [""] * (len(df.columns) - len(row))
        self.tabs[tab] = pd.concat([df, pd.DataFrame([row[:len(df.columns)]], columns=df.columns)], ignore_index=True)
        self.writes.append(("append", tab))
        return True

    def update(self, tab, sheet_row, row):
        df = self.tabs[tab]
        df.iloc[sheet_row - 2] = [str(x) for x in row] + [""] * (len(df.columns) - len(row))
        self.writes.append(("update", tab))
        return True

    def replace(self, tab, rows):
        self.tabs[tab] = pd.DataFrame([[str(x) for x in r] for r in rows], columns=HEADERS[tab])
        self.writes.append(("replace", tab))
        return True


def sheets():
    return OVERRIDE.get("sheets") or GoogleSheets()


def records(tab: str) -> list[dict]:
    """Rows as dicts, each with `_row` (1-based sheet row). Missing tab → []."""
    try:
        df = sheets().read(tab)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    out = []
    for i, r in enumerate(df.to_dict("records")):
        r = {k: ("" if v is None else str(v)) for k, v in r.items()}
        r["_row"] = i + 2
        out.append(r)
    return out


def upsert(tab: str, key: str, value: str, fields: dict) -> bool:
    """Insert or update the row whose `key` column equals `value`."""
    cols = HEADERS[tab]
    existing = next((r for r in records(tab) if r.get(key) == value), None)
    merged = {**(existing or {}), **fields, key: value}
    row = [merged.get(c, "") for c in cols]
    if existing:
        return sheets().update(tab, existing["_row"], row)
    return sheets().append(tab, row)


def rules() -> dict[str, str]:
    return {r["key"]: r["value"] for r in records("Triage_Rules") if r.get("key")}
