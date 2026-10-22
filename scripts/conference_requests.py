"""Conference support requests (cron, hourly): record new form rows in Conference_Approvals and email Aba.

Sends only to aba.micah@snowflake.com. Never emails Navan (that happens on Approve in Workflow admin).

  python scripts/conference_requests.py               # dry run: show unseen rows, write and send nothing
  python scripts/conference_requests.py --baseline    # once: record every current row as seen, send nothing
  python scripts/conference_requests.py --baseline --before 2026-10-01   # older rows seen; newer stay pending
  python scripts/conference_requests.py --notify      # record new rows and email Aba about each
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--notify", action="store_true")
    g.add_argument("--baseline", action="store_true")
    ap.add_argument("--before", default="", help="with --baseline: only rows submitted before this ISO date")
    args = ap.parse_args(argv)
    import streamlit as st
    from utils import conference as cf

    if not (args.notify or args.baseline):
        seen = cf.tracked()
        new = [r for r in cf.source_rows() if cf.key_of(r) not in seen]
        print(f"{len(new)} unseen row(s) (dry run; nothing written or sent).")
        for r in new:
            s = cf.summary(r)
            print(f"  {s['submitted_at']} · {s['name']} · {s['conference']}")
        return 0
    try:
        base = str(st.secrets.get("APP_BASE_URL", "") or "")
    except Exception:
        base = ""
    r = cf.check(notify=args.notify, baseline=args.baseline, base_url=base, baseline_before=args.before)
    if r["blocked"]:
        print(r["blocked"])
        return 1
    print(f"Conference requests: {r['new']} new, {r['notified']} emailed"
          + (f", failed: {', '.join(r['failed'])}" if r["failed"] else ""))
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
