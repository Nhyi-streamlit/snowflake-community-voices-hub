"""Daily digest job (cron, before the morning briefing): rewrite the Digest tab. Reads only; sends nothing.

  python scripts/daily_digest.py            # print the digest
  python scripts/daily_digest.py --write    # replace the Digest tab
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    import streamlit as st
    from utils import digest, ops_store as ops
    from utils.content_checks import report
    from workflow.runtime import get_service

    today = datetime.now(ZoneInfo("America/New_York")).date()
    try:
        base = str(st.secrets.get("APP_BASE_URL", "") or "")
    except Exception:
        base = ""
    svc = get_service()
    reports = report(svc.store, svc.files, today) if svc is not None else None
    rows = digest.build(today, base, reports)
    for _, key, value, _link in rows:
        print(f"{key}: {value}")
    if args.write:
        print("Digest tab updated." if ops.sheets().replace("Digest", rows) else "Couldn't write the Digest tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
