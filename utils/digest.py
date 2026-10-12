"""Daily digest: only the things that need a decision, written to the Digest tab for the good-morning briefing."""
from __future__ import annotations

from datetime import date, timedelta

from utils import ops_store as ops
from utils import triage as tr


def build(today: date, admin_url: str = "", content_reports=None) -> list[list[str]]:
    """Rows of [generated_at, key, value, link]. Keys are stable so the briefing can read them."""
    from utils.recap import now_utc
    ts = now_utc().isoformat(timespec="seconds")
    base = admin_url.rstrip("/")
    link = lambda tab: f"{base}/workflow-admin?tab={tab}" if base else ""   # noqa: E731
    items = tr.triage(ops.records("Events"), ops.records("Speaker_Requests"), ops.rules(), today=today)
    urgent = [t for t in items if t.urgency and t.urgency <= today + timedelta(days=7)]
    rows = [[ts, "event_requests_pending", str(len(items)), link("needs")],
            [ts, "event_requests_urgent_7d", str(len(urgent)), link("needs")]]
    for t in urgent[:5]:
        rows.append([ts, "urgent_event", f"{t.name} · {t.urgency:%b %d} · fit {t.score}", link("needs")])
    drafts = [r for r in ops.records("Triage") if r.get("decision_draft", "").startswith("decided:")]
    rows.append([ts, "vendor_emails_to_review", str(len(drafts)), link("needs")])

    if content_reports is None:
        rows.append([ts, "content", "workflow store not configured", ""])
    else:
        overdue = [r for r in content_reports if r.overdue]
        failed = [r for r in content_reports if not r.overdue and r.needs_attention]
        rows += [[ts, "content_overdue", str(len(overdue)), link("content")],
                 [ts, "content_failed_checks", str(len(failed)), link("content")]]
        for r in overdue[:5]:
            who = r.speaker.split("@")[0] if r.speaker else "Unassigned"     # no full addresses in the digest
            rows.append([ts, "overdue_item", f"{who} · {r.title} · {r.event_name}", link("content")])

    recaps = sorted(ops.records("Recaps"), key=lambda r: r.get("week_start", ""), reverse=True)
    rows.append([ts, "latest_recap", f"{recaps[0]['status']} (week of {recaps[0]['week_start']})" if recaps
                 else "none yet", link("recaps")])
    return rows
