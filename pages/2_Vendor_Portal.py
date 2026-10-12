"""Vendor & Event Organizer Portal.

Public landing page for signed-out visitors; after Google sign-in, a guided flow to register
an event, a validated bulk upload, and a "My events" view scoped to the verified email.
Submissions go through utils.vendor_backend (workflow service, or Google Sheets fallback).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pandas as pd
import streamlit as st

from utils import email_otp as otp
from utils import vendor_backend as vb
from utils import vendor_validation as vv
from utils import ui_components as ui
from utils.styles import inject_css
from workflow.runtime import form_token, get_actor, rotate_token
from workflow.ui import md

st.set_page_config(page_title="Vendor Portal — Community Voices", page_icon="🏟️", layout="centered")
inject_css()

STEPS = ["About you", "Event", "Speaker request", "Review & submit"]
VIEWS = ["Register an event", "Bulk upload", "My events", "Help"]
LABEL = {k: v[0] + (" *" if k in vv.REQUIRED else "") for k, v in vv.FIELDS.items()}
HELP = {
    "event_website": "Full link, e.g. https://yourevent.com",
    "cfp_link": "Where speakers submit talks, if you run a CFP",
    "cfp_deadline": "Must be on or before the event start date",
    "speaker_topic": "What should a Snowflake community speaker talk about? Include audience level if you can.",
}
def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def hero(title, body):
    ui.hero("Vendor & Event Organizer Portal", title, body, theme="purple")


# ══════════════════════════════════════════════════════════════════════════════
# SIGNED OUT: public landing page
# ══════════════════════════════════════════════════════════════════════════════
actor = get_actor()
logged_in = bool(getattr(st.user, "is_logged_in", False))

if actor is None or not actor.email:
    hero("Bring a Snowflake community speaker to your event",
         "Register your conference, meetup, or university event. Once approved, qualified Snowflake "
         "community speakers can be matched to it.")
    if logged_in and actor is None:
        st.warning("Your Google account doesn't have a verified email address, so we can't link events to it. "
                   "Sign out, then sign in with your email instead.", icon=":material/mark_email_unread:")
        if st.button("Sign out", icon=":material/logout:"):
            st.logout()
    elif actor is not None and not actor.email:
        st.info("You're unlocked as the program team. Sign in with Google to see the vendor experience.")
    st.subheader("How it works")
    ui.step_cards([("Sign in", "Enter your email and we'll send you a code."),
                   ("Register your event", "About 5 minutes. One event, or many at once by spreadsheet."),
                   ("Get matched", "We review within 5 business days and connect you with a speaker.")])
    if not logged_in:
        ui.otp_sign_in()
        if _secret("auth"):
            st.caption("Have a Google account set up for this program?")
            if st.button("Sign in with Google", icon=":material/login:", key="vnd_login"):
                st.login()
    st.subheader("Questions")
    ui.help_link("organizers", "Help for event organizers: FAQ, review times, editing")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SIGNED IN
# ══════════════════════════════════════════════════════════════════════════════
ss = st.session_state
ss.setdefault("vnd_step", 0)
ss.setdefault("vnd_draft", {})
ss.setdefault("vnd_errors", {})
ss.setdefault("vnd_view", VIEWS[0])

hero("Register your event", "Tell us about your event and the kind of speaker you're looking for.")

if actor.is_admin:
    m = vb.mode()
    if m == vb.WORKFLOW:
        st.info("**Admin · Mode: Workflow store.** Submissions are recorded in Snowflake and appear in Workflow admin.",
                icon=":material/database:")
    else:
        st.warning("**Admin · Mode: Google Sheets fallback.** `[connections.cv_workflow]` is not configured, so "
                   "submissions go to the Events / Speaker_Requests tabs and appear in the Admin Portal.",
                   icon=":material/table:")

top_l, top_r = st.columns([3, 2], vertical_alignment="center")
top_l.caption(f"Signed in as {md(actor.email)}")
with top_r:
    try:
        st.page_link("pages/5_Workspace.py", label="Event workspace (materials)", icon=":material/folder:")
    except Exception:      # page not registered in this navigation (e.g. page run standalone)
        st.markdown("[Event workspace (materials)](/workspace)")


def _widget_key(f):
    return f"vnd_f_{f}"


def _load_into_widgets(draft, overwrite=False):
    """Prefill widgets from a draft (used for Edit, and when a step is shown again)."""
    for f in vv.FIELDS:
        k = _widget_key(f)
        if k in ss and not overwrite:
            continue
        v = draft.get(f, "")
        if f in vv.DATE_FIELDS:
            ss[k] = vv.to_date(v)
        elif f == "event_format":
            ss[k] = v if v in vv.FORMATS else None
        else:
            ss[k] = v or ""


def _collect(fields):
    for f in fields:
        v = ss.get(_widget_key(f))
        ss.vnd_draft[f] = v.isoformat() if isinstance(v, date) else (v or "")


def _reset_form():
    ss.vnd_step, ss.vnd_draft, ss.vnd_errors = 0, {}, {}
    ss.pop("vnd_edit_ref", None)
    ss.pop("vnd_done", None)
    for f in vv.FIELDS:
        ss.pop(_widget_key(f), None)


def _go(step):
    ss.vnd_step = step


def _next():
    fields = vv.STEP_FIELDS[ss.vnd_step + 1]
    _collect(fields)
    errs = vv.validate(ss.vnd_draft, fields)
    ss.vnd_errors = errs
    if not errs:
        ss.vnd_step += 1


def _back():
    _collect(vv.STEP_FIELDS.get(ss.vnd_step + 1, []))     # keep what was typed on this step
    ss.vnd_errors = {}
    ss.vnd_step = max(0, ss.vnd_step - 1)


def _start_edit(ev):
    _reset_form()
    ss.vnd_draft = dict(ev.details)
    ss.vnd_edit_ref = ev.ref
    _load_into_widgets(ss.vnd_draft, overwrite=True)
    ss.vnd_view = VIEWS[0]


def _start_new():
    _reset_form()
    ss.vnd_view = VIEWS[0]


def field(f, kind="text", **kw):
    k = _widget_key(f)
    if k not in ss and ss.vnd_draft:
        _load_into_widgets(ss.vnd_draft)     # widget state is dropped when a step isn't shown
    label, help_ = LABEL[f], HELP.get(f)
    if kind == "text":
        st.text_input(label, key=k, help=help_, max_chars=vv.FIELDS[f][1], **kw)
    elif kind == "area":
        st.text_area(label, key=k, help=help_, max_chars=vv.FIELDS[f][1], height=110, **kw)
    elif kind == "date":
        if k not in ss:
            ss[k] = None
        st.date_input(label, key=k, help=help_, format="YYYY-MM-DD", **kw)
    elif kind == "select":
        if k not in ss:
            ss[k] = None
        st.selectbox(label, vv.FORMATS, key=k, placeholder="Choose a format", **kw)
    if f in ss.vnd_errors:
        st.error(ss.vnd_errors[f], icon=":material/error:")


view = st.radio("Section", VIEWS, key="vnd_view", horizontal=True, label_visibility="collapsed")
st.divider()

# ── Register an event (guided flow) ────────────────────────────────────────────
if view == "Register an event":
    done = ss.get("vnd_done")
    if done:
        st.success(done["message"], icon=":material/task_alt:")
        st.markdown("**Your reference ID** — save it for any follow-up emails:")
        st.code(done["ref"], language=None)
        st.markdown("#### What happens next")
        st.markdown(
            "1. **Now** — your event is recorded as *Pending*. You can still edit it from **My events**.\n"
            "2. **Within 5 business days** — the Community Voices team reviews it.\n"
            "3. **If approved** — it's listed for qualified community speakers.\n"
            "4. **Speaker matched** — we email you the speaker's details and next steps.\n"
            "5. **Before the event** — share logistics and materials in your event workspace."
        )
        c1, c2 = st.columns(2)
        c1.button("Register another event", on_click=_start_new, width="stretch", key="vnd_another")
        c2.button("View my events", on_click=lambda: ss.update(vnd_view="My events"), width="stretch",
                  key="vnd_view_mine")
    else:
        editing = ss.get("vnd_edit_ref")
        if editing:
            st.info(f"Editing pending event **{md(editing)}**.", icon=":material/edit:")
        step = ss.vnd_step
        st.progress((step + 1) / len(STEPS), text=f"Step {step + 1} of {len(STEPS)} · {STEPS[step]}")
        st.caption("Fields marked * are required.")

        if step == 0:
            st.text_input("Verified email", value=actor.email, disabled=True, key="vnd_email_ro",
                          help="Comes from your Google sign-in. We'll contact you here.")
            field("organizer_name")
            field("organizer_org")
        elif step == 1:
            field("event_name")
            c1, c2 = st.columns(2)
            with c1:
                field("event_start", "date", min_value=date.today())
            with c2:
                field("event_end", "date", min_value=date.today())
            c1, c2 = st.columns(2)
            with c1:
                field("event_city")
            with c2:
                field("event_country")
            field("event_format", "select")
            field("event_website", placeholder="https://")
            field("expected_audience", placeholder="e.g. 300")
            field("event_description", "area")
        elif step == 2:
            field("speaker_topic", "area")
            field("cfp_link", placeholder="https://")
            field("cfp_deadline", "date")
        else:
            d = ss.vnd_draft
            for s_idx, title in ((1, "Event"), (2, "Speaker request"), (0, "About you")):
                with st.container(border=True):
                    h1, h2 = st.columns([4, 1], vertical_alignment="center")
                    h1.markdown(f"**{title}**")
                    h2.button("Edit", key=f"vnd_edit_step_{s_idx}", on_click=_go, args=(s_idx,))
                    fields = vv.STEP_FIELDS[s_idx + 1]
                    if s_idx == 0:
                        st.markdown(f"Email: {md(actor.email)}")
                    for f in fields:
                        if d.get(f):
                            st.markdown(f"{vv.FIELDS[f][0]}: {md(d[f])}")
            errs = vv.validate(d)
            if errs:
                st.error("Please fix: " + " ".join(errs.values()))

        nav_l, nav_r = st.columns(2)
        if step > 0:
            nav_l.button("Back", on_click=_back, width="stretch", key="vnd_back", icon=":material/arrow_back:")
        else:
            nav_l.button("Cancel" if editing else "Clear form", on_click=_start_new, width="stretch",
                         key="vnd_clear")
        if step < 3:
            nav_r.button("Next", type="primary", on_click=_next, width="stretch", key="vnd_next",
                         icon=":material/arrow_forward:")
        else:
            label = "Save changes" if editing else "Submit event"
            if nav_r.button(label, type="primary", width="stretch", key="vnd_submit",
                            disabled=bool(vv.validate(ss.vnd_draft))):
                token_name = f"vendor_edit_{editing}" if editing else "vendor_event"
                with st.spinner("Saving…"):
                    if editing:
                        out = vb.update_pending(actor, editing, ss.vnd_draft, form_token(token_name))
                    else:
                        out = vb.submit_event(actor, ss.vnd_draft, form_token(token_name))
                if out.ok:
                    rotate_token(token_name)
                    msg = "Changes saved." if editing else "Event submitted — thank you!"
                    _reset_form()
                    ss.vnd_done = {"ref": out.ref, "message": msg}
                    st.rerun()
                else:
                    st.error(out.message, icon=":material/error:")

# ── Bulk upload ────────────────────────────────────────────────────────────────
elif view == "Bulk upload":
    st.markdown("#### Upload several events at once")
    ui.help_link("bulk", "Column guide and tips")
    st.markdown("1. Download the template (it includes one example row — replace it).\n"
                "2. Add one row per event. Dates use `YYYY-MM-DD`.\n"
                "3. Upload the file. We check every row before anything is submitted.")
    tpl = pd.DataFrame([vv.EXAMPLE_ROW], columns=vv.BULK_COLUMNS)
    st.download_button("Download template (CSV)", tpl.to_csv(index=False), file_name="cv_events_template.csv",
                       mime="text/csv", icon=":material/download:", key="vnd_tpl")
    with st.expander("Column guide"):
        st.dataframe(pd.DataFrame([{"column": c, "required": "Yes" if c in vv.REQUIRED else "",
                                    "notes": ", ".join(vv.FORMATS) if c == "event_format" else ""}
                                   for c in vv.BULK_COLUMNS]), hide_index=True, width="stretch")

    if ss.get("vnd_bulk_results"):
        res = pd.DataFrame(ss.vnd_bulk_results)
        n_ok = int((res["result"] == "Submitted").sum())
        st.success(f"{n_ok} event(s) submitted. Reference IDs are in the table below.", icon=":material/task_alt:")
        st.dataframe(res, hide_index=True, width="stretch")
        if st.button("Upload another file", key="vnd_bulk_reset"):
            ss.pop("vnd_bulk_results", None)
            ss.pop("vnd_upload", None)
            rotate_token("vendor_bulk")
            st.rerun()
    else:
        up = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx"], key="vnd_upload")
        if up is not None:
            try:
                df = vv.read_upload(up.name, up)
            except Exception:
                df = None
                st.error("We couldn't read that file. Save it as CSV or .xlsx using the template and try again.")
            if df is not None:
                if df.empty:
                    st.warning("That file has no rows.")
                else:
                    valid, errors, missing = vv.validate_bulk(df)
                    st.markdown(f"**Preview — {len(df)} row(s)**")
                    st.dataframe(df, hide_index=True, width="stretch")
                    if missing:
                        st.error("Missing required columns: " + ", ".join(missing) +
                                 ". Download the template to see the expected headers.")
                    else:
                        if not errors.empty:
                            st.error(f"{errors['row'].nunique()} row(s) need fixing. Row numbers match your file "
                                     "(row 1 is the header).", icon=":material/error:")
                            st.dataframe(errors, hide_index=True, width="stretch")
                        if valid:
                            label = (f"Submit {len(valid)} event(s)" if errors.empty else
                                     f"Submit {len(valid)} valid row(s), skip {errors['row'].nunique()}")
                            if st.button(label, type="primary", width="stretch", key="vnd_bulk_submit"):
                                with st.spinner("Submitting…"):
                                    ss.vnd_bulk_results = vb.submit_bulk(actor, valid, form_token("vendor_bulk"))
                                st.rerun()

# ── My events ──────────────────────────────────────────────────────────────────
elif view == "My events":
    try:
        mine = vb.list_my_events(actor)
    except RuntimeError as exc:
        mine = None
        st.error(str(exc), icon=":material/cloud_off:")
        st.button("Try again", key="vnd_mine_retry")
    if mine is not None:
        if not mine:
            st.info("You haven't registered any events with this account yet.")
            st.button("Register an event", type="primary", on_click=_start_new, key="vnd_mine_new")
        else:
            st.caption(f"{len(mine)} event(s) registered with {md(actor.email)}")
            for ev in mine:
                d = ev.details
                with st.container(border=True):
                    h1, h2 = st.columns([3, 1], vertical_alignment="center")
                    h1.markdown(f"**{md(d.get('event_name'))}**")
                    with h2:
                        ui.status_badge(ev.status)
                    where = ", ".join(x for x in (d.get("event_city"), d.get("event_country")) if x)
                    when = d.get("event_start", "") + (f" → {d['event_end']}" if d.get("event_end") else "")
                    st.caption(f":material/location_on: {md(where)}  ·  :material/calendar_today: {md(when)}  ·  "
                               f"Ref `{md(ev.ref)}`")
                    if d.get("speaker_topic"):
                        st.markdown(f"**Speaker topic:** {md(d['speaker_topic'])}")
                    if ev.matched_speakers:
                        st.markdown("**Matched speakers:** " + ", ".join(md(s) for s in ev.matched_speakers))
                    elif ev.status == "Approved":
                        st.caption("Approved — we're matching a speaker.")
                    if ev.admin_notes:
                        st.markdown(f"**Note from the team:** {md(ev.admin_notes)}")
                    if ev.editable:
                        st.button("Edit", key=f"vnd_edit_{ev.ref}", on_click=_start_edit, args=(ev,),
                                  icon=":material/edit:")

# ── Help ───────────────────────────────────────────────────────────────────────
else:
    st.markdown("#### Need a hand?")
    st.markdown("Step-by-step instructions, the FAQ, and contact details are on the Help page.")
    ui.help_link("organizers", "Help for event organizers")
    ui.help_link("bulk", "Bulk upload template and column guide")
    ui.help_link("signin", "Signing in with an email code")
    if st.button("Sign out", icon=":material/logout:", key="vnd_logout"):
        if logged_in:
            st.logout()
        else:
            otp.sign_out()
            st.rerun()
