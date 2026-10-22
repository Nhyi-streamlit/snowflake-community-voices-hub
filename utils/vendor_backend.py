"""Vendor submissions backend: routes through the workflow service when it is configured,
otherwise falls back to the Google Sheets Events / Speaker_Requests tabs.

Every write re-checks ownership against the verified identity; the UI is never trusted.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils import vendor_validation as vv
from workflow import runtime
from workflow.models import ACTIVE, INVITED, PROPOSED, SPEAKER, InvalidAction, NotAuthorized

log = logging.getLogger("cv.vendor")

WORKFLOW, SHEETS = "workflow", "sheets"
RETRY_MSG = ("We couldn't save that right now. Your answers are still here — please try again in a "
             "minute, or email aba.micah@snowflake.com if it keeps happening.")
LOAD_MSG = "We couldn't load your events right now. Please refresh in a minute."

EVENT_COLS = ["event_id", "submitted_at", "status", "organizer_name", "organizer_email", "organizer_org",
              "organizer_role", "org_website", "event_name", "event_website", "event_start", "event_end",
              "event_city", "event_country", "event_format", "expected_audience", "community_alignment",
              "event_description", "how_heard", "additional_notes", "admin_notes"]
REQUEST_COLS = ["request_id", "submitted_at", "status", "event_id", "event_name", "speaker_topic",
                "topic_tags", "session_format", "audience_level", "cfp_link", "cfp_deadline",
                "matched_speaker", "admin_notes"]
WORKFLOW_STATUS = {PROPOSED: "Pending", "ACTIVE": "Approved", "CLOSED": "Closed"}

# Tests replace this with an in-memory object exposing read_tab / append_row / update_row.
SHEETS_OVERRIDE: dict = {}


@dataclass
class Outcome:
    ok: bool
    ref: str = ""
    message: str = ""
    duplicate: bool = False


@dataclass
class VendorEvent:
    ref: str
    status: str
    details: dict
    matched_speakers: list = field(default_factory=list)
    admin_notes: str = ""

    @property
    def editable(self) -> bool:
        return self.status == "Pending"


def _sheets():
    if "api" in SHEETS_OVERRIDE:
        return SHEETS_OVERRIDE["api"]
    from utils import sheets
    return sheets


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mode() -> str:
    try:
        return WORKFLOW if runtime.get_service() is not None else SHEETS
    except Exception:
        log.exception("workflow service unavailable; using sheets")
        return SHEETS


def _clean(draft: dict) -> dict:
    return {k: str(draft.get(k) or "").strip() for k in vv.FIELDS}


# ── sheets helpers ────────────────────────────────────────────────────────────

def _event_row(ref, now, status, email, d, admin_notes=""):
    vals = {**d, "event_id": ref, "submitted_at": now, "status": status, "organizer_email": email,
            "admin_notes": admin_notes}
    return [vals.get(c, "") for c in EVENT_COLS]


def _request_row(rid, now, status, ref, d, matched="", admin_notes=""):
    vals = {**d, "request_id": rid, "submitted_at": now, "status": status, "event_id": ref,
            "matched_speaker": matched, "admin_notes": admin_notes}
    return [vals.get(c, "") for c in REQUEST_COLS]


def _read(tab):
    df = _sheets().read_tab(tab)
    return df.fillna("") if df is not None else df


def _mine_sheets(email):
    ev = _read("Events")
    if ev is None or ev.empty or "organizer_email" not in ev.columns:
        return ev, None, []
    rq = _read("Speaker_Requests")
    mask = ev["organizer_email"].astype(str).str.strip().str.lower() == email
    return ev, rq, list(ev.index[mask])


def _request_for(rq, ref):
    if rq is None or rq.empty or "event_id" not in rq.columns:
        return None, None
    hits = rq.index[rq["event_id"].astype(str) == ref]
    return (hits[0], rq.loc[hits[0]].to_dict()) if len(hits) else (None, None)


# ── public API ────────────────────────────────────────────────────────────────

def list_my_events(actor) -> list[VendorEvent]:
    """Events submitted by this verified vendor only. Raises RuntimeError(LOAD_MSG) on backend errors."""
    try:
        if mode() == WORKFLOW:
            return _list_workflow(actor)
        return _list_sheets(actor.email)
    except (NotAuthorized, InvalidAction):
        return []
    except Exception:
        log.exception("listing vendor events failed")
        raise RuntimeError(LOAD_MSG)


def _list_sheets(email):
    ev, rq, idx = _mine_sheets(email)
    out = []
    for i in idx:
        row = ev.loc[i].to_dict()
        _, req = _request_for(rq, row.get("event_id", ""))
        req = req or {}
        details = {k: str(row.get(k, req.get(k, "")) or "") for k in vv.FIELDS}
        for k in ("speaker_topic", "cfp_link", "cfp_deadline"):
            details[k] = str(req.get(k, "") or "")
        matched = [m.strip() for m in str(req.get("matched_speaker", "")).split(",") if m.strip()]
        notes = " ".join(n for n in (str(row.get("admin_notes", "")).strip(),
                                     str(req.get("admin_notes", "")).strip()) if n)
        out.append(VendorEvent(str(row.get("event_id", "")), str(row.get("status", "") or "Pending"),
                               details, matched, notes))
    return out


def _details_item(view):
    return next((i for i in view.items if i.item_type == "event_details"), None)


def _list_workflow(actor):
    svc = runtime.get_service()
    out = []
    for e in svc.my_events(actor):
        if e.created_by != actor.subject:
            continue        # vendor portal lists the events this vendor proposed
        view = svc.event_view(actor, e.event_id)
        details = {"event_name": e.name, "event_start": str(e.start_date or ""), "event_city": e.city}
        item = _details_item(view)
        if item is not None:
            versions, _ = svc.history(actor, item.item_id)
            if versions:
                import json
                details.update(json.loads(versions[-1].text_json or "{}"))
        speakers = [m.display_name or m.email for m in view.members
                    if m.role == SPEAKER and m.status in (ACTIVE, INVITED)]
        out.append(VendorEvent(e.event_id, WORKFLOW_STATUS.get(e.status, e.status.title()),
                               {k: str(details.get(k, "") or "") for k in vv.FIELDS}, speakers))
    return out


def existing_keys(actor) -> set:
    return {vv.dedupe_key(e.details.get("event_name"), e.details.get("event_start"), actor.email)
            for e in list_my_events(actor)}


def submit_event(actor, draft: dict, token: str) -> Outcome:
    d = _clean(draft)
    errs = vv.validate(d)
    if errs:
        return Outcome(False, message=next(iter(errs.values())))
    try:
        if mode() == WORKFLOW:
            svc = runtime.get_service()
            res = svc.propose_event(actor, name=d["event_name"], start_date=vv.to_date(d["event_start"]),
                                    city=d["event_city"], details=d, token=token)
            if res.status == "duplicate":
                return Outcome(True, res.ref, "Already submitted.", duplicate=True)
            runtime.after_action(svc, res)      # delivery attempt; failures never undo the record
            return Outcome(True, res.ref, "Event submitted.")
        api = _sheets()
        now = _now()
        ref = f"EV-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"
        rid = ref.replace("EV-", "SR-")
        if not api.append_row("Events", _event_row(ref, now, "Pending", actor.email, d)):
            return Outcome(False, message=RETRY_MSG)
        if not api.append_row("Speaker_Requests", _request_row(rid, now, "Pending", ref, d)):
            log.error("speaker request append failed for %s", ref)
            return Outcome(True, ref, "Event submitted. The program team will confirm your speaker request.")
        return Outcome(True, ref, "Event submitted.")
    except InvalidAction as exc:
        return Outcome(False, message=str(exc))
    except NotAuthorized:
        return Outcome(False, message="Your account can't submit events. Contact aba.micah@snowflake.com.")
    except Exception:
        log.exception("vendor submit failed")
        return Outcome(False, message=RETRY_MSG)


def update_pending(actor, ref: str, draft: dict, token: str) -> Outcome:
    d = _clean(draft)
    errs = vv.validate(d)
    if errs:
        return Outcome(False, message=next(iter(errs.values())))
    try:
        if mode() == WORKFLOW:
            svc = runtime.get_service()
            event = next((e for e in svc.my_events(actor)
                          if e.event_id == ref and e.created_by == actor.subject), None)
            if event is None or event.status != PROPOSED:
                return Outcome(False, message="Only your pending events can be edited.")
            item = _details_item(svc.event_view(actor, ref))
            res = svc.submit_item(actor, item.item_id, text=d, token=token)
            if res.status == "no_change":
                return Outcome(True, ref, "Nothing changed.")
            runtime.after_action(svc, res)
            return Outcome(True, ref, "Changes saved.")
        api = _sheets()
        ev, rq, idx = _mine_sheets(actor.email)
        hit = [i for i in idx if str(ev.loc[i].get("event_id", "")) == ref]
        if not hit:
            return Outcome(False, message="Only your pending events can be edited.")
        row = ev.loc[hit[0]].to_dict()
        if str(row.get("status", "") or "Pending") != "Pending":
            return Outcome(False, message="This event has already been reviewed and can't be edited.")
        sheet_row = list(ev.index).index(hit[0]) + 2
        new_ev = _event_row(ref, row.get("submitted_at", ""), "Pending", actor.email,
                            {**{c: row.get(c, "") for c in EVENT_COLS}, **d}, row.get("admin_notes", ""))
        if not api.update_row("Events", sheet_row, new_ev):
            return Outcome(False, message=RETRY_MSG)
        ri, req = _request_for(rq, ref)
        if req is not None:
            new_rq = _request_row(req.get("request_id", ""), req.get("submitted_at", ""),
                                  req.get("status", "Pending"), ref, {**req, **d},
                                  req.get("matched_speaker", ""), req.get("admin_notes", ""))
            api.update_row("Speaker_Requests", list(rq.index).index(ri) + 2, new_rq)
        return Outcome(True, ref, "Changes saved.")
    except InvalidAction as exc:
        return Outcome(False, message=str(exc))
    except Exception:
        log.exception("vendor update failed")
        return Outcome(False, message=RETRY_MSG)


def submit_bulk(actor, rows: list[dict], token: str) -> list[dict]:
    """Submit validated rows; skip duplicates against existing events and earlier rows in the file."""
    try:
        seen = existing_keys(actor)
    except RuntimeError:
        return [{"row": r.get("_row", ""), "event_name": r.get("event_name", ""), "result": "Not submitted",
                 "detail": LOAD_MSG} for r in rows]
    results = []
    for r in rows:
        key = vv.dedupe_key(r.get("event_name"), r.get("event_start"), actor.email)
        base = {"row": r.get("_row", ""), "event_name": r.get("event_name", "")}
        if key in seen:
            results.append({**base, "result": "Skipped", "detail": "Duplicate of an event you already submitted"})
            continue
        out = submit_event(actor, r, f"{token}-{r.get('_row', '')}")
        if out.ok:
            seen.add(key)
            results.append({**base, "result": "Submitted", "detail": out.ref})
        else:
            results.append({**base, "result": "Failed", "detail": out.message})
    return results
