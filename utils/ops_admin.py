"""Workflow admin areas for the ops automation: Recaps (approve-to-send), Needs you (triage), Content checks.

Admin authorization is checked by the page before any of these render. All sheet text shown here is
escaped with md(); nothing is sent except from an explicit button click.
"""
from __future__ import annotations

import streamlit as st

from utils import ops_store as ops
from utils import ui_components as ui
from workflow.ui import md

# Tests set OVERRIDE["slack"], OVERRIDE["email"], OVERRIDE["config"] (dict of recap settings).
OVERRIDE: dict = {}


def _secret(path, default=""):
    cur = st.secrets
    try:
        for part in path.split("."):
            cur = cur[part]
        return cur
    except Exception:
        return default


def recap_config() -> dict:
    if "config" in OVERRIDE:
        return OVERRIDE["config"]
    lst = _secret("recap.email_list", [])
    return {"slack_channel": str(_secret("recap.slack_channel", "") or ""),
            "email_list": [lst] if isinstance(lst, str) else list(lst or [])}


def _slack():
    if "slack" in OVERRIDE:
        return OVERRIDE["slack"]
    token = _secret("notify.slack.bot_token", "")
    if not token:
        return None
    from workflow.channels import SlackChannel
    return SlackChannel(bot_token=token)


def _email():
    if "email" in OVERRIDE:
        return OVERRIDE["email"]
    from utils.sheets import send_gmail_result
    return send_gmail_result


STATUS_BADGE = {ops.DRAFT: ("orange", ":material/edit_note:"), ops.APPROVED: ("blue", ":material/thumb_up:"),
                ops.SENT: ("green", ":material/send:"), ops.DISCARDED: ("gray", ":material/delete:")}


def render_recaps(actor) -> None:
    from utils import recap_publish as rp
    cfg = recap_config()
    st.markdown("#### Weekly recaps")
    st.caption("Drafted every Monday morning from the Sheets tabs. Nothing reaches the team until you approve it here.")
    recs = sorted(ops.records("Recaps"), key=lambda r: r.get("week_start", ""), reverse=True)
    if not recs:
        st.info("No recaps yet. The first draft appears after the Monday job runs "
                "(`python scripts/weekly_recap.py --publish-draft`).", icon=":material/event_note:")
        return
    flash = st.session_state.pop("recap_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])
    for r in recs[:8]:
        rid, status = r["recap_id"], r.get("status") or ops.DRAFT
        with st.container(border=True):
            h1, h2 = st.columns([4, 1], vertical_alignment="center")
            h1.markdown(f"**Week of {md(r.get('week_start'))}** → {md(r.get('week_end'))}")
            color, icon = STATUS_BADGE.get(status, ("gray", ":material/help:"))
            with h2:
                st.badge(status, color=color, icon=icon)
            if r.get("doc_url"):
                st.markdown(f"[Open the Google Doc]({r['doc_url']})" if r["doc_url"].startswith("https://")
                            else md(r["doc_url"]))
            if r.get("send_result"):
                st.caption(f"Delivery: {md(r['send_result'])}")
            with st.expander("Preview the Slack message", expanded=status == ops.DRAFT):
                st.code(r.get("slack_text", ""), language=None, wrap_lines=True)
            if status in (ops.DISCARDED,):
                continue
            b = st.container(horizontal=True)
            slack_ok = bool(cfg.get("slack_channel")) and _slack() is not None
            if b.button("Approve & send to Slack", key=f"rc_slack_{rid}", type="primary", icon=":material/send:",
                        disabled=not slack_ok or "slack:ok" in r.get("send_result", ""),
                        help=None if slack_ok else "Set [recap] slack_channel and [notify.slack] bot_token"):
                o = rp.approve_and_send(rid, "slack", actor.email or actor.subject, slack=_slack(),
                                        slack_channel=cfg["slack_channel"])
                st.session_state["recap_flash"] = (o.ok, o.message)
                st.rerun()
            email_ok = bool(cfg.get("email_list"))
            if b.button("Approve & send email", key=f"rc_email_{rid}", icon=":material/mail:",
                        disabled=not email_ok or "email:ok" in r.get("send_result", ""),
                        help=None if email_ok else "Set [recap] email_list"):
                o = rp.approve_and_send(rid, "email", actor.email or actor.subject, email=_email(),
                                        email_list=cfg["email_list"])
                st.session_state["recap_flash"] = (o.ok, o.message)
                st.rerun()
            if status != ops.SENT and b.button("Discard", key=f"rc_discard_{rid}", icon=":material/delete:"):
                o = rp.discard(rid, actor.email or actor.subject)
                st.session_state["recap_flash"] = (o.ok, o.message)
                st.rerun()


# ── Needs you: event request triage ───────────────────────────────────────────────────────────

DECISIONS = ["Approve", "Waitlist", "Not a fit"]
SHEET_STATUS = {"Approve": "Approved", "Waitlist": "Waitlisted", "Not a fit": "Not a Fit"}


def set_sheet_status(event_id: str, status: str) -> bool:
    """Update the Events tab status for one event (Sheets mode)."""
    rec = next((r for r in ops.records("Events") if r.get("event_id") == event_id), None)
    if rec is None:
        return False
    cols = [c for c in rec if c != "_row"]
    rec["status"] = status
    return ops.sheets().update("Events", rec["_row"], [rec[c] for c in cols])


def apply_decisions(choices: dict[str, str]) -> tuple[list[str], list[str]]:
    """Set statuses and mark each event "decided:<choice>" so its email draft survives refreshes. Sends nothing."""
    done, failed = [], []
    for eid, decision in choices.items():
        if set_sheet_status(eid, SHEET_STATUS[decision]):
            ops.upsert("Triage", "event_id", eid, {"decision_draft": f"decided:{decision}"})
            done.append(eid)
        else:
            failed.append(eid)
    return done, failed


def pending_drafts() -> dict[str, dict]:
    """Email drafts for decided events not yet emailed or skipped, rebuilt from the sheet."""
    from utils import triage as tr
    events = {r["event_id"]: r for r in ops.records("Events")}
    out = {}
    for r in ops.records("Triage"):
        state, _, decision = r.get("decision_draft", "").partition(":")
        if state != "decided" or decision not in DECISIONS or r["event_id"] not in events:
            continue
        e = events[r["event_id"]]
        t = tr.Triage(r["event_id"], e.get("event_name", ""), e.get("status", ""), None, None, row=e)
        subj, body = tr.draft_email(t, decision)
        out[r["event_id"]] = {"to": e.get("organizer_email", ""), "subject": subj, "body": body,
                              "decision": decision, "event": t.name}
    return out


def _email_html(body: str) -> str:
    import html as _h
    return "".join(f"<p>{_h.escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n"))


def render_drafts(actor) -> None:
    drafts = pending_drafts()
    if not drafts:
        return
    st.markdown(f"#### Vendor emails to review · {len(drafts)}")
    st.caption("Drafted from your decisions. Edit anything, tick **Reviewed**, then send. Nothing goes out on its own.")
    ready = {}
    for eid, d in drafts.items():
        with st.container(border=True):
            st.markdown(f"**{md(d['event'])}** · {md(d['decision'])} → {md(d['to']) or ':red[no organizer email]'}")
            d["subject"] = st.text_input("Subject", d["subject"], key=f"vd_subj_{eid}")
            d["body"] = st.text_area("Message", d["body"], key=f"vd_body_{eid}", height=180)
            c = st.container(horizontal=True, vertical_alignment="center")
            reviewed = c.checkbox("Reviewed", key=f"vd_rev_{eid}")
            if reviewed and d["to"]:
                ready[eid] = d
            if c.button("Send", key=f"vd_send_{eid}", icon=":material/send:", disabled=not (reviewed and d["to"])):
                _send_draft(eid, d)
                st.rerun()
            if c.button("Don't send", key=f"vd_drop_{eid}"):
                ops.upsert("Triage", "event_id", eid, {"decision_draft": f"skipped:{d['decision']}"})
                st.rerun()
    if len(ready) > 1 and st.button(f"Send {len(ready)} reviewed emails", type="primary", key="vd_send_all"):
        for eid, d in ready.items():
            _send_draft(eid, d)
        st.rerun()


def _send_draft(eid, d) -> None:
    r = _email()([d["to"]], d["subject"], _email_html(d["body"]))
    flash = st.session_state.setdefault("needs_flash", [])
    if r:
        ops.upsert("Triage", "event_id", eid, {"decision_draft": f"emailed:{d['decision']}"})
        flash.append((True, f"Email sent for {d['event']}."))
    else:
        flash.append((False, f"Email for {d['event']} failed ({getattr(r, 'reason', '') or 'send_failed'}). "
                             "It's still in the list."))


def render_needs_you(actor, svc=None) -> None:
    from utils import triage as tr
    for ok, msg in st.session_state.pop("needs_flash", []):
        (st.success if ok else st.error)(md(msg))
    if svc is not None:
        st.info("Workflow store is on: proposals made through the workflow appear under **Workflow**. "
                "This queue covers events in the Google Sheet.", icon=":material/info:")
    try:
        events, requests = ops.records("Events"), ops.records("Speaker_Requests")
    except Exception:
        st.error("Couldn't read the Events tab. Try again in a minute.")
        return
    saved = {r["event_id"]: r for r in ops.records("Triage")}
    rules = ops.rules()
    items = tr.triage(events, requests, rules)
    with st.expander(":material/tune: Triage rules", expanded=False):
        render_rules(rules)
    render_drafts(actor)
    st.markdown(f"#### Needs you · {len(items)} pending")
    if not items:
        st.success("Inbox zero: no pending event requests.", icon=":material/task_alt:")
        return
    st.caption("Soonest event or CFP deadline first. Suggested decisions are pre-selected; change any before applying.")
    with st.form("needs_form"):
        choices = {}
        for t in items:
            with st.container(border=True):
                top = st.container(horizontal=True, vertical_alignment="center")
                top.markdown(f"**{md(t.name)}** · {md(t.row.get('event_city'))}, {md(t.row.get('event_country'))}")
                top.badge(f"Fit {t.score}", color="green" if t.score >= 70 else "orange" if t.score >= 40 else "red")
                if t.urgency:
                    top.badge(f"{t.urgency:%b %d}", icon=":material/schedule:", color="gray")
                if t.missing:
                    top.badge("Incomplete", color="red", icon=":material/error:")
                if t.duplicate_of:
                    top.badge(f"Duplicate of {t.duplicate_of}", color="red", icon=":material/content_copy:")
                if t.conflicts:
                    top.badge("Date conflict", color="orange", icon=":material/event_busy:")
                note = saved.get(t.event_id, {}).get("ai_rationale", "")
                st.caption(f":material/auto_awesome: {md(note) if note else 'AI note pending'}")
                if t.row.get("speaker_topic"):
                    st.markdown(f"**Topic:** {md(t.row['speaker_topic'])}")
                with st.expander("Why this score"):
                    for line in t.reasons + t.conflicts + ([f"Missing: {', '.join(t.missing)}"] if t.missing else []):
                        st.markdown(f"- {md(line)}")
                pick = st.radio("Decision", ["Decide later"] + DECISIONS, horizontal=True, key=f"nd_{t.event_id}",
                                index=(DECISIONS.index(t.suggestion) + 1) if t.suggestion else 0)
                if pick in DECISIONS:
                    choices[t.event_id] = pick
        apply = st.form_submit_button("Apply decisions", type="primary", icon=":material/done_all:")
    if apply:
        if not choices:
            st.warning("Pick at least one decision.")
            return
        done, failed = apply_decisions(choices)
        flash = st.session_state.setdefault("needs_flash", [])
        if done:
            flash.append((True, f"Updated {len(done)} event(s). Vendor emails are drafted below — review before sending."))
        if failed:
            flash.append((False, f"Couldn't update {', '.join(failed)}. Try again."))
        st.rerun()


def render_rules(rules: dict) -> None:
    from utils import triage as tr
    merged = tr.merged_rules(rules)
    with st.form("rules_form", border=False):
        vals = {k: st.text_input(k.replace("_", " ").capitalize(), merged[k], help=tr.RULE_HELP[k], key=f"rule_{k}")
                for k in tr.DEFAULT_RULES}
        if st.form_submit_button("Save rules"):
            ok = all(ops.upsert("Triage_Rules", "key", k, {"value": v.strip()}) for k, v in vals.items())
            (st.success if ok else st.error)("Rules saved." if ok else "Couldn't save the rules. Try again.")


# ── Content checks (workflow store) ───────────────────────────────────────────────────────────

CHECK_BADGE = {"pass": ("green", ":material/check:"), "fail": ("red", ":material/close:"),
               "manual": ("orange", ":material/visibility:")}


def render_content(actor, svc=None) -> None:
    from datetime import datetime, timezone
    from utils import content_checks as cc
    st.markdown("#### Overdue and failed checks")
    st.caption("Required speaker items: bio, headshot, talk title and abstract, slides. Reminders go out 14, 7 and "
               "2 days before each deadline, and only once delivery is turned on.")
    if svc is None:
        ui.coming_soon("Content tracking",
                       "This needs the workflow store. Add `[connections.cv_workflow]` to the app secrets and run "
                       "the migration to switch it on.")
        return
    today = datetime.now(timezone.utc).date()
    reports = cc.report(svc.store, svc.files, today)
    reviews = {r["item_id"]: r for r in ops.records("Content_Review")}
    attention = [r for r in reports if r.needs_attention]
    c = st.columns(3)
    c[0].metric("Items tracked", len(reports))
    c[1].metric("Overdue", sum(r.overdue for r in reports))
    c[2].metric("Failed or manual checks", sum(any(x.status != "pass" for x in r.checks) for r in reports))
    if not svc.config.delivery_enabled:
        st.info("Delivery is OFF: reminders are recorded in the outbox but not sent.", icon=":material/notifications_off:")
    if not attention:
        st.success("Nothing needs you: every item is on time and passing.", icon=":material/task_alt:")
        return
    for r in attention:
        with st.container(border=True):
            top = st.container(horizontal=True, vertical_alignment="center")
            top.markdown(f"**{md(r.speaker) or 'Unassigned'}** · {md(r.event_name)} · {md(r.title)}")
            if r.overdue:
                top.badge(f"Overdue since {r.due_date:%b %d}", color="red", icon=":material/alarm:")
            elif r.due_date:
                top.badge(f"Due {r.due_date:%b %d}", color="gray", icon=":material/schedule:")
            for ch in r.checks:
                color, icon = CHECK_BADGE[ch.status]
                st.markdown(f":{color}[{icon}] {md(ch.message)}")
            note = reviews.get(r.item_id, {}).get("ai_note")
            if note:
                st.caption(f":material/auto_awesome: Brand review (advisory): {md(note)}")
            st.markdown(f"[Open in workspace](/workspace?event={r.event_id}&item={r.item_id})")
