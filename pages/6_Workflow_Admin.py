"""Workflow admin: unified queue, event assignments and routing, notification delivery, audit."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

import pandas as pd
import streamlit as st

from workflow.models import (
    ACTIVE, DEAD, DELEGATE, INVITED, OWNER, PENDING, PROGRAM_ROLES, REMOVED, RETRY, SPEAKER, SUGGESTED,
    UNCERTAIN, UNROUTABLE, VENDOR,
)
from workflow.runtime import form_token, get_actor, get_service
from workflow.service import EVENT_STATUSES
from workflow.ui import md, run_action, show_flash

st.set_page_config(page_title="Workflow admin - Community Voices", layout="wide")

from utils.identity import require_admin
from workflow.runtime import OVERRIDE
if "actor" not in OVERRIDE:
    require_admin()                         # checked here, not only in navigation
actor = get_actor()
if actor is None or not actor.is_admin:
    st.error("This area is restricted to program administrators.")
    st.stop()
svc = get_service()
st.title("Workflow admin")
show_flash()
from utils import email_health
email_health.render(actor)          # shown even when the workflow store isn't configured

# Areas. The first three read the Google Sheet, so they work before the workflow store is provisioned.
AREAS = {"needs": ":material/priority_high: Needs you", "recaps": ":material/summarize: Recaps",
         "content": ":material/fact_check: Content checks", "workflow": ":material/inbox: Workflow"}
if "admin_area" not in st.session_state:
    _q = st.query_params.get("tab", "needs")
    st.session_state["admin_area"] = _q if _q in AREAS else "needs"
area = st.radio("Area", list(AREAS), format_func=AREAS.get, key="admin_area", horizontal=True,
                label_visibility="collapsed",
                on_change=lambda: st.query_params.update(tab=st.session_state["admin_area"]))
st.divider()
if area != "workflow":
    from utils import ops_admin
    if area == "needs":
        ops_admin.render_needs_you(actor, svc)
    elif area == "recaps":
        ops_admin.render_recaps(actor)
    else:
        ops_admin.render_content(actor, svc)
    st.stop()

if svc is None:
    st.warning("Workflow store is not configured. Add the `[connections.cv_workflow]` secret (service user).")
    st.stop()

if not svc.config.delivery_enabled:
    st.info("Automatic delivery is OFF. Notifications are recorded in the outbox but not sent.",
            icon=":material/notifications_off:")

q = svc.admin_queue(actor)
events = q["events"]
ev_name = lambda eid: md(events[eid].name if eid in events else eid)  # noqa: E731

attention = q["notifications"]
problems = [n for n in attention if n.status in (DEAD, UNROUTABLE, UNCERTAIN)]
c = st.columns(4)
c[0].metric("Awaiting review", len(q["to_review"]))
c[1].metric("Outstanding items", len(q["outstanding"]))
c[2].metric("Events without owner", len(q["no_owner"]))
c[3].metric("Notification problems", len(problems))

tab_q, tab_ev, tab_n, tab_a = st.tabs([":material/inbox: Queue", ":material/groups: Events and people",
                                       ":material/notifications: Notifications", ":material/history: Audit"])

with tab_q:
    st.markdown("#### Awaiting review")
    if q["to_review"]:
        for i in q["to_review"]:
            row = st.container(horizontal=True, vertical_alignment="center")
            row.markdown(f"**{ev_name(i.event_id)}** · {i.title} · v{i.current_version} · {i.party.title()}"
                         f" · [Review](/workspace?event={i.event_id}&item={i.item_id})")
    else:
        st.caption("Nothing to review.")
    st.markdown("#### Outstanding items")
    if q["outstanding"]:
        st.dataframe(pd.DataFrame([{"Event": ev_name(i.event_id), "Item": i.title, "Party": i.party.title(),
                                    "Status": i.status.replace("_", " ").title(),
                                    "Due": i.due_date} for i in sorted(q["outstanding"],
                                                                      key=lambda i: i.due_date or date.max)]),
                     hide_index=True)
    else:
        st.caption("No outstanding items.")
    if q["no_owner"]:
        st.markdown("#### Events without a program owner")
        st.caption("Notifications for these events are held as unroutable until you assign an owner.")
        for e in q["no_owner"]:
            st.markdown(f"- **{md(e.name)}** ({e.status.title()}) · `{e.event_id}`")

with tab_ev:
    with st.expander("Create event"):
        with st.form("create_event"):
            name = st.text_input("Event name")
            c1, c2 = st.columns(2)
            start = c1.date_input("Start date", value=None)
            city = c2.text_input("City")
            go = st.form_submit_button("Create", type="primary")
        if go:
            run_action(svc, lambda: svc.create_event(actor, name=name, start_date=start, city=city,
                                                     token=form_token("create_event")), "create_event")
    if not events:
        st.caption("No workflow events yet. Create one or run the backfill script.")
    else:
        ids = sorted(events, key=lambda e: (events[e].status != "PROPOSED", events[e].name))
        eid = st.selectbox("Event", ids, format_func=lambda e: f"{events[e].name} ({events[e].status.title()})",
                           key="adm_event")
        event = events[eid]
        view = svc.event_view(actor, eid)
        row = st.container(horizontal=True, vertical_alignment="bottom")
        new_status = row.selectbox("Event status", EVENT_STATUSES, index=EVENT_STATUSES.index(event.status),
                                   key=f"st_{eid}")
        if row.button("Update status") and new_status != event.status:
            run_action(svc, lambda: svc.set_event_status(actor, eid, new_status, form_token(f"status_{eid}")),
                       f"status_{eid}")
        row.markdown(f"[Open workspace](/workspace?event={eid})")

        st.markdown("#### People and routing")
        people = [m for m in view.members if m.status != REMOVED]
        if people:
            st.dataframe(pd.DataFrame([{
                "Role": m.role.title(), "Name": m.display_name, "Email": m.email, "Status": m.status.title(),
                "Signed in": "Yes" if m.subject else "No", "Slack": m.slack_user_id,
                "Shared with vendor": "Yes" if m.shared_with_vendor else ""} for m in people]), hide_index=True)
        if any(m.status == SUGGESTED for m in people):
            st.caption("Suggested rows came from legacy sheet emails and grant nothing until you invite them.")

        with st.expander("Assign a person", expanded=not people):
            with st.form(f"invite_{eid}"):
                c1, c2 = st.columns(2)
                role = c1.selectbox("Role", [SPEAKER, VENDOR, OWNER, DELEGATE], format_func=str.title)
                email = c2.text_input("Email (they must sign in with this Google account)")
                dname = c1.text_input("Display name")
                slack = c2.text_input("Slack user ID (owners and delegates only)")
                due = c1.date_input("Default deadline for their items", value=None)
                go = st.form_submit_button("Assign and notify", type="primary")
            if go:
                tn = f"invite_{eid}"
                run_action(svc, lambda: svc.invite(actor, eid, role=role, email=email, display_name=dname,
                                                   slack_user_id=slack, due_date=due, token=form_token(tn)), tn)

        if people:
            with st.expander("Correct routing, confirm, or remove"):
                mid = st.selectbox("Person", [m.member_id for m in people],
                                   format_func=lambda x: next(f"{m.role.title()}: {m.display_name or m.email}"
                                                              for m in people if m.member_id == x),
                                   key=f"pick_{eid}")
                m = next(p for p in people if p.member_id == mid)
                with st.form(f"route_{mid}"):
                    email2 = st.text_input("Notification email", value=m.email)
                    dname2 = st.text_input("Display name", value=m.display_name)
                    slack2 = st.text_input("Slack user ID", value=m.slack_user_id,
                                           disabled=m.role not in PROGRAM_ROLES)
                    save = st.form_submit_button("Save routing")
                if save:
                    tn = f"route_{mid}"
                    run_action(svc, lambda: svc.update_routing(actor, mid, email=email2, display_name=dname2,
                                                               slack_user_id=slack2 if m.role in PROGRAM_ROLES else "",
                                                               token=form_token(tn)), tn)
                b = st.container(horizontal=True)
                if m.role == SPEAKER and m.status == ACTIVE and not m.shared_with_vendor:
                    if b.button("Confirm speaker to vendor", key=f"conf_{mid}"):
                        run_action(svc, lambda: svc.confirm_speaker(actor, mid))
                if b.button("Remove from event", key=f"rm_{mid}"):
                    run_action(svc, lambda: svc.remove_member(actor, mid, form_token(f"rm_{mid}")), f"rm_{mid}")

        unroutable = [n for n in attention if n.event_id == eid and n.status == UNROUTABLE]
        if unroutable and any(m.role in PROGRAM_ROLES and m.status in (ACTIVE, INVITED) for m in people):
            if st.button(f"Re-route {len(unroutable)} held notification(s) to the current owner", type="primary"):
                def reroute_all():
                    last = None
                    for n in unroutable:
                        last = svc.reroute(actor, n.notification_id, form_token(f"rr_{n.notification_id}"))
                    return last
                run_action(svc, reroute_all)

with tab_n:
    row = st.container(horizontal=True)
    if row.button("Send due notifications now", icon=":material/send:", disabled=not svc.config.delivery_enabled):
        s = svc.dispatch(limit=50)
        st.session_state["_wf_flash"] = ("info", f"Sent {s['sent']}, retrying {s['retry']}, failed {s['dead']}, "
                                                 f"uncertain {s['uncertain']}.")
        st.rerun()
    status_filter = row.pills("Show", [UNROUTABLE, DEAD, UNCERTAIN, RETRY, PENDING],
                              default=[UNROUTABLE, DEAD, UNCERTAIN, RETRY], selection_mode="multi",
                              format_func=str.title, key="n_filter")
    shown = [n for n in attention if n.status in (status_filter or [])]
    if not shown:
        st.caption("No notifications need attention.")
    for n in shown:
        with st.container(border=True):
            top = st.container(horizontal=True, vertical_alignment="center")
            top.markdown(f"**{n.status.title()}** · {ev_name(n.event_id)} · {n.rule.replace('_', ' ')} · "
                         f"{n.channel.title()} {md(n.address)}")
            st.caption(f"{md(n.subject)} · attempts {n.attempts}/{n.max_attempts}"
                       + (f" · last error: {n.last_error}" if n.last_error else "")
                       + (f" · next try {n.next_attempt_at:%b %d %H:%M} UTC" if n.status == RETRY else ""))
            act = st.container(horizontal=True)
            if n.status in (DEAD, UNCERTAIN, RETRY):
                label = "Send again (may duplicate)" if n.status == UNCERTAIN else "Retry"
                if act.button(label, key=f"retry_{n.notification_id}"):
                    tn = f"retry_{n.notification_id}"
                    run_action(svc, lambda n=n, tn=tn: svc.retry_notification(actor, n.notification_id,
                                                                              form_token(tn)), tn)
            if n.status == UNROUTABLE:
                if act.button("Re-route", key=f"rr_{n.notification_id}"):
                    tn = f"rr_{n.notification_id}"
                    run_action(svc, lambda n=n, tn=tn: svc.reroute(actor, n.notification_id, form_token(tn)), tn)
            if act.button("Dismiss", key=f"cx_{n.notification_id}"):
                tn = f"cx_{n.notification_id}"
                run_action(svc, lambda n=n, tn=tn: svc.cancel_notification(actor, n.notification_id,
                                                                           form_token(tn)), tn)

with tab_a:
    audit = svc.audit_log(actor, limit=200)
    if audit:
        st.dataframe(pd.DataFrame([{"When (UTC)": a.created_at, "Event": ev_name(a.event_id), "Action": a.action,
                                    "By": a.actor_role, "From": a.from_status, "To": a.to_status, "Note": a.note}
                                   for a in audit]), hide_index=True)
    else:
        st.caption("No activity yet.")
