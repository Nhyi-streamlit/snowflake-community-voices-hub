"""Weekly recap job (run Monday mornings from cron).

  python scripts/weekly_recap.py                  # dry run: preview only, writes logs/recap-preview.*
  python scripts/weekly_recap.py --publish-draft  # Google Doc + Recaps row + "Recap ready" DM to Aba

Nothing is sent to the team channel or email list here; that happens only when Aba approves in
Workflow admin → Recaps. Secrets come from .streamlit/secrets.toml (gitignored).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                       # st.secrets reads ./.streamlit/secrets.toml

PROGRAM_TZ = ZoneInfo("America/New_York")


def secret(path: str, default=""):
    import streamlit as st
    cur = st.secrets
    try:
        for part in path.split("."):
            cur = cur[part]
        return cur
    except Exception:
        return default


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish-draft", action="store_true")
    ap.add_argument("--scheduled", action="store_true",
                    help="cron mode: only on Mondays from 8:00 ET, and only if this week has no recap yet")
    ap.add_argument("--today", help="YYYY-MM-DD (for re-running a past week)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from utils import ops_store as ops
    from utils import recap as rc
    from utils import recap_publish as rp
    from utils.sheets import create_google_doc, read_tab

    now_et = datetime.now(PROGRAM_TZ)
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else now_et.date()
    start, end = rc.week_bounds(today)
    if args.scheduled:
        # Cron fires hourly (the Mac isn't on Eastern time and may be asleep at 8:00): the first run at or after
        # Monday 8:00 ET drafts last week's recap; every other run finds it already drafted and exits.
        if args.today is None and now_et.weekday() == 0 and now_et.hour < 8:
            return 0
        if any(r.get("recap_id") == f"recap-{start.isoformat()}" for r in ops.records("Recaps")):
            return 0
    tabs = rp.load_tabs(read_tab)
    summary = rc.summarize(tabs, start, end)

    if not args.publish_draft:
        os.makedirs("logs", exist_ok=True)
        with open("logs/recap-preview.txt", "w") as f:
            f.write(rc.to_slack(summary))
        with open("logs/recap-preview.html", "w") as f:
            f.write(rc.to_html(summary))
        print(rc.to_slack(summary))
        print("\n[dry run] Preview written to logs/recap-preview.txt/.html. Nothing created or sent.")
        return 0

    token, user = secret("notify.slack.bot_token"), secret("recap.slack_user_id")
    if not (token and user):
        print("Missing [notify.slack] bot_token or [recap] slack_user_id in .streamlit/secrets.toml")
        return 2
    from workflow.channels import SlackChannel
    base = str(secret("APP_BASE_URL", "") or "").rstrip("/")
    out = rp.publish_draft(tabs, today, make_doc=lambda t, h: create_google_doc(t, h, secret("recap.drive_folder_id") or None),
                           slack=SlackChannel(bot_token=token), dm_user=user,
                           admin_url=f"{base}/workflow-admin?tab=recaps" if base else "")
    print(out.message, out.doc_url or "")
    return 0 if out.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
