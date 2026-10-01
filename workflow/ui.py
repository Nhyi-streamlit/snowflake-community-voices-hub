"""Shared Streamlit rendering for workflow items. All data comes from WorkflowService calls,
which enforce authorization; nothing here decides access on its own.
"""
from __future__ import annotations

import json
import re
from datetime import date

import streamlit as st

from workflow import rules
from workflow.models import (
    APPROVED, CHANGES_REQUESTED, MISSING, SPEAKER, SUBMITTED, InvalidAction, NotAuthorized,
)
from workflow.runtime import after_action, form_token

STATUS_BADGE = {
    MISSING: ":gray-badge[:material/radio_button_unchecked: Missing]",
    SUBMITTED: ":blue-badge[:material/hourglass_top: Awaiting review]",
    CHANGES_REQUESTED: ":orange-badge[:material/edit_note: Changes requested]",
    APPROVED: ":green-badge[:material/check_circle: Approved]",
}

# Text fields collected for each text item type: (key, label, multiline)
TEXT_FIELDS = {
    "profile": [("name", "Full name", False), ("title", "Job title", False), ("company", "Company", False),
                ("links", "LinkedIn / website", False)],
    "bio": [("bio", "Bio (about 100 words)", True)],
    "talk_details": [("title", "Talk title", False), ("abstract", "Abstract", True),
                     ("level", "Audience level", False)],
    "availability": [("availability", "Dates and times you are available", True)],
    "event_details": [("description", "Event description", True), ("website", "Event website", False),
                      ("audience", "Expected audience", False)],
    "logistics": [("logistics", "Venue, AV, schedule, arrival instructions", True)],
    "speaker_request": [("request", "Topic, format, and session length you need", True)],
}


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md(text) -> str:
    """Escape user-supplied text before it is rendered as Markdown (links, images, directives)."""
    return _MD_SPECIAL.sub(r"\\\1", str(text or ""))


def deadline_text(item) -> str:
    if not item.due_date:
        return ""
    days = (item.due_date - date.today()).days
    if item.status != APPROVED and days < 0:
        return f":red[Overdue since {item.due_date:%b %d}]"
    return f"Due {item.due_date:%b %d, %Y}"


def flash(msg: str, kind: str = "success"):
    st.session_state["_wf_flash"] = (kind, msg)


def show_flash():
    if "_wf_flash" in st.session_state:
        kind, msg = st.session_state.pop("_wf_flash")
        getattr(st, kind)(msg)


def run_action(svc, fn, token_name=None):
    """Call a service action and turn the outcome into a user-facing message."""
    try:
        result = fn()
    except (NotAuthorized, InvalidAction) as exc:
        st.error(str(exc))
        return None
    except Exception:
        st.error("Something went wrong and nothing was saved. Please try again.")
        return None
    flash(after_action(svc, result, token_name), "success" if result.status == "recorded" else "info")
    st.rerun()


def _latest_text(svc, actor, item) -> dict:
    if not item.current_version:
        return {}
    try:
        versions, _ = svc.history(actor, item.item_id)
    except NotAuthorized:
        return {}
    return json.loads(versions[-1].text_json or "{}") if versions else {}


def render_item(svc, actor, view, item):
    _, kind, exts = rules.item_spec(item)
    members = view.members
    can_submit = item.item_id in view.submittable
    with st.container(border=True):
        top = st.container(horizontal=True, vertical_alignment="center")
        top.markdown(f"**{item.title}**")
        top.markdown(STATUS_BADGE.get(item.status, item.status))
        if item.due_date:
            top.markdown(deadline_text(item))
        if view.is_reviewer and item.party == SPEAKER:
            owner = next((m for m in members if m.member_id == item.assignee_member_id), None)
            if owner:
                st.caption(f"Speaker: {md(owner.display_name or owner.email)}")

        if can_submit:
            label = "Submit" if item.status == MISSING else "Update"
            with st.expander(f"{label} {item.title.lower()}", expanded=item.status in (MISSING, CHANGES_REQUESTED)):
                tname = f"item_{item.item_id}"
                with st.form(f"form_{item.item_id}", clear_on_submit=False, border=False):
                    text, upload = {}, None
                    if kind == "text":
                        prev = _latest_text(svc, actor, item)
                        for key, lbl, multi in TEXT_FIELDS.get(item.item_type, []):
                            widget = st.text_area if multi else st.text_input
                            text[key] = widget(lbl, value=prev.get(key, ""), key=f"{item.item_id}_{key}")
                    else:
                        f = st.file_uploader(f"Upload ({', '.join(exts)}; max 25 MB)", type=exts,
                                             key=f"{item.item_id}_file")
                        if f is not None:
                            upload = (f.name, f.getvalue())
                    if item.current_version:
                        st.caption("Earlier versions are kept in your history; nothing is overwritten.")
                    sent = st.form_submit_button(label, type="primary")
                if sent:
                    run_action(svc, lambda: svc.submit_item(actor, item.item_id, text=text, upload=upload,
                                                            token=form_token(tname)), tname)

        if view.is_reviewer and item.status == SUBMITTED:
            with st.expander(f"Review version {item.current_version}", expanded=True):
                with st.form(f"review_{item.item_id}", border=False):
                    note = st.text_area("Note to submitter (required to request changes)", key=f"rn_{item.item_id}")
                    row = st.container(horizontal=True)
                    ok = row.form_submit_button("Approve", type="primary", icon=":material/check:")
                    chg = row.form_submit_button("Request changes", icon=":material/edit_note:")
                if ok or chg:
                    run_action(svc, lambda: svc.review_item(actor, item.item_id, version=item.current_version,
                                                            approve=bool(ok), note=note))

        if view.is_reviewer:
            with st.expander("Deadline and sharing"):
                with st.form(f"settings_{item.item_id}", border=False):
                    due = st.date_input("Deadline", value=item.due_date, key=f"due_{item.item_id}")
                    vv = sv = False
                    if item.party == SPEAKER:
                        vv = st.toggle("Vendors may see the approved version", value=item.vendor_visible,
                                       key=f"vv_{item.item_id}")
                    else:
                        sv = st.toggle("Assigned speakers must see and act on this", value=item.speaker_action,
                                       key=f"sa_{item.item_id}")
                    save = st.form_submit_button("Save")
                if save:
                    tname = f"settings_{item.item_id}"
                    run_action(svc, lambda: svc.update_item_settings(
                        actor, item.item_id, due_date=due, vendor_visible=vv, speaker_action=sv,
                        token=form_token(tname)), tname)

        if item.current_version:
            with st.expander("History"):
                render_history(svc, actor, item)


def render_history(svc, actor, item):
    try:
        versions, audit = svc.history(actor, item.item_id)
    except NotAuthorized:
        st.caption("Not available.")
        return
    for v in reversed(versions):
        row = st.container(horizontal=True, vertical_alignment="center")
        who = "speaker" if v.submitted_role == SPEAKER else v.submitted_role.lower()
        row.markdown(f"**v{v.version}** · {v.submitted_at:%b %d, %Y %H:%M} UTC · by {who}"
                     + (" · :green[approved]" if v.version == item.approved_version else ""))
        if v.file_path:
            def fetch(vn=v.version):
                return svc.download(actor, item.item_id, vn)[1]   # re-authorized at click time
            row.download_button(f"Download {md(v.file_name)}", data=fetch, file_name=v.file_name,
                                key=f"dl_{item.item_id}_{v.version}", on_click="ignore",
                                icon=":material/download:")
        else:
            with row.popover("View"):
                for k, val in json.loads(v.text_json or "{}").items():
                    st.markdown(f"**{k.replace('_', ' ').title()}**")
                    st.text(val)
    notes = [a for a in audit if a.action in ("CHANGES_REQUESTED", "ITEM_APPROVED") and a.note]
    for a in notes:
        st.caption(f"{a.created_at:%b %d} · {a.action.replace('_', ' ').lower()}: {md(a.note)}")
