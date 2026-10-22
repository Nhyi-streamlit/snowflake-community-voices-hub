"""Conference support requests from the Data Superhero & Streamlit Creator form.

The form appends rows to the "Filled Form" tab of the Event Support spreadsheet. The hourly job finds rows it
hasn't seen (keyed on Submitted At + Email), records them in the hub tab Conference_Approvals and emails Aba.
Approving in Workflow admin sends one booking email to Navan (cc Aba); navan_sent_at makes that send-once.

Tests set SHEETS_OVERRIDE["source"] (callable → DataFrame), ops_store.OVERRIDE["sheets"] for the hub tab, and a fake
GmailClient as utils.sheets._gmail_client.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd

from utils import ops_store as ops

TAB = "Conference_Approvals"
SOURCE_SPREADSHEET_ID = "1zQlOQYBqyVn9pAFjNQCM0LZleq1VktUmqFbuRq3Je8c"   # not a secret; override with a secret
SOURCE_TAB = "Filled Form"
ADMIN_EMAIL = "aba.micah@snowflake.com"
NAVAN_TO = ["alldavis@navan.com", "wbickmore@navan.com"]
PENDING, APPROVED, DECLINED, BASELINE = "pending", "approved", "declined", "baseline"
MAX_NOTIFY_PER_RUN = 10

SHEETS_OVERRIDE: dict = {}

# Source columns. The form has been renamed over time, so each field accepts a few header spellings.
COLS = {
    "submitted_at": ["Submitted At"], "first": ["First Name"], "last": ["Last Name"], "email": ["Email"],
    "country": ["Country"], "city": ["City"], "community": ["Community"], "event": ["Event Name"],
    "event_link": ["Event Link"], "talk": ["Talk Title"], "session": ["Session Type"],
    "depart": ["Departure Date"], "return": ["Return Date"], "from": ["Traveling From"], "to": ["Traveling To"],
    "notes": ["Notes", "Additional Notes"],
    "travel_mode": ["Preferred Travel Mode", "Preferred mode of travel", "Preferred Mode of Travel"],
}


def _secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default)
    except Exception:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _get(row: dict, field: str) -> str:
    for name in COLS[field]:
        v = str(row.get(name, "") or "").strip()
        if v:
            return v
    return ""


def key_of(row: dict) -> str:
    return f"{_get(row, 'submitted_at')}|{_get(row, 'email').lower()}"


def summary(row: dict) -> dict:
    """The Conference_Approvals fields taken from a form row."""
    dep, ret = _get(row, "depart"), _get(row, "return")
    return {"name": f"{_get(row, 'first')} {_get(row, 'last')}".strip(), "email": _get(row, "email"),
            "conference": _get(row, "event"), "dates": f"{dep} to {ret}" if dep and ret and dep != ret else dep or ret,
            "submitted_at": _get(row, "submitted_at")}


def source_rows() -> list[dict]:
    """Form rows with an email, de-duplicated by key (the last copy wins: re-submissions fill in more)."""
    if "source" in SHEETS_OVERRIDE:
        df = SHEETS_OVERRIDE["source"]()
    else:
        from utils.sheets import read_tab
        df = read_tab(_secret("CONFERENCE_SOURCE_TAB", SOURCE_TAB),
                      spreadsheet_id=_secret("CONFERENCE_SPREADSHEET_ID", SOURCE_SPREADSHEET_ID))
    if df is None or df.empty:
        return []
    out: dict[str, dict] = {}
    for r in df.fillna("").to_dict("records"):
        r = {k: str(v) for k, v in r.items()}
        if _get(r, "email"):
            out[key_of(r)] = r
    return list(out.values())


def source_row(key: str) -> dict | None:
    return next((r for r in source_rows() if key_of(r) == key), None)


def tracked() -> dict[str, dict]:
    return {r["key"]: r for r in ops.records(TAB) if r.get("key")}


def _send(to, subject, body, cc=None):
    from utils.sheets import send_gmail_result
    return send_gmail_result(to, subject, body, cc=cc)


def _e(v) -> str:
    return html.escape(str(v or ""))


def _table(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555;vertical-align:top'><b>{_e(k)}</b></td>"
                   f"<td style='padding:4px 0;white-space:pre-wrap'>{_e(v) or '—'}</td></tr>" for k, v in pairs)
    return f"<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'>{rows}</table>"


# ── Notify Aba ────────────────────────────────────────────────────────────────────────────────────────────────

def notify_email(row: dict, base_url: str) -> tuple[str, str]:
    s = summary(row)
    link = f"{base_url.rstrip('/')}/workflow-admin?tab=conference"
    body = (f"<p>New conference support request from <b>{_e(s['name'])}</b>.</p>"
            + _table([("Name", s["name"]), ("Email", s["email"]), ("Community", _get(row, "community")),
                      ("Conference", s["conference"]), ("Event link", _get(row, "event_link")),
                      ("Talk", _get(row, "talk")), ("Dates", s["dates"]),
                      ("Traveling from", _get(row, "from")), ("Traveling to", _get(row, "to")),
                      ("Preferred mode of travel", _get(row, "travel_mode")), ("Notes", _get(row, "notes")),
                      ("Submitted", s["submitted_at"])])
            + f"<p><a href='{_e(link)}'>Review and approve in Workflow admin</a></p>")
    return f"Conference support request: {s['name']} · {s['conference'] or 'event TBD'}", body


def check(notify: bool = True, baseline: bool = False, base_url: str = "", baseline_before: str = "") -> dict:
    """Record unseen form rows. Returns counts. Sends only to Aba.

    baseline=True records every current row as `baseline` (never shown, never emailed). Until a baseline exists
    the job refuses to notify, so the first run can't email about every historic row. With baseline_before
    (ISO date), only rows submitted before it (or undated) become baseline; later rows are recorded pending.
    """
    seen = tracked()
    rows = source_rows()
    res = {"new": 0, "notified": 0, "failed": [], "blocked": ""}
    if not seen and not baseline:
        res["blocked"] = "No baseline yet: run scripts/conference_requests.py --baseline once."
        return res
    for r in rows:
        k = key_of(r)
        if k in seen:
            continue
        early = not baseline_before or _get(r, "submitted_at")[:10] < baseline_before
        status = BASELINE if baseline and early else PENDING
        if ops.upsert(TAB, "key", k, {**summary(r), "status": status}):
            res["new"] += 1
            seen[k] = {"key": k, "status": status, "notified_at": ""}
    if baseline or not notify:
        return res
    # Pending rows that were never announced (new now, or an earlier send failed). Capped per run.
    for k, t in list(seen.items()):
        if t.get("status") != PENDING or t.get("notified_at"):
            continue
        if res["notified"] + len(res["failed"]) >= MAX_NOTIFY_PER_RUN:
            break
        row = next((r for r in rows if key_of(r) == k), None)
        if row is None:
            continue
        r = _send([ADMIN_EMAIL], *notify_email(row, base_url))
        if r:
            ops.upsert(TAB, "key", k, {"notified_at": _now()})
            res["notified"] += 1
        else:
            res["failed"].append(getattr(r, "reason", "") or "send_failed")
    return res


# ── Approve / decline / Navan ─────────────────────────────────────────────────────────────────────────────────

def navan_email(row: dict, note: str = "") -> tuple[str, str]:
    s = summary(row)
    body = ("<p>Hi Navan team,</p><p>Please arrange travel for the Snowflake community speaker below. "
            "This trip is approved by Snowflake Community Voices.</p>"
            + _table([("Traveler", s["name"]), ("Traveler email", s["email"]), ("Conference", s["conference"]),
                      ("Event link", _get(row, "event_link")), ("Departure date", _get(row, "depart")),
                      ("Return date", _get(row, "return")), ("Location", _get(row, "to")),
                      ("Traveling from", _get(row, "from")),
                      ("Traveler home city", ", ".join(x for x in (_get(row, "city"), _get(row, "country")) if x)),
                      ("Preferred mode of travel", _get(row, "travel_mode")),
                      ("Traveler's travel notes", _get(row, "notes")), ("Note from Snowflake", note)])
            + f"<p>Questions? Reply to this email or contact {ADMIN_EMAIL}.</p><p>Thanks,<br>Aba Micah<br>"
              "Snowflake Community Voices</p>")
    return f"Travel booking request (approved): {s['name']} · {s['conference'] or 'conference'}", body


def _deliver_navan(key: str, note: str, to=None, cc=None):
    row = source_row(key)
    if row is None:
        from utils.gmail_diag import SendResult
        return SendResult(False, "source_row_not_found")
    return _send(to or NAVAN_TO, *navan_email(row, note), cc=cc)


def decide(key: str, decision: str, actor_email: str, note: str = "") -> tuple[bool, str]:
    """Approve (and send to Navan once) or decline. Returns (ok, message)."""
    t = tracked().get(key)
    if t is None:
        return False, "Request not found."
    if decision == DECLINED:
        if t.get("status") == APPROVED:
            return False, "Already approved; not changed."
        ops.upsert(TAB, "key", key, {"status": DECLINED, "decided_by": actor_email, "decided_at": _now(),
                                     "notes": note})
        return True, f"Declined {t.get('name')}. Nothing was sent."
    if t.get("status") != APPROVED:
        ops.upsert(TAB, "key", key, {"status": APPROVED, "decided_by": actor_email, "decided_at": _now(),
                                     "notes": note})
    return send_navan(key)


def send_navan(key: str) -> tuple[bool, str]:
    """Send the approved request to Navan unless navan_sent_at is already set (fresh read guards double clicks)."""
    t = tracked().get(key)
    if t is None or t.get("status") != APPROVED:
        return False, "Only approved requests go to Navan."
    if t.get("navan_sent_at"):
        return True, f"Already sent to Navan at {t['navan_sent_at']}; not resent."
    r = _deliver_navan(key, t.get("notes", ""), cc=[ADMIN_EMAIL])
    if not r:
        return False, (f"Approved, but the Navan email failed: {getattr(r, 'reason', '') or 'send_failed'}. "
                       "Use Retry once it's fixed.")
    ops.upsert(TAB, "key", key, {"navan_sent_at": _now()})
    return True, f"Approved {t.get('name')} and emailed Navan (cc you)."


def send_navan_test_to_admin(key: str, note: str = ""):
    """The Navan email sent to Aba only. Records nothing."""
    return _deliver_navan(key, note, to=[ADMIN_EMAIL])


# ── Workflow admin area ───────────────────────────────────────────────────────────────────────────────────────

def render(actor) -> None:
    import streamlit as st
    from workflow.ui import md
    if actor is None or not actor.is_admin:
        st.error("This area is restricted to program administrators.")
        return
    for ok, msg in st.session_state.pop("conf_flash", []):
        (st.success if ok else st.error)(md(msg))
    flash = lambda ok, msg: st.session_state.setdefault("conf_flash", []).append((ok, msg))  # noqa: E731

    top = st.container(horizontal=True, vertical_alignment="center")
    top.markdown("#### Conference support requests")
    if top.button("Check for new requests now", icon=":material/refresh:", key="conf_check"):
        try:
            r = check(notify=True, base_url=_secret("APP_BASE_URL"))
        except Exception as e:
            flash(False, f"Couldn't read the form sheet ({type(e).__name__}).")
        else:
            if r["blocked"]:
                flash(False, r["blocked"])
            else:
                flash(not r["failed"], f"{r['new']} new, {r['notified']} emailed to you"
                      + (f", {len(r['failed'])} email(s) failed: {', '.join(r['failed'])}" if r["failed"] else "."))
        st.rerun()

    rows = list(tracked().values())
    pending = [r for r in rows if r.get("status") == PENDING]
    unsent = [r for r in rows if r.get("status") == APPROVED and not r.get("navan_sent_at")]
    st.caption("Approving emails Navan once (cc you). Declining records the decision and sends nothing.")

    if unsent:
        st.markdown(f"##### Approved but not sent to Navan · {len(unsent)}")
        for r in unsent:
            with st.container(border=True):
                row = st.container(horizontal=True, vertical_alignment="center")
                row.markdown(f"**{md(r['name'])}** · {md(r['conference'])} · {md(r['dates'])}")
                if row.button("Retry", icon=":material/send:", key=f"conf_retry_{r['_row']}"):
                    flash(*send_navan(r["key"]))
                    st.rerun()

    st.markdown(f"##### Pending · {len(pending)}")
    if not pending:
        st.caption("No pending requests.")
    for r in pending:
        k, n = r["key"], r["_row"]
        with st.container(border=True):
            st.markdown(f"**{md(r['name'])}** · {md(r['email'])}")
            st.markdown(f"{md(r['conference']) or '_Event not named_'} · {md(r['dates']) or 'dates not given'} · "
                        f"submitted {md(r['submitted_at'])}")
            note = st.text_input("Note (optional, included in the Navan email)", key=f"conf_note_{n}")
            act = st.container(horizontal=True)
            if act.button("Approve", type="primary", icon=":material/check:", key=f"conf_ok_{n}"):
                flash(*decide(k, APPROVED, actor.email, note))
                st.rerun()
            if act.button("Decline", icon=":material/close:", key=f"conf_no_{n}"):
                flash(*decide(k, DECLINED, actor.email, note))
                st.rerun()

    done = [r for r in rows if r.get("status") in (APPROVED, DECLINED) and r not in unsent]
    if done:
        with st.expander(f"Decided · {len(done)}"):
            st.dataframe(pd.DataFrame([{"Name": r["name"], "Conference": r["conference"], "Status": r["status"],
                                        "By": r["decided_by"], "At": r["decided_at"], "Navan sent": r["navan_sent_at"],
                                        "Note": r["notes"]} for r in done]), hide_index=True)
