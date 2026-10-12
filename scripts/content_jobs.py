"""Daily content job (cron): record 14/7/2-day deadline reminders and add advisory AI brand reviews.

  python scripts/content_jobs.py                   # dry run: report only
  python scripts/content_jobs.py --reminders       # record reminders in the outbox (not sent here)
  python scripts/content_jobs.py --ai-review       # Cortex brand review of new text versions → Content_Review tab

Reminders are delivered only by the existing outbox dispatcher, and only when DELIVERY_ENABLED is on.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

log = logging.getLogger("cv.content_jobs")
JOB_ACTOR_SUBJECT = "cron-content-job"


def ai_review(svc, complete) -> int:
    """Review text items (bio, talk details) whose latest version hasn't been reviewed yet."""
    from utils import content_checks as cc
    from utils import ops_store as ops
    from utils.recap import now_utc
    done = {r["review_key"] for r in ops.records("Content_Review")}
    n = 0
    for item in svc.store.list_items(None):
        if item.item_type not in ("bio", "talk_details"):
            continue
        versions = svc.store.list_versions(item.item_id)
        if not versions:
            continue
        v = max(versions, key=lambda x: x.version)
        key = f"{item.item_id}:{v.version}"
        if key in done:
            continue
        text = json.loads(v.text_json or "{}")
        content = "\n".join(f"{k}: {val}" for k, val in text.items() if isinstance(val, str))
        try:
            note = complete(cc.brand_prompt(item.item_type, content))
        except Exception as e:
            log.warning("brand review failed for %s: %s", item.item_id, type(e).__name__)
            continue
        ops.upsert("Content_Review", "review_key", key, {"item_id": item.item_id, "version": str(v.version),
                                                          "checked_at": now_utc().isoformat(timespec="seconds"),
                                                          "ai_note": note})
        n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reminders", action="store_true")
    ap.add_argument("--ai-review", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from utils import content_checks as cc
    from workflow.runtime import get_service
    from workflow.service import Actor
    svc = get_service()
    if svc is None:
        print("Workflow store not configured ([connections.cv_workflow]). Nothing to do.")
        return 0
    today = datetime.now(ZoneInfo("America/New_York")).date()
    reports = cc.report(svc.store, svc.files, today)
    print(f"{len(reports)} items · {sum(r.overdue for r in reports)} overdue · "
          f"{sum(r.needs_attention for r in reports)} need attention")
    job = Actor(JOB_ACTOR_SUBJECT, "", is_admin=True)
    if args.reminders:
        print(f"Recorded {svc.enqueue_due_reminders(job, today)} reminder(s). "
              f"Delivery is {'ON' if svc.config.delivery_enabled else 'OFF (recorded, not sent)'}.")
    if args.ai_review:
        from scripts.triage_ai import DEFAULT_CONNECTION, DEFAULT_MODEL, cortex_completer
        complete = cortex_completer(os.environ.get("CV_SNOWFLAKE_CONNECTION", DEFAULT_CONNECTION),
                                    os.environ.get("CV_TRIAGE_MODEL", DEFAULT_MODEL))
        print(f"Reviewed {ai_review(svc, complete)} new version(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
