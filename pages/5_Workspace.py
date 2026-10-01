"""My event workspace: speakers and vendors see only their own events and permitted items."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import streamlit as st

from workflow.models import APPROVED, CHANGES_REQUESTED, MISSING, PROGRAM_ROLES, SPEAKER, VENDOR, NotAuthorized
from workflow.runtime import form_token, get_actor, get_service
from workflow.ui import md, render_item, run_action, show_flash

st.set_page_config(page_title="My events - Community Voices", layout="wide")

actor = get_actor()
if actor is None:
    st.error("Sign in with a verified Google account.")
    st.stop()
svc = get_service()

st.title("My event workspace")
st.caption(f"Signed in as {md(actor.email)}")
show_flash()

if svc is None:
    st.info("The secure workflow store is not configured yet. Your program contact will let you know when "
            "your workspace opens.")
    st.stop()

if not st.session_state.get("_wf_bound"):
    svc.bind_invites(actor)     # first sign-in: accept invitations sent to this verified email
    st.session_state["_wf_bound"] = True

tab_events, tab_propose = st.tabs([":material/event: My events", ":material/add_circle: Propose an event"])

with tab_events:
    events = svc.my_events(actor)
    if not events:
        st.info("You are not assigned to any events yet. If you were invited, make sure you signed in with the "
                "same Google account the invitation was sent to. Event organizers can propose an event in the "
                "next tab.")
    else:
        labels = {e.event_id: f"{e.name} ({e.status.title()})" for e in events}
        wanted = st.query_params.get("event")
        ids = list(labels)
        selected = st.selectbox("Event", ids, index=ids.index(wanted) if wanted in ids else 0,
                                format_func=labels.get, key="ws_event")
        if selected != wanted:
            st.query_params["event"] = selected
        try:
            view = svc.event_view(actor, selected)
        except NotAuthorized as exc:
            st.error(str(exc))
            st.stop()

        ev = view.event
        roles = ", ".join(sorted(r.title() for r in view.roles)) or ("Administrator" if actor.is_admin else "")
        meta = " · ".join(x for x in [ev.city, ev.start_date.strftime("%b %d, %Y") if ev.start_date else "",
                                      f"Your role: {roles}"] if x)
        st.subheader(md(ev.name))
        st.caption(md(meta))

        mine = [i for i in view.items if i.item_id in view.submittable]
        shared = [i for i in view.items if i.item_id not in view.submittable]
        todo = [i for i in mine if i.status in (MISSING, CHANGES_REQUESTED)]
        next_due = min((i.due_date for i in todo if i.due_date), default=None)
        cols = st.columns(4)
        cols[0].metric("Your items", len(mine))
        cols[1].metric("Still needed", len(todo))
        cols[2].metric("Approved", sum(i.status == APPROVED for i in mine))
        cols[3].metric("Next deadline", next_due.strftime("%b %d") if next_due else "None")

        contacts = [m for m in view.members if m.role in PROGRAM_ROLES]
        if contacts:
            st.caption("Program contact: " + ", ".join(md(m.display_name or m.email) for m in contacts))
        speakers = [m for m in view.members if m.role == SPEAKER and m.shared_with_vendor]
        if VENDOR in view.roles and speakers:
            st.caption("Confirmed speakers: " + ", ".join(md(m.display_name or m.email) for m in speakers))

        focus = st.query_params.get("item")
        if mine:
            st.markdown("#### Your checklist")
            for item in sorted(mine, key=lambda i: (i.status == APPROVED, i.item_id != focus, i.due_date or date.max)):
                render_item(svc, actor, view, item)
        if shared:
            st.markdown("#### " + ("Submissions" if view.is_reviewer else "Shared with you"))
            for item in shared:
                render_item(svc, actor, view, item)

with tab_propose:
    st.markdown("Organizing an event and want a Community Voices speaker? Propose it here. The program team "
                "reviews proposals and will add you to the event workspace.")
    tname = "propose_event"
    with st.form("propose_form"):
        name = st.text_input("Event name")
        c1, c2 = st.columns(2)
        start = c1.date_input("Start date", value=None, min_value=date.today())
        city = c2.text_input("City")
        description = st.text_area("Event description")
        website = st.text_input("Event website")
        audience = st.text_input("Expected audience")
        go = st.form_submit_button("Submit proposal", type="primary")
    if go:
        run_action(svc, lambda: svc.propose_event(
            actor, name=name, start_date=start, city=city, token=form_token(tname),
            details={"description": description, "website": website, "audience": audience}), tname)
