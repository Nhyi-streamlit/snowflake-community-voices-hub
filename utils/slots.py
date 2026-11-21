"""Partner speaker slots: speakers claim a slot in the Speaker Portal, Aba accepts or declines in Workflow admin.

Slots are Events-tab rows with opportunity_type "Speaker slot"; their slot_status moves Open → Pending review → Filled
(or back to Open on decline). Claims live in the hub tab Slot_Claims, keyed on event_id|email, so a double submit
records once. Aba is emailed about each claim; the speaker gets one email when Aba decides (speaker_notified_at makes
it send-once). Accepting also adds the talk to the program sheet (Event List, Speakers, Speaker-Events).

Tests set OVERRIDE["events"] (a MemoryEvents), OVERRIDE["program"] (a MemoryProgram), ops_store.OVERRIDE["sheets"]
for Slot_Claims, and a fake GmailClient as utils.sheets._gmail_client.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from utils import ops_store as ops
from utils import public_events as pe

TAB = "Slot_Claims"
ADMIN_EMAIL = "aba.micah@snowflake.com"
PROGRAM_SPREADSHEET_ID = "1zQlOQYBqyVn9pAFjNQCM0LZleq1VktUmqFbuRq3Je8c"   # Community Voices program sheet
CONFERENCE_FORM_URL = "https://app-superhero-creator-form-5rkbvp9kjmrkjjkqfbslqj.streamlit.app/"
TRAVEL_OPTIONS = ["Flight", "Hotel", "Uber / ground"]
PENDING, WAITLIST, ACCEPTED, DECLINED = "pending", "waitlist", "accepted", "declined"
OPEN_CLAIMS = (PENDING, WAITLIST)

OVERRIDE: dict = {}


def _secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default)
    except Exception:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _e(v) -> str:
    return html.escape(str(v or ""))


def _table(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555;vertical-align:top'><b>{_e(k)}</b></td>"
                   f"<td style='padding:4px 0;white-space:pre-wrap'>{_e(v) or '—'}</td></tr>" for k, v in pairs)
    return f"<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'>{rows}</table>"


def _send(to, subject, body, cc=None):
    from utils.sheets import send_gmail_result
    return send_gmail_result(to, subject, body, cc=cc)


def _nice_date(value: str) -> str:
    d = pe.parse_date(value)
    return d.strftime("%a, %b %-d, %Y") if d else (value or "date TBD")


# ── Events tab (hub sheet) ──────────────────────────────────────────────────────────────────────────────────────

class SheetEvents:
    def read(self) -> pd.DataFrame:
        from utils.sheets import read_tab
        return read_tab("Events")

    def set(self, event_id: str, field: str, value: str) -> bool:
        from utils.sheets import col_letter, update_cell
        df = self.read()
        hits = df.index[df["event_id"].astype(str) == event_id].tolist() if "event_id" in df else []
        if not hits or field not in df:
            return False
        return update_cell("Events", hits[0] + 2, col_letter(df, field), value)

    def append(self, row: list) -> bool:
        from utils.sheets import append_row
        return append_row("Events", row)


class MemoryEvents:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def read(self):
        return self.df.copy()

    def set(self, event_id, field, value):
        hit = self.df["event_id"].astype(str) == event_id
        if not hit.any():
            return False
        self.df.loc[hit, field] = value
        return True

    def append(self, row):
        self.df.loc[len(self.df)] = (list(row) + [""] * len(self.df.columns))[:len(self.df.columns)]
        return True


def _events():
    return OVERRIDE.get("events") or SheetEvents()


def _clear_cache():
    try:
        pe._approved_from_sheet.clear()
    except Exception:
        pass


def event(event_id: str) -> dict | None:
    df = _events().read()
    if df is None or df.empty or "event_id" not in df:
        return None
    rows = df[df["event_id"].astype(str) == event_id].fillna("").to_dict("records")
    return {k: str(v) for k, v in rows[0].items()} if rows else None


def _set_slot(event_id: str, status: str) -> bool:
    ok = _events().set(event_id, "slot_status", status)
    _clear_cache()
    return ok


EVENT_COLS = ["event_id", "submitted_at", "status", "organizer_name", "organizer_email", "organizer_org",
              "organizer_role", "org_website", "event_name", "event_website", "event_start", "event_end", "event_city",
              "event_country", "event_format", "expected_audience", "community_alignment", "event_description",
              "how_heard", "additional_notes", "admin_notes", "opportunity_type", "slot_status", "cfp_deadline"]


def add_slot(partner: str, event_name: str, start: date, city: str, country: str, website: str = "",
             description: str = "", contact: str = "") -> tuple[bool, str]:
    """Hub Admin: add a partner speaker slot, visible in the Speaker Portal right away."""
    if not (partner.strip() and event_name.strip() and city.strip() and start):
        return False, "Partner, event name, city and date are required."
    eid = f"EV-SLOT-{uuid.uuid4().hex[:8].upper()}"
    vals = {"event_id": eid, "submitted_at": _now(), "status": "Approved", "organizer_name": contact.strip(),
            "organizer_org": partner.strip(), "organizer_role": "Partner", "event_name": event_name.strip(),
            "event_website": website.strip(), "event_start": start.isoformat(), "event_end": start.isoformat(),
            "event_city": city.strip(), "event_country": country.strip(), "event_format": "In-person",
            "event_description": description.strip(), "how_heard": "Added by admin",
            "opportunity_type": pe.SPEAKER_SLOT, "slot_status": pe.OPEN}
    if not _events().append([vals.get(c, "") for c in EVENT_COLS]):
        return False, "Couldn't save the slot. Try again."
    _clear_cache()
    return True, f"Added {event_name} ({start:%b %-d}). It's now listed as an open slot."


# ── Claims ──────────────────────────────────────────────────────────────────────────────────────────────────────

def key_of(event_id: str, email: str) -> str:
    return f"{event_id}|{email.strip().lower()}"


def claims() -> list[dict]:
    return [r for r in ops.records(TAB) if r.get("key")]


def _claim(key: str) -> dict | None:
    return next((r for r in claims() if r["key"] == key), None)


def notify_email(c: dict, base_url: str) -> tuple[str, str]:
    link = f"{base_url.rstrip('/')}/workflow-admin?tab=slots"
    lead = "is on the waitlist for" if c["status"] == WAITLIST else "claimed"
    body = (f"<p><b>{_e(c['name'])}</b> {lead} a speaker slot.</p>"
            + _table([("Speaker", c["name"]), ("Email", c["email"]), ("Event", c["event_name"]),
                      ("Date", _nice_date(c["event_date"])), ("City", c["event_city"]), ("Talk", c["talk_title"]),
                      ("Abstract", c["abstract"]), ("Travel support", c["travel"] or "None"),
                      ("Status", "Waitlist (slot already claimed)" if c["status"] == WAITLIST else "Pending your review"),
                      ("Submitted", c["submitted_at"])])
            + f"<p><a href='{_e(link)}'>Accept or decline in Workflow admin</a></p>")
    return f"Speaker slot claim: {c['name']} · {c['event_name']} ({_nice_date(c['event_date'])})", body


def claim(event_id: str, name: str, email: str, talk_title: str, abstract: str, travel: list[str] | None = None,
          base_url: str = "") -> tuple[bool, str]:
    """Record a speaker's claim (once), move the slot to Pending review, and email Aba. Returns (ok, message)."""
    from utils.email_otp import valid_email
    name, email, talk_title = name.strip(), email.strip().lower(), talk_title.strip()
    if not (name and talk_title and valid_email(email)):
        return False, "Please add your name, a valid email and a talk title."
    ev = event(event_id)
    if ev is None or ev.get("opportunity_type") != pe.SPEAKER_SLOT:
        return False, "We couldn't find that slot. Please refresh the page."
    k = key_of(event_id, email)
    mine = _claim(k)
    if mine and mine.get("status") in (*OPEN_CLAIMS, ACCEPTED):
        return True, "You've already claimed this slot. Aba will be in touch."
    slot = ev.get("slot_status", "")
    if slot in (pe.FILLED, pe.CANCELED):
        return False, "Sorry, this slot is no longer available. Take a look at the other open slots."
    status = PENDING if slot == pe.OPEN else WAITLIST
    rec = {"event_id": event_id, "event_name": ev.get("event_name", ""), "event_date": ev.get("event_start", ""),
           "event_city": ev.get("event_city", ""), "name": name, "email": email, "talk_title": talk_title,
           "abstract": abstract.strip(), "travel": ", ".join(travel or []), "submitted_at": _now(), "status": status,
           "notified_at": "", "decided_by": "", "decided_at": "", "speaker_notified_at": "", "notes": ""}
    if not ops.upsert(TAB, "key", k, rec):
        return False, "Something went wrong saving your claim. Please try again."
    if status == PENDING:
        _set_slot(event_id, pe.PENDING_REVIEW)
    if _send([ADMIN_EMAIL], *notify_email({**rec, "key": k}, base_url or _secret("APP_BASE_URL"))):
        ops.upsert(TAB, "key", k, {"notified_at": _now()})
    if status == WAITLIST:
        return True, "Thanks! Someone has already claimed this slot, so you're on the waitlist. Aba will let you know."
    return True, "Thanks! Aba will confirm within 2 business days."


def accept_email(c: dict, note: str = "") -> tuple[str, str]:
    first = c["name"].split()[0] if c["name"] else "there"
    d = pe.parse_date(c["event_date"])
    due = f" (by {(d - timedelta(days=14)):%b %-d})" if d else ""
    steps = [f"Send your final talk title, abstract and slides at least 2 weeks before the event{due}. Just reply to this email.",
             "Grab the brand kit and talk templates under Resources in the Speaker Portal."]
    if c.get("travel"):
        steps.insert(1, f"You asked for travel support ({c['travel']}). Please fill in the conference support form so we "
                        f"can book it: {CONFERENCE_FORM_URL}")
    steps.append("On the day, show your feedback QR code from the Speaker Portal (After your talk).")
    body = (f"<p>Hi {_e(first)},</p><p>Great news: you're confirmed to speak at <b>{_e(c['event_name'])}</b> in "
            f"{_e(c['event_city'])} on <b>{_e(_nice_date(c['event_date']))}</b>. Thank you for raising your hand!</p>"
            f"<p><b>Talk:</b> {_e(c['talk_title'])}</p><p><b>Next steps</b></p><ol>"
            + "".join(f"<li>{_e(s)}</li>" for s in steps) + "</ol>"
            + (f"<p><b>Note from Aba:</b> {_e(note)}</p>" if note else "")
            + "<p>So excited to have you on stage!</p><p>Thanks,<br>Aba Micah<br>Snowflake Community Voices</p>")
    return f"You're confirmed: {c['event_name']} on {_nice_date(c['event_date'])}", body


def decline_email(c: dict, note: str = "", base_url: str = "") -> tuple[str, str]:
    first = c["name"].split()[0] if c["name"] else "there"
    link = f"{(base_url or _secret('APP_BASE_URL')).rstrip('/')}/Speaker_Portal?section=speak"
    body = (f"<p>Hi {_e(first)},</p><p>Thank you so much for raising your hand for <b>{_e(c['event_name'])}</b> "
            f"on {_e(_nice_date(c['event_date']))}. We weren't able to place you in this one, but we'd love to have you "
            f"speak at another event.</p>"
            + (f"<p><b>Note from Aba:</b> {_e(note)}</p>" if note else "")
            + f"<p>You can see the other open slots here: <a href='{_e(link)}'>{_e(link)}</a></p>"
            "<p>Thanks again,<br>Aba Micah<br>Snowflake Community Voices</p>")
    return f"About the {c['event_name']} speaker slot", body


def decide(key: str, decision: str, actor_email: str, note: str = "") -> tuple[bool, str]:
    """Accept or decline a claim. Emails the speaker once (cc Aba on accept). Returns (ok, message)."""
    c = _claim(key)
    if c is None:
        return False, "Claim not found."
    if c.get("status") not in OPEN_CLAIMS:
        return False, f"Already {c.get('status')}; not changed."
    eid = c["event_id"]
    if decision == ACCEPTED:
        taken = [r for r in claims() if r["event_id"] == eid and r.get("status") == ACCEPTED]
        if taken:
            return False, f"This slot is already filled by {taken[0]['name']}. Decline this claim instead."
        ops.upsert(TAB, "key", key, {"status": ACCEPTED, "decided_by": actor_email, "decided_at": _now(), "notes": note})
        _set_slot(eid, pe.FILLED)
        sync = sync_program(c)
        sent = _send([c["email"]], *accept_email(c, note), cc=[ADMIN_EMAIL])
        msg = f"Accepted {c['name']}. Slot marked Filled. {sync}"
    elif decision == DECLINED:
        ops.upsert(TAB, "key", key, {"status": DECLINED, "decided_by": actor_email, "decided_at": _now(), "notes": note})
        waiting = sorted((r for r in claims() if r["event_id"] == eid and r.get("status") == WAITLIST),
                         key=lambda r: r.get("submitted_at", ""))
        others = [r for r in claims() if r["event_id"] == eid and r["key"] != key]
        if any(r.get("status") == ACCEPTED for r in others):
            msg_slot = "Slot stays filled."
        elif c.get("status") == PENDING and waiting:
            ops.upsert(TAB, "key", waiting[0]["key"], {"status": PENDING})
            msg_slot = f"{waiting[0]['name']} (waitlist) is now up for review."
        elif not any(r.get("status") == PENDING for r in others):
            _set_slot(eid, pe.OPEN)
            msg_slot = "Slot reopened."
        else:
            msg_slot = "Slot stays in review."
        sent = _send([c["email"]], *decline_email(c, note))
        msg = f"Declined {c['name']}. {msg_slot}"
    else:
        return False, "Unknown decision."
    if sent:
        ops.upsert(TAB, "key", key, {"speaker_notified_at": _now()})
        return True, msg + " Speaker emailed."
    return False, msg + f" But the email to the speaker failed: {getattr(sent, 'reason', '') or 'send_failed'}."


# ── Program sheet sync (Event List, Speakers, Speaker-Events) ─────────────────────────────────────────────────────

class SheetProgram:
    def read(self, tab: str) -> pd.DataFrame:
        from utils.sheets import read_tab
        return read_tab(tab, spreadsheet_id=PROGRAM_SPREADSHEET_ID)

    def append(self, tab: str, row: list) -> bool:
        from utils.sheets import append_row
        return append_row(tab, row, spreadsheet_id=PROGRAM_SPREADSHEET_ID, value_input="USER_ENTERED")

    def set(self, tab: str, sheet_row: int, column: str, value: str) -> bool:
        """One cell by header name; sheet_row is 1-based (row 2 = first data row)."""
        from utils.sheets import read_tab, update_cell
        cols = list(read_tab(tab, spreadsheet_id=PROGRAM_SPREADSHEET_ID).columns)
        i = cols.index(column)
        letter = (chr(64 + i // 26) if i >= 26 else "") + chr(65 + i % 26)
        return update_cell(tab, sheet_row, letter, value, spreadsheet_id=PROGRAM_SPREADSHEET_ID,
                           value_input="USER_ENTERED")


class MemoryProgram:
    def __init__(self, tabs: dict[str, pd.DataFrame]):
        self.tabs = {k: v.copy() for k, v in tabs.items()}

    def read(self, tab):
        return self.tabs[tab].copy()

    def append(self, tab, row):
        df = self.tabs[tab]
        df.loc[len(df)] = ([("" if v is None else str(v)) for v in row] + [""] * len(df.columns))[:len(df.columns)]
        return True

    def set(self, tab, sheet_row, column, value):
        df = self.tabs[tab]
        if column not in df.columns:
            df[column] = ""
        df.loc[sheet_row - 2, column] = str(value)
        return True


def _program():
    return OVERRIDE.get("program") or SheetProgram()


def _next_id(df: pd.DataFrame, col: str, prefix: str) -> str:
    nums = [int(m.group(1)) for v in (df[col] if col in df else []) if (m := re.match(rf"{prefix}-(\d+)$", str(v)))]
    return f"{prefix}-{(max(nums) if nums else 0) + 1:03d}"


def sync_program(c: dict) -> str:
    """Add the accepted talk to the program sheet. None leaves formula columns untouched. Never raises."""
    try:
        p = _program()
        spk = p.read("Speakers")
        hit = spk[spk["Email"].astype(str).str.strip().str.lower() == c["email"]] if "Email" in spk else spk.iloc[0:0]
        if len(hit):
            spk_id = str(hit.iloc[0]["Speaker ID"])
        else:
            spk_id = _next_id(spk, "Speaker ID", "SPK")
            p.append("Speakers", [spk_id, c["name"], c["email"], "[confirm]", "", "", "", "[confirm]", "", "Accepted",
                                  "Speaker Hub slot claim", ""])
        evl = p.read("Event List")
        same = evl[(evl["Date"].astype(str).str[:10] == c["event_date"][:10])
                   & (evl["City"].astype(str).str.lower() == c["event_city"].lower())] if "Date" in evl else evl.iloc[0:0]
        if len(same):
            evt_id = str(same.iloc[0]["Event ID"])
        else:
            evt_id = _next_id(evl, "Event ID", "EVT")
            ev = event(c["event_id"]) or {}
            p.append("Event List", [evt_id, c["event_name"], ev.get("organizer_org", "") or "[confirm]", c["event_date"],
                                    None, c["event_city"], "[confirm]", None, ev.get("event_website", ""), "Confirmed",
                                    "Added from Speaker Hub slot claim"])
        se = p.read("Speaker-Events")
        se_id = _next_id(se, "SE ID", "SE")
        p.append("Speaker-Events", [se_id, spk_id, evt_id, None, None, None, None, None, None, None, "[confirm]",
                                    "Confirmed", "Yes", "", c["talk_title"], "Talk"])
        return f"Added {se_id} to the program sheet."
    except Exception as ex:
        return f"Couldn't update the program sheet ({type(ex).__name__}); add it there by hand."


# ── Workflow admin UI ───────────────────────────────────────────────────────────────────────────────────────────

def render(actor) -> None:
    import streamlit as st
    from workflow.ui import md
    if actor is None or not actor.is_admin:
        st.error("This area is restricted to program administrators.")
        return
    for ok, msg in st.session_state.pop("slot_flash", []):
        (st.success if ok else st.error)(md(msg))
    flash = lambda ok, msg: st.session_state.setdefault("slot_flash", []).append((ok, msg))  # noqa: E731

    st.markdown("#### Speaker slot claims")
    st.caption("Accepting fills the slot, adds the talk to the program sheet and emails the speaker (cc you). "
               "Declining reopens the slot (or moves the next waitlisted speaker up) and sends a kind note.")
    waiting = sorted((c for c in claims() if c.get("status") in OPEN_CLAIMS),
                     key=lambda c: (c.get("event_date", ""), c.get("status") != PENDING, c.get("submitted_at", "")))
    if not waiting:
        st.caption("No claims waiting for you.")
    for c in waiting:
        n = c["_row"]
        with st.container(border=True):
            tag = " · _waitlist_" if c["status"] == WAITLIST else ""
            st.markdown(f"**{md(c['name'])}** · {md(c['email'])}{tag}")
            st.markdown(f"{md(c['event_name'])} · {md(c['event_city'])} · {md(_nice_date(c['event_date']))}")
            st.markdown(f"**Talk:** {md(c['talk_title'])}")
            if c.get("abstract"):
                st.caption(md(c["abstract"]))
            st.markdown(f"**Travel support:** {md(c.get('travel') or 'None')}")
            note = st.text_input("Note to the speaker (optional)", key=f"slot_note_{n}")
            act = st.container(horizontal=True)
            if act.button("Accept", type="primary", icon=":material/check:", key=f"slot_ok_{n}"):
                flash(*decide(c["key"], ACCEPTED, actor.email, note))
                st.rerun()
            if act.button("Decline", icon=":material/close:", key=f"slot_no_{n}"):
                flash(*decide(c["key"], DECLINED, actor.email, note))
                st.rerun()

    with st.expander("Add a speaker slot", icon=":material/add:"):
        with st.form("slot_add", clear_on_submit=True):
            c1, c2 = st.columns(2)
            partner = c1.text_input("Partner", value="AI Camp")
            contact = c2.text_input("Partner contact (optional)")
            name = st.text_input("Event name", placeholder="AI Camp Austin")
            c3, c4, c5 = st.columns(3)
            when = c3.date_input("Date", value=None)
            city = c4.text_input("City")
            country = c5.text_input("Country", value="United States")
            site = st.text_input("Event link (optional)")
            desc = st.text_area("What speakers should know (optional)", height=80)
            if st.form_submit_button("Add slot", type="primary"):
                flash(*add_slot(partner, name, when, city, country, site, desc, contact))
                st.rerun()

    all_claims = claims()
    try:
        slots = pe.speaker_slots(statuses=(pe.OPEN, pe.PENDING_REVIEW, pe.FILLED))
    except Exception:
        slots = None
    if slots is not None and not slots.empty:
        st.markdown("##### Upcoming speaker slots")
        who = {c["event_id"]: c["name"] for c in all_claims if c.get("status") == ACCEPTED}
        st.dataframe(pd.DataFrame([{"Date": r["start"], "Event": r["event_name"], "City": r["event_city"],
                                    "Status": r.get("slot_status", ""), "Speaker": who.get(r.get("event_id", ""), "")}
                                   for r in slots.to_dict("records")]), hide_index=True)
    done = [c for c in all_claims if c.get("status") in (ACCEPTED, DECLINED)]
    if done:
        with st.expander(f"Decided · {len(done)}"):
            st.dataframe(pd.DataFrame([{"Speaker": c["name"], "Event": c["event_name"], "Date": c["event_date"],
                                        "Status": c["status"], "By": c["decided_by"], "At": c["decided_at"],
                                        "Speaker emailed": c["speaker_notified_at"]} for c in done]), hide_index=True)
