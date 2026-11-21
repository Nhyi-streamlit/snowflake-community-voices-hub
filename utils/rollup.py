"""Keep the program sheet's Speaker-Events current (run hourly by scripts/program_rollup.py).

- New Talk_Feedback ratings (hub) are copied to the program sheet's Talk Feedback tab, which feeds the
  Survey Responses / Avg Rating / % New formulas on Speaker-Events. No respondent names or emails are copied.
- Event_Headcount (hub) fills Attended; Partner Metrics (program) fills Registered and Attended.
- Speaker updates that didn't reach Speaker-Events are retried.
Only blank cells are filled; nothing a person typed is overwritten. Anything that can't be matched to exactly one
Speaker-Events row goes to the hub's Needs_Review tab instead of being guessed.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from utils import activity as act
from utils import ops_store as ops
from utils import slots as sl
from utils.public_events import parse_date

FEEDBACK_COLS = 13              # program Talk Feedback = the first 13 hub columns (no respondent contact details)
NEAR = timedelta(days=3)


def _d(v):
    s = str(v or "").strip()
    return parse_date(s[:10]) if s else None


def _blank(v) -> bool:
    return str(v if v is not None else "").strip() in ("", "nan")


def _num(v):
    from utils.recap import _num as n
    return n(v)


def _candidates(se: pd.DataFrame, when, *, speaker_id: str = "", city: str = "", event: str = ""):
    """Speaker-Events rows within 3 days of `when`, narrowed by speaker, then by city / event name."""
    if when is None or se.empty:
        return se.iloc[0:0]
    dates = se["Date"].map(_d) if "Date" in se else pd.Series([None] * len(se), index=se.index)
    rows = se[dates.map(lambda d: d is not None and abs(d - when) <= NEAR)]
    rows = rows[rows.get("Stage", pd.Series("", index=rows.index)).astype(str) != "Canceled"]
    if speaker_id:
        rows = rows[rows["Speaker ID"].astype(str) == speaker_id]
    if len(rows) > 1 and city and "City" in rows:
        by_city = rows[rows["City"].astype(str).map(act._norm) == act._norm(city)]
        rows = by_city if len(by_city) else rows
    if len(rows) > 1 and event and "Event" in rows:
        by_ev = rows[rows["Event"].astype(str).map(act._norm) == act._norm(event)]
        rows = by_ev if len(by_ev) else rows
    return rows


def _fill(p, se, idx, column: str, value, note: list) -> None:
    if value is None or column not in se.columns or not _blank(se.at[idx, column]):
        return
    p.set("Speaker-Events", int(idx) + 2, column, str(int(value)) if float(value).is_integer() else str(value))
    se.at[idx, column] = str(value)
    note.append(f"{se.at[idx, 'SE ID']}.{column}")


def run(hub_read=None) -> dict:
    """Returns {"feedback_copied": n, "filled": [...], "flagged": n, "retried": n}."""
    hub_read = hub_read or (lambda tab: ops.sheets().read(tab))
    p = sl._program()
    out = {"feedback_copied": 0, "filled": [], "flagged": 0, "retried": 0}

    # 1. Talk feedback → program Talk Feedback (dedupe on submission id)
    try:
        hub_fb = hub_read("Talk_Feedback")
        prog_fb = p.read("Talk Feedback")
        have = set(prog_fb.iloc[:, 0].astype(str)) if not prog_fb.empty else set()
        for _, r in hub_fb.iterrows():
            sid = str(r.iloc[0])
            if sid and sid not in have:
                p.append("Talk Feedback", [("" if pd.isna(v) else str(v)) for v in list(r.values)[:FEEDBACK_COLS]])
                have.add(sid)
                out["feedback_copied"] += 1
    except Exception:
        pass

    se = p.read("Speaker-Events")
    spk = p.read("Speakers")
    by_email = {str(e).strip().lower(): str(i) for e, i in zip(spk.get("Email", []), spk.get("Speaker ID", []))}

    # 2. Headcount → Attended
    try:
        hc = hub_read("Event_Headcount")
    except Exception:
        hc = pd.DataFrame()
    for _, r in hc.iterrows():
        email = str(r.get("Speaker_Email", "")).strip().lower()
        ref = f"{email}|{r.get('Event_Name', '')}|{r.get('Event_Date', '')}"
        rows = _candidates(se, _d(r.get("Event_Date")), speaker_id=by_email.get(email, "_none_"),
                           city=str(r.get("City", "")), event=str(r.get("Event_Name", "")))
        if len(rows) != 1:
            act.flag("Event_Headcount", ref, f"{r.get('Event_Name', '')} · {r.get('Event_Date', '')} · {email}",
                     "No matching Speaker-Events row" if rows.empty else f"{len(rows)} possible Speaker-Events rows")
            out["flagged"] += 1
            continue
        _fill(p, se, rows.index[0], "Attended", _num(r.get("Reported_Attendance")), out["filled"])

    # 3. Partner Metrics → Registered / Attended
    try:
        pm = p.read("Partner Metrics")
    except Exception:
        pm = pd.DataFrame()
    for _, r in pm.iterrows():
        ref = str(r.get("Submission ID", "")) or f"{r.get('Event Name', '')}|{r.get('Event Date', '')}"
        speaker = str(r.get("Speaker Name", "")).strip()
        rows = _candidates(se, _d(r.get("Event Date")), city=str(r.get("City", "")), event=str(r.get("Event Name", "")))
        if speaker and len(rows) > 1 and "Speaker" in rows:
            named = rows[rows["Speaker"].astype(str).map(act._norm) == act._norm(speaker)]
            rows = named if len(named) else rows
        if len(rows) != 1:
            act.flag("Partner Metrics", ref, f"{r.get('Partner', '')} · {r.get('Event Name', '')} · {r.get('Event Date', '')}",
                     "No matching Speaker-Events row" if rows.empty else f"{len(rows)} possible Speaker-Events rows")
            out["flagged"] += 1
            continue
        _fill(p, se, rows.index[0], "Registered", _num(r.get("Registered / RSVPs")), out["filled"])
        _fill(p, se, rows.index[0], "Attended", _num(r.get("Total Attendees")), out["filled"])

    # 4. Speaker updates that didn't sync
    for u in act.updates():
        confirmed = u.get("kind") == act.SPEAKING or (u.get("status") == act.ACCEPTED and u.get("event_date"))
        if confirmed and not u.get("se_id"):
            act.sync_talk(u)
            out["retried"] += 1
    return out
