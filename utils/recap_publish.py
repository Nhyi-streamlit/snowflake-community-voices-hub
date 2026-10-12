"""Recap lifecycle: create the draft (Doc + Recaps row + DM to Aba), then send only on admin approval.

Dependencies are injected so tests use fakes:
  make_doc(title, html) -> (url, reason)
  slack: object with send_mrkdwn(address, text)       (workflow.channels.SlackChannel / FakeChannel)
  email(to_list, subject, html) -> SendResult-like    (utils.sheets.send_gmail_result)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from utils import ops_store as ops
from utils import recap as rc
from workflow.channels import DeliveryError

log = logging.getLogger("cv.recap")
SOURCE_TABS = ["Events", "Speaker_Requests", "Talk_Feedback", "Event_Headcount", "Reimbursements"]


@dataclass
class Outcome:
    ok: bool
    message: str
    recap_id: str = ""
    doc_url: str = ""


def load_tabs(read) -> dict:
    """{tab: DataFrame or None if unreadable}."""
    out = {}
    for t in SOURCE_TABS:
        try:
            out[t] = read(t)
        except Exception as e:      # missing tab / outage: recap still drafts, and lists what it couldn't read
            log.warning("recap: couldn't read %s (%s)", t, type(e).__name__)
            out[t] = None
    return out


def publish_draft(tabs: dict, today, *, make_doc, slack, dm_user: str, admin_url: str = "",
                  workflow_counts: dict | None = None) -> Outcome:
    start, end = rc.week_bounds(today)
    s = rc.summarize(tabs, start, end, workflow_counts)
    rid = rc.recap_id(s)
    existing = next((r for r in ops.records("Recaps") if r.get("recap_id") == rid), None)
    if existing and existing.get("status") in (ops.APPROVED, ops.SENT):
        return Outcome(True, f"Recap for {rid} was already {existing['status'].lower()}; nothing changed.", rid,
                       existing.get("doc_url", ""))
    html_body = rc.to_html(s)
    doc_url, reason = (existing.get("doc_url"), "") if existing and existing.get("doc_url") else \
        make_doc(f"Community Voices recap · {start:%b %d}–{end:%b %d, %Y}", html_body)
    slack_text = rc.to_slack(s, doc_url)
    ops.upsert("Recaps", "recap_id", rid, {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "created_at": rc.now_utc().isoformat(timespec="seconds"), "status": ops.DRAFT, "doc_url": doc_url,
        "slack_text": slack_text, "email_html": html_body,
        "send_result": f"doc_failed:{reason}" if reason else ""})
    if existing:
        return Outcome(True, f"Updated the existing draft {rid} (no second DM).", rid, doc_url)
    lines = [f"*Recap ready* for {start:%b %d}–{end:%b %d}."]
    if doc_url:
        lines.append(f"<{doc_url}|Open the Google Doc>")
    elif reason:
        lines.append(f"(Google Doc couldn't be created: `{reason}`. The text is in Workflow admin.)")
    if admin_url:
        lines.append(f"<{admin_url}|Review and approve in Workflow admin → Recaps>")
    try:
        slack.send_mrkdwn(dm_user, "\n".join(lines))
    except DeliveryError as e:
        return Outcome(False, f"Draft saved, but the Slack DM failed: {e}", rid, doc_url)
    return Outcome(True, "Draft saved and DM sent.", rid, doc_url)


def _set(rid, **fields):
    ops.upsert("Recaps", "recap_id", rid, fields)


def approve_and_send(rid: str, target: str, actor_email: str, *, slack=None, slack_channel: str = "",
                     email=None, email_list: list[str] | None = None) -> Outcome:
    """target is "slack" or "email". Called only from the admin's button click."""
    rec = next((r for r in ops.records("Recaps") if r.get("recap_id") == rid), None)
    if rec is None:
        return Outcome(False, "That recap no longer exists.")
    if rec.get("status") == ops.DISCARDED:
        return Outcome(False, "This recap was discarded.")
    now = rc.now_utc().isoformat(timespec="seconds")
    prior = rec.get("send_result", "")
    if f"{target}:ok" in prior:
        return Outcome(True, f"Already sent to {target}; not sending twice.", rid)
    _set(rid, status=ops.APPROVED, approved_by=actor_email, approved_at=now)
    if target == "slack":
        if not (slack and slack_channel):
            return Outcome(False, "No recap Slack channel is configured.", rid)
        try:
            slack.send_mrkdwn(slack_channel, rec["slack_text"])
            result, ok = "slack:ok", True
        except DeliveryError as e:
            result, ok = f"slack:failed:{e}", False
    elif target == "email":
        if not (email and email_list):
            return Outcome(False, "No recap email list is configured.", rid)
        r = email(email_list, f"Community Voices weekly recap · week of {rec['week_start']}", rec["email_html"])
        ok = bool(r)
        result = "email:ok" if ok else f"email:failed:{getattr(r, 'reason', '') or 'send_failed'}"
    else:
        return Outcome(False, "Unknown target.", rid)
    combined = ";".join(x for x in (prior, result) if x)
    _set(rid, send_result=combined, **({"status": ops.SENT, "sent_at": now} if ok else {}))
    return Outcome(ok, f"Sent to {target}." if ok else f"Send to {target} failed: {result.split(':', 2)[-1]}", rid)


def discard(rid: str, actor_email: str) -> Outcome:
    rec = next((r for r in ops.records("Recaps") if r.get("recap_id") == rid), None)
    if rec is None or rec.get("status") == ops.SENT:
        return Outcome(False, "Only unsent drafts can be discarded.", rid)
    _set(rid, status=ops.DISCARDED, approved_by=actor_email,
         approved_at=rc.now_utc().isoformat(timespec="seconds"))
    return Outcome(True, "Discarded. Nothing was sent.", rid)
