"""Weekly recap: collect last week's activity from the Sheets tabs and render Slack + HTML drafts.

Pure functions; no Streamlit, no network. Personal data (emails, payment details) is never copied into a
recap; reimbursements contribute counts and totals only.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from utils.public_events import parse_date
from workflow.channels import slack_escape

MIN_RATINGS_FOR_HIGHLIGHT = 3

# Candidate header names per logical column (tabs created by hand don't share exact names), plus position fallback.
COLS = {
    "Events": {"submitted": (["submitted_at", "timestamp"], 1), "status": (["status"], 2),
               "name": (["event_name"], 8), "start": (["event_start", "event_date_start"], 10),
               "city": (["event_city"], 12), "country": (["event_country"], 13),
               "audience": (["expected_audience"], 15)},
    "Speaker_Requests": {"submitted": (["submitted_at"], 1), "status": (["status"], 2)},
    "Talk_Feedback": {"submitted": (["submitted_at"], 1), "speaker": (["speaker_name"], 2),
                      "event": (["event_name"], 3), "talk": (["talk_title"], 4),
                      "rating": (["rating_overall"], 6)},
    "Event_Headcount": {"submitted": (["saved_at", "timestamp", "submitted_at"], 0), "event": (["event_name", "event"], 2),
                        "city": (["city", "event_city"], 4), "reported": (["reported", "attendance_reported"], 9)},
    "Reimbursements": {"submitted": (["submitted_at", "timestamp"], 1), "total": (["total_usd", "total"], 8),
                       "status": (["status"], 16)},
}


def _col(df: pd.DataFrame, tab: str, key: str) -> pd.Series:
    names, pos = COLS[tab][key]
    for n in names:
        if n in df.columns:
            return df[n]
    if pos < len(df.columns):
        return df.iloc[:, pos]
    return pd.Series([""] * len(df), index=df.index)


def _when(value) -> date | None:
    s = str(value or "").strip()
    return parse_date(s[:10]) if s else None


def _num(value) -> float | None:
    """First number in a cell such as "$420.50 USD", "1,200", or "4"."""
    import re
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(m.group().replace(",", "")) if m else None


def week_bounds(today: date) -> tuple[date, date]:
    """Previous Monday..Sunday for a run on `today` (the recap runs Monday mornings)."""
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


@dataclass
class Summary:
    week_start: date
    week_end: date
    numbers: dict = field(default_factory=dict)
    top_talks: list = field(default_factory=list)       # [(talk, speaker, event, avg, n)]
    biggest_events: list = field(default_factory=list)  # [(event, city, attendance)]
    pending: dict = field(default_factory=dict)
    next_week: list = field(default_factory=list)       # [(start, name, city)]
    sources_missing: list = field(default_factory=list)
    workflow: dict = field(default_factory=dict)        # optional counts from the workflow store


def summarize(tabs: dict[str, pd.DataFrame | None], week_start: date, week_end: date,
              workflow_counts: dict | None = None) -> Summary:
    s = Summary(week_start, week_end, workflow=dict(workflow_counts or {}))
    in_week = lambda d: d is not None and week_start <= d <= week_end   # noqa: E731

    def tab(name):
        df = tabs.get(name)
        if df is None:
            s.sources_missing.append(name)
            return pd.DataFrame()
        return df

    ev = tab("Events")
    if not ev.empty:
        sub = _col(ev, "Events", "submitted").map(_when)
        status = _col(ev, "Events", "status").astype(str).str.strip()
        s.numbers["new_events"] = int(sub.map(in_week).sum())
        s.pending["events_awaiting_review"] = int((status == "Pending").sum())
        starts = _col(ev, "Events", "start").map(_when)
        nxt_lo, nxt_hi = week_end + timedelta(days=1), week_end + timedelta(days=7)
        approved = status == "Approved"
        s.numbers["approved_events_upcoming"] = int((approved & starts.map(lambda d: d is not None and d > week_end)).sum())
        rows = ev[approved & starts.map(lambda d: d is not None and nxt_lo <= d <= nxt_hi)]
        s.next_week = sorted((starts[i], str(_col(ev, "Events", "name")[i]), str(_col(ev, "Events", "city")[i]))
                             for i in rows.index)

    sr = tab("Speaker_Requests")
    if not sr.empty:
        s.numbers["speaker_requests"] = int(_col(sr, "Speaker_Requests", "submitted").map(_when).map(in_week).sum())

    fb = tab("Talk_Feedback")
    if not fb.empty:
        wk = fb[_col(fb, "Talk_Feedback", "submitted").map(_when).map(in_week)]
        ratings = _col(wk, "Talk_Feedback", "rating").map(_num)
        s.numbers["ratings"] = int(ratings.notna().sum())
        if ratings.notna().any():
            s.numbers["avg_rating"] = round(float(ratings.mean()), 2)
        g = pd.DataFrame({"talk": _col(wk, "Talk_Feedback", "talk").astype(str),
                          "speaker": _col(wk, "Talk_Feedback", "speaker").astype(str),
                          "event": _col(wk, "Talk_Feedback", "event").astype(str), "r": ratings}).dropna()
        if not g.empty:
            agg = g.groupby(["talk", "speaker", "event"])["r"].agg(["mean", "count"]).reset_index()
            agg = agg[agg["count"] >= MIN_RATINGS_FOR_HIGHLIGHT].sort_values(["mean", "count"], ascending=False)
            s.top_talks = [(r.talk, r.speaker, r.event, round(r["mean"], 2), int(r["count"]))
                           for _, r in agg.head(3).iterrows()]

    hc = tab("Event_Headcount")
    if not hc.empty:
        wk = hc[_col(hc, "Event_Headcount", "submitted").map(_when).map(in_week)]
        att = _col(wk, "Event_Headcount", "reported").map(_num)
        s.numbers["attendance"] = int(att.fillna(0).sum())
        rows = sorted(((str(_col(wk, "Event_Headcount", "event")[i]), str(_col(wk, "Event_Headcount", "city")[i]),
                        int(att[i])) for i in wk.index if att[i] is not None and att[i] == att[i]),
                      key=lambda r: -r[2])
        s.biggest_events = rows[:3]

    rb = tab("Reimbursements")
    if not rb.empty:
        status = _col(rb, "Reimbursements", "status").astype(str).str.strip().str.lower()
        open_ = rb[status.str.startswith("pending")]
        s.pending["reimbursements_open"] = int(len(open_))
        s.pending["reimbursements_open_usd"] = round(float(_col(open_, "Reimbursements", "total").map(_num).fillna(0).sum()), 2)
        s.numbers["reimbursements_submitted"] = int(_col(rb, "Reimbursements", "submitted").map(_when).map(in_week).sum())
    return s


LABELS = [("new_events", "New event requests"), ("speaker_requests", "Speaker requests"),
          ("ratings", "Talk ratings"), ("avg_rating", "Average rating"), ("attendance", "Attendance logged"),
          ("reimbursements_submitted", "Reimbursements submitted"),
          ("approved_events_upcoming", "Approved upcoming events")]


def _range(s: Summary) -> str:
    return f"{s.week_start:%b %d} – {s.week_end:%b %d, %Y}"


def to_slack(s: Summary, doc_url: str = "") -> str:
    """Slack mrkdwn. Every value that came from the sheet is passed through slack_escape."""
    e = slack_escape
    out = [f"*Community Voices weekly recap* · {_range(s)}"]
    nums = [f"• {label}: *{s.numbers[k]}*" for k, label in LABELS if k in s.numbers]
    out += ["", "*Headline numbers*"] + (nums or ["• No activity recorded"])
    if s.top_talks:
        out += ["", "*Top-rated talks*"] + [f"• {e(t)} — {e(sp)} at {e(ev)} ({avg}/5, {n} ratings)"
                                           for t, sp, ev, avg, n in s.top_talks]
    if s.biggest_events:
        out += ["", "*Biggest events*"] + [f"• {e(ev)}{' (' + e(c) + ')' if c else ''}: {n} attendees"
                                          for ev, c, n in s.biggest_events]
    pend = []
    if s.pending.get("events_awaiting_review"):
        pend.append(f"• {s.pending['events_awaiting_review']} event request(s) awaiting review")
    if s.pending.get("reimbursements_open"):
        pend.append(f"• {s.pending['reimbursements_open']} reimbursement(s) open "
                    f"(${s.pending['reimbursements_open_usd']:,.2f})")
    for k, v in s.workflow.items():
        pend.append(f"• {e(k)}: {v}")
    if pend:
        out += ["", "*Pending*"] + pend
    if s.next_week:
        out += ["", "*Coming up this week*"] + [f"• {d:%a %b %d} — {e(n)}{', ' + e(c) if c else ''}"
                                                   for d, n, c in s.next_week]
    if s.sources_missing:
        out += ["", f"_Couldn't read: {e(', '.join(s.sources_missing))}_"]
    if doc_url:
        out += ["", f"<{doc_url}|Full recap (Google Doc)>"]
    return "\n".join(out)


def to_html(s: Summary) -> str:
    """Static HTML for the Google Doc / email. All sheet values are html-escaped."""
    e = lambda x: html.escape(str(x))   # noqa: E731

    def ul(items):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else "<p>None this week.</p>"

    parts = [f"<h1>Community Voices weekly recap</h1><p>{e(_range(s))}</p>", "<h2>Headline numbers</h2>",
             ul([f"{e(label)}: <b>{e(s.numbers[k])}</b>" for k, label in LABELS if k in s.numbers]),
             "<h2>Top-rated talks</h2>",
             ul([f"{e(t)} — {e(sp)} at {e(ev)} ({e(avg)}/5, {e(n)} ratings)" for t, sp, ev, avg, n in s.top_talks]),
             "<h2>Biggest events</h2>",
             ul([f"{e(ev)}{' (' + e(c) + ')' if c else ''}: {e(n)} attendees" for ev, c, n in s.biggest_events]),
             "<h2>Pending</h2>",
             ul([f"{e(k.replace('_', ' '))}: {e(v)}" for k, v in {**s.pending, **s.workflow}.items()]),
             "<h2>Coming up this week</h2>",
             ul([f"{e(f'{d:%a %b %d}')} — {e(n)}{', ' + e(c) if c else ''}" for d, n, c in s.next_week])]
    if s.sources_missing:
        parts.append(f"<p><i>Couldn't read: {e(', '.join(s.sources_missing))}</i></p>")
    return "".join(parts)


def recap_id(s: Summary) -> str:
    return f"recap-{s.week_start.isoformat()}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
