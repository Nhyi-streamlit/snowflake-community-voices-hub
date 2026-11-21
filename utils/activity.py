"""Speaker self-reports ("Share an update"): talks they're giving and CFPs they've submitted.

Saved to the hub tab Speaker_Updates, keyed on email + event + date so a second report for the same talk edits
that row instead of adding one. Confirmed talks (and accepted CFPs with a date) are added to the program sheet's
Speaker-Events (Stage = Confirmed), with a new Event List row when the event isn't there yet. Anything the
program sheet can't take is recorded in Needs_Review rather than guessed. Tests use ops_store.OVERRIDE["sheets"]
for the hub and slots.OVERRIDE["program"] for the program sheet.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from utils import ops_store as ops
from utils import slots as sl

TAB = "Speaker_Updates"
REVIEW_TAB = "Needs_Review"
SPEAKING, CFP = "speaking", "cfp"
CONFIRMED, SUBMITTED, ACCEPTED, DECLINED = "Confirmed", "Submitted", "Accepted", "Declined"
CHOICES = {"I'm speaking at an event": SPEAKING, "I submitted a CFP": CFP, "My CFP was accepted / declined": "cfp_result"}
MAX_LEN = 500


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clip(v) -> str:
    return str(v or "").strip()[:MAX_LEN]


def _norm(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def key_of(email: str, event: str, when: str) -> str:
    return f"{_clip(email).lower()}|{_norm(event)}|{_clip(when)[:10]}"


def updates(email: str | None = None) -> list[dict]:
    rows = ops.records(TAB)
    return [r for r in rows if email is None or r.get("email", "").lower() == email.strip().lower()]


def my_cfps(email: str) -> list[dict]:
    return [r for r in updates(email) if r.get("kind") == CFP]


def flag(source: str, ref: str, detail: str, reason: str) -> None:
    """One Needs_Review row per (source, ref); re-flagging updates it rather than duplicating."""
    ops.upsert(REVIEW_TAB, "key", f"{source}|{ref}", {"found_at": _now(), "source": source, "detail": detail,
                                                      "reason": reason, "status": "Open"})


def report_talk(*, name: str, email: str, event: str, date: str, city: str = "", link: str = "", talk_title: str = "",
                partner: str = "") -> tuple[bool, str]:
    """"I'm speaking at an event". Same email + event + date edits the existing row."""
    if not (_clip(email) and _clip(event) and _clip(date)):
        return False, "Add your email, the event and the date."
    k = key_of(email, event, date)
    existing = next((r for r in updates() if r.get("key") == k), None)
    rec = {"kind": SPEAKING, "name": _clip(name), "email": _clip(email).lower(), "event_name": _clip(event),
           "event_date": _clip(date)[:10], "city": _clip(city), "link": _clip(link), "talk_title": _clip(talk_title),
           "partner": _clip(partner), "status": CONFIRMED, "updated_at": _now(),
           "submitted_at": (existing or {}).get("submitted_at") or _now()}
    if not ops.upsert(TAB, "key", k, rec):
        return False, "We couldn't save that just now. Please try again in a moment."
    note = sync_talk({**(existing or {}), **rec, "key": k})
    return True, ("Updated your talk." if existing else "Thanks! Your talk is on the program.") + (f" {note}" if note else "")


def report_cfp(*, name: str, email: str, conference: str, cfp_link: str = "", deadline: str = "",
               talk_title: str = "", event_date: str = "", city: str = "") -> tuple[bool, str]:
    """"I submitted a CFP" → status Submitted (re-submitting the same CFP edits the row)."""
    if not (_clip(email) and _clip(conference)):
        return False, "Add your email and the conference."
    k = key_of(email, conference, event_date)
    existing = next((r for r in updates() if r.get("key") == k), None)
    rec = {"kind": CFP, "name": _clip(name), "email": _clip(email).lower(), "event_name": _clip(conference),
           "event_date": _clip(event_date)[:10], "city": _clip(city), "link": _clip(cfp_link),
           "talk_title": _clip(talk_title), "cfp_deadline": _clip(deadline)[:10], "updated_at": _now(),
           "status": (existing or {}).get("status") or SUBMITTED,
           "submitted_at": (existing or {}).get("submitted_at") or _now()}
    if not ops.upsert(TAB, "key", k, rec):
        return False, "We couldn't save that just now. Please try again in a moment."
    return True, "Updated your CFP." if existing else "Good luck! We've noted your CFP submission."


def cfp_result(key: str, email: str, result: str, *, event_date: str = "", city: str = "") -> tuple[bool, str]:
    """"My CFP was accepted / declined": updates that speaker's own CFP row."""
    if result not in (ACCEPTED, DECLINED):
        return False, "Choose accepted or declined."
    row = next((r for r in my_cfps(email) if r.get("key") == key), None)
    if row is None:
        return False, "We couldn't find that CFP under your email."
    fields = {"status": result, "decided_at": _now(), "updated_at": _now()}
    if event_date:
        fields["event_date"] = _clip(event_date)[:10]
    if city:
        fields["city"] = _clip(city)
    if not ops.upsert(TAB, "key", key, fields):
        return False, "We couldn't save that just now. Please try again in a moment."
    if result == DECLINED:
        return True, "Thanks for letting us know. There will be other stages!"
    rec = {**row, **fields}
    if not rec.get("event_date"):
        return True, "Congratulations! Add the talk date when you have it and we'll put it on the program."
    note = sync_talk(rec)
    return True, "Congratulations! Your talk is on the program." + (f" {note}" if note else "")


# ── Program sheet ────────────────────────────────────────────────────────────────────────────────────────────────

def _find_event(evl, event: str, date: str, city: str):
    if evl.empty or "Date" not in evl:
        return None
    same_day = evl[evl["Date"].astype(str).str[:10] == date[:10]]
    for _, r in same_day.iterrows():
        if _norm(r.get("Event Name", "")) == _norm(event) or (city and _norm(r.get("City", "")) == _norm(city)):
            return str(r["Event ID"])
    return None


def sync_talk(rec: dict) -> str:
    """Add or confirm the talk on Speaker-Events. Returns a short note for the speaker ("" when all went well).
    Never raises; anything that can't be matched goes to Needs_Review."""
    try:
        p = sl._program()
        spk = p.read("Speakers")
        hit = spk[spk["Email"].astype(str).str.strip().str.lower() == rec["email"]] if "Email" in spk else spk.iloc[0:0]
        if len(hit):
            spk_id = str(hit.iloc[0]["Speaker ID"])
        else:
            spk_id = sl._next_id(spk, "Speaker ID", "SPK")
            p.append("Speakers", [spk_id, rec.get("name") or "[confirm]", rec["email"], "[confirm]", "", "", "",
                                  "[confirm]", "", "Accepted", "Speaker Hub update", ""])
        evl = p.read("Event List")
        evt_id = _find_event(evl, rec["event_name"], rec["event_date"], rec.get("city", ""))
        if evt_id is None:
            evt_id = sl._next_id(evl, "Event ID", "EVT")
            p.append("Event List", [evt_id, rec["event_name"], rec.get("partner") or "[confirm]", rec["event_date"],
                                    None, rec.get("city") or "[confirm]", "[confirm]", None, rec.get("link", ""),
                                    "Confirmed", "Added from a Speaker Hub update"])
        se = p.read("Speaker-Events")
        mine = se[(se["Speaker ID"].astype(str) == spk_id) & (se["Event ID"].astype(str) == evt_id)] \
            if {"Speaker ID", "Event ID"} <= set(se.columns) else se.iloc[0:0]
        if len(mine):
            se_id = str(mine.iloc[0]["SE ID"])
            stage = str(mine.iloc[0].get("Stage", "") or "")
            if stage not in ("Delivered", CONFIRMED):
                p.set("Speaker-Events", int(mine.index[0]) + 2, "Stage", CONFIRMED)
            if rec.get("talk_title") and not str(mine.iloc[0].get("Talk Title", "") or "").strip():
                p.set("Speaker-Events", int(mine.index[0]) + 2, "Talk Title", rec["talk_title"])
        else:
            se_id = sl._next_id(se, "SE ID", "SE")
            p.append("Speaker-Events", [se_id, spk_id, evt_id, None, None, None, None, None, None, None, "[confirm]",
                                        CONFIRMED, "Yes", "", rec.get("talk_title", ""), "Talk"])
        ops.upsert(TAB, "key", rec["key"], {"se_id": se_id, "sync_note": ""})
        return ""
    except Exception as ex:
        reason = type(ex).__name__
        ops.upsert(TAB, "key", rec["key"], {"sync_note": f"not synced ({reason})"})
        flag(TAB, rec["key"], f"{rec.get('name', '')} · {rec.get('event_name', '')} · {rec.get('event_date', '')}",
             f"Couldn't add to Speaker-Events ({reason})")
        return ""
