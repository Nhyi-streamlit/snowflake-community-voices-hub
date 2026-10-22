"""Speaker → program team feedback: saved to the hub tab Program_Feedback and emailed to Aba.

Open to everyone; name and email are optional (anonymous allowed). Tests use ops_store.OVERRIDE["sheets"] and a fake
GmailClient as utils.sheets._gmail_client.
"""
from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from utils import ops_store as ops

TAB = "Program_Feedback"
TO = "aba.micah@snowflake.com"
TOPICS = ["Overall program", "Finding speaking opportunities", "Talk prep & resources", "Travel & reimbursement",
          "Communication from the team", "Speaker Portal", "Other"]
MAX_LEN = 4000


def submit(*, name: str, email: str, community: str, event: str, topic: str, rating: int, went_well: str,
           improve: str, follow_up: bool) -> tuple[bool, str, str]:
    """Save and notify. Returns (saved, feedback_id, email_reason); email_reason is "" when the email went out."""
    clip = lambda s: str(s or "").strip()[:MAX_LEN]  # noqa: E731
    if not (clip(went_well) or clip(improve)):
        raise ValueError("Tell us what went well or what we could improve.")
    fid = f"PF-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rec = {"feedback_id": fid, "submitted_at": now, "name": clip(name), "email": clip(email),
           "community": clip(community), "event": clip(event), "topic": topic if topic in TOPICS else "Other",
           "rating": str(int(rating)), "went_well": clip(went_well), "improve": clip(improve),
           "follow_up_ok": "yes" if follow_up and clip(email) else "no"}
    if not ops.sheets().append(TAB, [rec[c] for c in ops.HEADERS[TAB]]):
        return False, fid, ""
    from utils.sheets import send_gmail_result
    who = rec["name"] or "Anonymous speaker"
    e = lambda v: html.escape(v) or "—"  # noqa: E731
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555;vertical-align:top'><b>{k}</b></td>"
                   f"<td style='white-space:pre-wrap'>{e(rec[c])}</td></tr>"
                   for k, c in [("From", "name"), ("Email", "email"), ("Community", "community"), ("Event", "event"),
                                ("Topic", "topic"), ("Rating (1-5)", "rating"), ("What went well", "went_well"),
                                ("What we could improve", "improve"), ("OK to follow up", "follow_up_ok")])
    body = (f"<p>New program feedback ({fid}).</p>"
            f"<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'>{rows}</table>")
    r = send_gmail_result([TO], f"Program feedback: {rec['rating']}/5 · {rec['topic']} · {who}", body)
    return True, fid, "" if r else (getattr(r, "reason", "") or "send_failed")


def render(prefix: str = "pf") -> None:
    import streamlit as st
    st.markdown("### :material/forum: Feedback for the program team")
    st.caption("Tell the Community Voices program managers how we're doing. Name and email are optional; "
               "leave them blank to send feedback anonymously.")
    done = st.session_state.get(f"{prefix}_done")
    if done:
        st.success(f"Thank you! Your feedback ({done}) reached the program team.")
        if st.button("Send more feedback", key=f"{prefix}_again"):
            st.session_state.pop(f"{prefix}_done", None)
            st.rerun()
        return
    with st.form(f"{prefix}_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        name = c1.text_input("Your name (optional)", key=f"{prefix}_name")
        email = c2.text_input("Your email (optional)", key=f"{prefix}_email")
        community = c1.radio("You are a…", ["Data Superhero", "Streamlit Creator", "Squad member", "Other"],
                             horizontal=True, key=f"{prefix}_community")
        event = c2.text_input("Event (optional)", key=f"{prefix}_event")
        topic = st.selectbox("What is this about?", TOPICS, key=f"{prefix}_topic")
        rating = st.radio("How would you rate your experience with the program?", [1, 2, 3, 4, 5], index=3,
                          horizontal=True, format_func=lambda n: "★" * n, key=f"{prefix}_rating")
        went_well = st.text_area("What went well?", key=f"{prefix}_well", max_chars=MAX_LEN)
        improve = st.text_area("What could we improve?", key=f"{prefix}_improve", max_chars=MAX_LEN)
        follow_up = st.checkbox("The team may contact me about this feedback (needs your email)",
                                key=f"{prefix}_follow")
        go = st.form_submit_button("Send feedback", type="primary", icon=":material/send:")
    if not go:
        return
    try:
        ok, fid, reason = submit(name=name, email=email, community=community, event=event, topic=topic,
                                 rating=rating, went_well=went_well, improve=improve, follow_up=follow_up)
    except ValueError as e:
        st.warning(str(e))
        return
    if not ok:
        st.error(f"Couldn't save your feedback. Please try again or email {TO}.")
        return
    st.session_state[f"{prefix}_done"] = fid
    if reason:          # saved; the team still sees it in the sheet and Workflow admin
        import logging
        logging.getLogger(__name__).warning("program feedback email failed reason=%s", reason)
    st.rerun()
