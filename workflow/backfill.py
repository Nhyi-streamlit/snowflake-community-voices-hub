"""Backfill legacy Google Sheet events into the workflow store.

Creates one workflow event per legacy event row. Legacy emails (organizer, matched speaker)
become SUGGESTED members only: they grant no access and receive no notifications until an
administrator assigns that person. No program owner is set (decision: no default owner).
Idempotent: re-running skips events already backfilled.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from workflow.models import (
    CLOSED, EVENT_ACTIVE, PROPOSED, SPEAKER, SUGGESTED, VENDOR, AuditEvent, ChangeSet, Event, Member,
)
from workflow.service import EMAIL_RE, _h

STATUS_MAP = {"approved": EVENT_ACTIVE, "pending": PROPOSED, "rejected": CLOSED, "not a fit": CLOSED,
              "cancelled": CLOSED, "completed": CLOSED}


def _date(s) -> date | None:
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def plan(events_rows: list[dict], application_rows: list[dict], *, now: datetime, actor_subject: str):
    """Return (changesets, report). Pure: no I/O."""
    by_event: dict[str, list[str]] = {}
    for a in application_rows:
        eid, email = str(a.get("matched_event", "")).strip(), str(a.get("email", "")).strip().lower()
        if eid and EMAIL_RE.match(email):
            by_event.setdefault(eid, []).append(email)
    out, report = [], {"events": 0, "skipped_no_id": 0, "suggested_vendors": 0, "suggested_speakers": 0,
                       "unparsed_dates": 0}
    for r in events_rows:
        legacy = str(r.get("event_id", "")).strip()
        if not legacy or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", legacy):
            report["skipped_no_id"] += 1
            continue
        start = _date(r.get("event_start"))
        if r.get("event_start") and start is None:
            report["unparsed_dates"] += 1
        eid = "EV-" + _h("legacy", legacy)[:12].upper()
        event = Event(eid, str(r.get("event_name", "")).strip()[:500] or legacy,
                      STATUS_MAP.get(str(r.get("status", "")).strip().lower(), PROPOSED), start,
                      str(r.get("event_city", "")).strip()[:200], legacy, actor_subject, now)
        members = []
        org = str(r.get("organizer_email", "")).strip().lower()
        if EMAIL_RE.match(org):
            members.append(Member(_h("legacy-member", legacy, VENDOR, org)[:32], eid, VENDOR, org, SUGGESTED,
                                  display_name=str(r.get("organizer_name", "")).strip()[:300],
                                  created_by=actor_subject, created_at=now))
            report["suggested_vendors"] += 1
        for email in sorted(set(by_event.get(legacy, []))):
            members.append(Member(_h("legacy-member", legacy, SPEAKER, email)[:32], eid, SPEAKER, email, SUGGESTED,
                                  created_by=actor_subject, created_at=now))
            report["suggested_speakers"] += 1
        key = _h("backfill", legacy)
        audit = AuditEvent(_h("backfill-audit", legacy)[:32], key, eid, "BACKFILLED", actor_subject, "ADMIN", now,
                           to_status=event.status, note=f"legacy {legacy}; owner not set")
        out.append(ChangeSet(audit=[audit], events=[event], members=members))
        report["events"] += 1
    return out, report
