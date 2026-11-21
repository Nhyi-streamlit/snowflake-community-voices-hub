"""Weekly recap: where Community Voices speakers spoke last week, and what's next. Renders Slack + HTML drafts.

Pure functions; no Streamlit, no network. No financials (no reimbursements or budget) and no personal contact
details: names, events, cities and counts only. Iceberg / Polaris open-source events are left out (separate program).

Sources (each number comes from one of these tabs):
  Speaker-Events (program sheet)  talks: Stage, Date, Attended, Survey Responses, Avg Rating
  Slot_Claims (hub)               slot claims and accept / decline decisions
  Speaker_Updates (hub)           talks and CFPs speakers report themselves
  Events (hub)                    vendor-submitted events and open speaker slots
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from utils.public_events import SPEAKER_SLOT, OPEN, parse_date
from workflow.channels import slack_escape

CONFIRM = "[confirm]"
GAP_LOOKBACK = timedelta(days=28)            # past talks still not marked Delivered, within the last 4 weeks
OSS = re.compile(r"iceberg|polaris", re.I)   # open-source program, reported separately


def _when(value) -> date | None:
    s = str(value or "").strip()
    return parse_date(s[:10]) if s else None


def _num(value) -> float | None:
    """First number in a cell such as "1,200", "4.93" or "26 people"."""
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(m.group().replace(",", "")) if m else None


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _fmt(n: float | None) -> str:
    return CONFIRM if n is None else (str(int(n)) if float(n).is_integer() else f"{n:.2f}".rstrip("0").rstrip("."))


def week_bounds(today: date) -> tuple[date, date]:
    """Previous Monday..Sunday for a run on `today` (the recap runs Monday mornings)."""
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


@dataclass
class Talk:
    speaker: str
    event: str
    city: str
    when: date
    attendance: str = ""      # number or [confirm]
    rating: str = ""          # "4.9/5 (14)" or ""
    stage: str = ""


@dataclass
class Summary:
    week_start: date
    week_end: date
    delivered: list = field(default_factory=list)     # [Talk]
    coming_up: list = field(default_factory=list)     # [Talk], next 2 weeks
    new: dict = field(default_factory=dict)           # section → [str]
    open_slots: list = field(default_factory=list)    # [(date, event, city)]
    pending_slots: int = 0
    gaps: list = field(default_factory=list)          # [str]
    sources_missing: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {"delivered": len(self.delivered), "coming_up": len(self.coming_up),
                **{k: len(v) for k, v in self.new.items()}, "open_slots": len(self.open_slots), "gaps": len(self.gaps)}


NEW_LABELS = [("talks_reported", "Talks speakers added"), ("slot_claims", "Slot claims"),
              ("slots_accepted", "Slots accepted"), ("slots_declined", "Slots declined"),
              ("cfps_submitted", "CFPs submitted"), ("cfps_accepted", "CFPs accepted"),
              ("vendor_events", "New events submitted")]


def _rows(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{k: _s(v) for k, v in r.items()} for r in df.to_dict("records")]


def summarize(tabs: dict[str, pd.DataFrame | None], week_start: date, week_end: date,
              workflow_counts: dict | None = None) -> Summary:
    """workflow_counts is accepted for callers of the old signature and not shown (approvals live in Workflow admin)."""
    s = Summary(week_start, week_end)
    in_week = lambda d: d is not None and week_start <= d <= week_end   # noqa: E731

    def tab(name):
        df = tabs.get(name)
        if df is None:
            s.sources_missing.append(name)
        return _rows(df)

    # Talks (program sheet master)
    for r in tab("Speaker-Events"):
        d, stage, event = _when(r.get("Date")), r.get("Stage", ""), r.get("Event", "")
        if d is None or stage in ("Canceled", "Declined") or OSS.search(event):
            continue
        n_fb = _num(r.get("Survey Responses"))
        t = Talk(r.get("Speaker", "") or CONFIRM, event or CONFIRM, r.get("City", ""), d, stage=stage,
                 attendance=_fmt(_num(r.get("Attended"))),
                 rating=f"{_fmt(_num(r.get('Avg Rating (1-5)')))}/5 ({int(n_fb)})" if n_fb else "")
        if in_week(d) and stage == "Delivered":
            s.delivered.append(t)
            if t.attendance == CONFIRM:
                s.gaps.append(f"Attendance missing: {t.speaker} · {t.event} ({d:%b %d})")
        elif week_end < d <= week_end + timedelta(days=14) and stage in ("Confirmed", "Delivered"):
            s.coming_up.append(t)
        elif week_end - GAP_LOOKBACK <= d <= week_end and stage != "Delivered":
            s.gaps.append(f"Not marked delivered: {t.speaker} · {t.event} ({d:%b %d}, Stage: {stage or 'blank'})")
    s.delivered.sort(key=lambda t: (t.when, t.event))
    s.coming_up.sort(key=lambda t: (t.when, t.event))

    new = {k: [] for k, _ in NEW_LABELS}
    for r in tab("Slot_Claims"):
        if OSS.search(r.get("event_name", "")):
            continue
        what = f"{r.get('name', '')} · {r.get('event_name', '')}"
        if in_week(_when(r.get("submitted_at"))):
            new["slot_claims"].append(what)
        if in_week(_when(r.get("decided_at"))) and r.get("status") in ("accepted", "declined"):
            new[f"slots_{r['status']}"].append(what)

    for r in tab("Speaker_Updates"):
        if OSS.search(r.get("event_name", "")):
            continue
        what = f"{r.get('name', '') or CONFIRM} · {r.get('event_name', '')}"
        if r.get("kind") == "speaking" and in_week(_when(r.get("submitted_at"))):
            new["talks_reported"].append(what)
        if r.get("kind") == "cfp" and in_week(_when(r.get("submitted_at"))):
            new["cfps_submitted"].append(what)
        if r.get("kind") == "cfp" and r.get("status") == "Accepted" and in_week(_when(r.get("decided_at"))):
            new["cfps_accepted"].append(what)

    for r in tab("Events"):
        name, city = r.get("event_name", ""), r.get("event_city", "")
        if OSS.search(name):
            continue
        start = _when(r.get("event_start"))
        if r.get("opportunity_type") == SPEAKER_SLOT:
            if start and start > week_end and r.get("slot_status") == OPEN:
                s.open_slots.append((start, name, city))
            elif start and start > week_end and r.get("slot_status") == "Pending review":
                s.pending_slots += 1
        elif in_week(_when(r.get("submitted_at"))):
            new["vendor_events"].append(f"{name}{' · ' + city if city else ''}")
    s.open_slots.sort()
    s.new = new
    return s


def _range(s: Summary) -> str:
    return f"{s.week_start:%b %d} – {s.week_end:%b %d, %Y}"


def _talk_line(t: Talk, e, delivered: bool) -> str:
    where = f" · {e(t.city)}" if t.city else ""
    if not delivered:
        return f"{t.when:%a %b %d} · {e(t.speaker)} · {e(t.event)}{where}"
    rating = f" · {e(t.rating)}" if t.rating else ""
    return f"{e(t.speaker)} · {e(t.event)}{where} · {e(t.attendance)} attended{rating}"


def to_slack(s: Summary, doc_url: str = "") -> str:
    """Slack mrkdwn draft. Every value from a sheet goes through slack_escape."""
    e = slack_escape
    out = [f"Hi <!here>! Sharing this week's Community Voices recap ({_range(s)}).", ""]
    out += ["*Talks delivered*"] + ([f"• {_talk_line(t, e, True)}" for t in s.delivered] or ["• None marked delivered this week"])
    if s.coming_up:
        out += ["", "*Coming up (next 2 weeks)*"] + [f"• {_talk_line(t, e, False)}" for t in s.coming_up]
    new = [f"• {label}: *{len(s.new[k])}*" for k, label in NEW_LABELS if s.new.get(k)]
    if new:
        out += ["", "*New this week*"] + new
    if s.open_slots:
        out += ["", "*Open speaker slots*"] + [f"• {d:%b %d} · {e(n)}{' · ' + e(c) if c else ''}"
                                                for d, n, c in s.open_slots]
    if s.gaps:
        out += ["", f"*To confirm* ({len(s.gaps)})"] + [f"• {e(g)}" for g in s.gaps[:8]]
        if len(s.gaps) > 8:
            out.append(f"• …and {len(s.gaps) - 8} more in the doc")
    if s.sources_missing:
        out += ["", f"_Couldn't read: {e(', '.join(s.sources_missing))}_"]
    if doc_url:
        out += ["", f"<{doc_url}|Full recap (Google Doc)>"]
    out += ["", "Thank you to all our speakers!"]
    return "\n".join(out)


def to_html(s: Summary) -> str:
    """Static HTML for the Google Doc. All sheet values are html-escaped."""
    e = lambda x: html.escape(str(x))   # noqa: E731

    def ul(items, empty="None this week."):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else f"<p>{empty}</p>"

    parts = [f"<h1>Community Voices weekly recap</h1><p>{e(_range(s))}</p>",
             "<h2>1. Talks delivered</h2>",
             ul([e(_talk_line(t, str, True)) for t in s.delivered], "None marked delivered this week."),
             "<h2>2. Coming up (next 2 weeks)</h2>", ul([e(_talk_line(t, str, False)) for t in s.coming_up]),
             "<h2>3. New this week</h2>"]
    for k, label in NEW_LABELS:
        items = s.new.get(k, [])
        parts.append(f"<p><b>{e(label)}: {len(items)}</b></p>" + (ul([e(i) for i in items]) if items else ""))
    parts += ["<h2>4. Open speaker slots</h2>",
              ul([e(f"{d:%b %d} · {n}{' · ' + c if c else ''}") for d, n, c in s.open_slots], "No open slots.")]
    if s.pending_slots:
        parts.append(f"<p>{s.pending_slots} more slot(s) have a claim pending review.</p>")
    parts += ["<h2>5. Gaps to chase</h2>", ul([e(g) for g in s.gaps], "Nothing to confirm.")]
    parts.append("<p><i>Sources: Speaker-Events (program sheet), Slot_Claims, Speaker_Updates, Events. "
                 f"{CONFIRM} = not recorded yet. Iceberg / Polaris open-source events are reported separately.</i></p>")
    if s.sources_missing:
        parts.append(f"<p><i>Couldn't read: {e(', '.join(s.sources_missing))}</i></p>")
    return "".join(parts)


def recap_id(s: Summary) -> str:
    return f"recap-{s.week_start.isoformat()}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
