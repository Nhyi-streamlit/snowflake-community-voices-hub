"""Event request triage: completeness, duplicates, date conflicts, editable fit score, urgency.

Pure functions over Events + Speaker_Requests rows (dicts of strings) and a rules dict
(the Triage_Rules tab). No network, no Streamlit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from utils import vendor_validation as vv

DEFAULT_RULES = {
    "min_audience": "50",
    "regions": "",                 # comma-separated countries/cities that score a bonus; empty = any
    "topics": "ai, apps, streamlit, data engineering, iceberg, cortex, snowpark, analytics",
    "blocked_dates": "",           # comma-separated YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD
    "conflict_window_days": "2",
    "auto_approve_score": "75",    # pre-select Approve at or above
    "auto_decline_score": "30",    # pre-select Not a fit at or below
}
RULE_HELP = {
    "min_audience": "Events below this expected audience lose points.",
    "regions": "Priority countries or cities, comma-separated. Leave empty to treat all equally.",
    "topics": "Topic keywords that match our speakers, comma-separated.",
    "blocked_dates": "Dates we can't support, e.g. 2026-11-24..2026-11-28, 2026-12-25",
    "conflict_window_days": "Approved events in the same city within this many days count as a conflict.",
    "auto_approve_score": "Pre-select Approve at or above this score.",
    "auto_decline_score": "Pre-select Not a fit at or below this score.",
}
REQUIRED_SHEET = ["organizer_name", "organizer_email", "event_name", "event_start", "event_city",
                  "event_country", "event_format"]


def merged_rules(user: dict | None) -> dict:
    return {**DEFAULT_RULES, **{k: v for k, v in (user or {}).items() if k in DEFAULT_RULES and str(v).strip()}}


def _int(v, default=0):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except ValueError:
        return default


def _csv(v) -> list[str]:
    return [x.strip().lower() for x in str(v or "").split(",") if x.strip()]


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _blocked(rules) -> list[tuple[date, date]]:
    out = []
    for part in _csv(rules["blocked_dates"]):
        a, _, b = part.partition("..")
        da, db = vv.to_date(a), vv.to_date(b) if b else None
        if da:
            out.append((da, db or da))
    return out


@dataclass
class Triage:
    event_id: str
    name: str
    status: str
    start: date | None
    cfp_deadline: date | None
    missing: list = field(default_factory=list)
    duplicate_of: str = ""
    conflicts: list = field(default_factory=list)
    score: int = 0
    reasons: list = field(default_factory=list)
    urgency: date | None = None
    suggestion: str = ""          # Approve / Waitlist / Not a fit / "" (needs a look)
    row: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.missing


def triage(events: list[dict], requests: list[dict], rules: dict | None = None,
           today: date | None = None) -> list[Triage]:
    """Triage every Pending event. Returns them sorted by urgency (soonest event/CFP first)."""
    r = merged_rules(rules)
    today = today or date.today()
    req_by_event = {}
    for q in requests:
        req_by_event.setdefault(q.get("event_id", ""), q)
    approved = [e for e in events if str(e.get("status", "")).strip() == "Approved"]
    seen = {}
    for e in events:                                   # first submission wins for duplicate detection
        key = (_norm(e.get("event_name")), str(vv.to_date(e.get("event_start")) or ""), _norm(e.get("event_city")))
        seen.setdefault(key, e.get("event_id", ""))
    window = timedelta(days=_int(r["conflict_window_days"], 2))
    blocked = _blocked(r)
    topics, regions = _csv(r["topics"]), _csv(r["regions"])
    min_aud = _int(r["min_audience"], 50)

    out = []
    for e in events:
        if str(e.get("status", "")).strip() != "Pending":
            continue
        q = req_by_event.get(e.get("event_id", ""), {})
        start = vv.to_date(e.get("event_start"))
        cfp = vv.to_date(q.get("cfp_deadline"))
        t = Triage(e.get("event_id", ""), e.get("event_name", ""), "Pending", start, cfp, row={**e, **{
            "speaker_topic": q.get("speaker_topic", ""), "cfp_link": q.get("cfp_link", "")}})
        t.missing = [f for f in REQUIRED_SHEET if not str(e.get(f, "")).strip()]
        if not str(q.get("speaker_topic", "")).strip():
            t.missing.append("speaker_topic")
        key = (_norm(e.get("event_name")), str(start or ""), _norm(e.get("event_city")))
        if seen.get(key) and seen[key] != t.event_id:
            t.duplicate_of = seen[key]
        if start:
            for a in approved:
                ad = vv.to_date(a.get("event_start"))
                if ad and abs(ad - start) <= window and _norm(a.get("event_city")) == _norm(e.get("event_city")):
                    t.conflicts.append(f"Overlaps approved {a.get('event_name', '')} ({ad:%b %d})")
            for lo, hi in blocked:
                if lo <= start <= hi:
                    t.conflicts.append(f"Falls on blocked dates {lo:%b %d}–{hi:%b %d}")

        score, why = 50, t.reasons
        aud = _int(e.get("expected_audience"), -1)
        if aud < 0:
            score -= 5; why.append("−5 expected audience not given")
        elif aud >= min_aud * 4:
            score += 20; why.append(f"+20 large audience ({aud})")
        elif aud >= min_aud:
            score += 10; why.append(f"+10 audience {aud} ≥ {min_aud}")
        else:
            score -= 20; why.append(f"−20 audience {aud} < {min_aud}")
        text = _norm(" ".join([e.get("event_name", ""), e.get("event_description", ""), q.get("speaker_topic", ""),
                               q.get("topic_tags", "")]))
        hits = [tp for tp in topics if _norm(tp) and _norm(tp) in text]
        if hits:
            score += min(20, 10 * len(hits)); why.append(f"+{min(20, 10 * len(hits))} topics: {', '.join(hits[:3])}")
        else:
            score -= 10; why.append("−10 no matching topics")
        place = _norm(f"{e.get('event_city', '')} {e.get('event_country', '')}")
        if regions:
            if any(_norm(rg) in place for rg in regions):
                score += 10; why.append("+10 priority region")
        if start is None:
            score -= 10; why.append("−10 no valid start date")
        elif start < today:
            score -= 40; why.append("−40 event date has passed")
        elif start - today < timedelta(days=14):
            score -= 10; why.append("−10 less than 2 weeks away")
        if t.missing:
            score -= 5 * len(t.missing); why.append(f"−{5 * len(t.missing)} missing {', '.join(t.missing)}")
        if t.duplicate_of:
            score -= 30; why.append(f"−30 duplicate of {t.duplicate_of}")
        if t.conflicts:
            score -= 15; why.append("−15 date conflict")
        t.score = max(0, min(100, score))

        dates = [d for d in (start, cfp) if d]
        t.urgency = min(dates) if dates else None
        if t.duplicate_of or (start and start < today):
            t.suggestion = "Not a fit"
        elif t.score >= _int(r["auto_approve_score"], 75) and t.complete and not t.conflicts:
            t.suggestion = "Approve"
        elif t.score <= _int(r["auto_decline_score"], 30):
            t.suggestion = "Not a fit"
        elif t.conflicts or not t.complete:
            t.suggestion = ""
        else:
            t.suggestion = "Waitlist"
        out.append(t)
    return sorted(out, key=lambda t: (t.urgency is None, t.urgency or date.max, -t.score))


# ── Vendor decision emails (drafts only; Aba edits and sends) ─────────────────────────────────

TEMPLATES = {
    "Approve": ("Your event is approved: {event}",
                "Hi {name},\n\nGreat news: {event} is approved for the Snowflake Community Voices program. "
                "We're now matching a community speaker for your topic and will be in touch with details.\n\n"
                "You can follow along under My events in the Vendor Portal (reference {ref}).\n\n"
                "Thanks,\nAba Micah\nCommunity Voices, Snowflake"),
    "Waitlist": ("Update on {event}",
                 "Hi {name},\n\nThanks for registering {event}. We've added it to our waitlist while we confirm "
                 "speaker availability for those dates, and we'll update you as soon as we can.\n\n"
                 "Reference: {ref}\n\nThanks,\nAba Micah\nCommunity Voices, Snowflake"),
    "Not a fit": ("Update on {event}",
                  "Hi {name},\n\nThank you for thinking of Snowflake Community Voices for {event}. After review, "
                  "we're not able to support this one, but we'd love to hear about future events.\n\n"
                  "Reference: {ref}\n\nThanks,\nAba Micah\nCommunity Voices, Snowflake"),
}


def draft_email(t: Triage, decision: str) -> tuple[str, str]:
    subj, body = TEMPLATES[decision]
    first = (str(t.row.get("organizer_name", "")).split() or ["there"])[0]
    vals = {"name": first, "event": t.name or "your event", "ref": t.event_id}
    return subj.format(**vals), body.format(**vals)


def ai_prompt(t: Triage) -> str:
    """Only non-personal event fields go to the model."""
    e = t.row
    return ("You review events for a developer community speaker program (Snowflake Community Voices). "
            "In ONE sentence under 30 words, say whether this event is a good fit for a community speaker and why. "
            "Do not invent facts.\n"
            f"Event: {e.get('event_name', '')}\nFormat: {e.get('event_format', '')}\n"
            f"Location: {e.get('event_city', '')}, {e.get('event_country', '')}\n"
            f"Expected audience: {e.get('expected_audience', '')}\n"
            f"Description: {str(e.get('event_description', ''))[:800]}\n"
            f"Requested topic: {str(e.get('speaker_topic', ''))[:400]}")
