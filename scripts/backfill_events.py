"""Backfill legacy Sheet events into the workflow store. Dry-run by default.

  # report counts only (reads the Sheet; writes nothing)
  python scripts/backfill_events.py --connection <name> --schema DB.SCHEMA --admin-subject <sub>
  # apply
  python scripts/backfill_events.py ... --apply

Sheet credentials are read from GOOGLE_* environment variables (see utils/sheets.py).
Output never prints names or emails.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.backfill import plan  # noqa: E402
from workflow.models import DuplicateAction  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--connection", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--admin-subject", required=True, help="Google subject recorded as the backfill actor")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()

    from utils.sheets import read_tab
    events = read_tab("Events").fillna("").to_dict("records")
    apps = read_tab("Speaker_Applications").fillna("").to_dict("records")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    changesets, report = plan(events, apps, now=now, actor_subject=a.admin_subject)
    print({k: v for k, v in report.items()})
    if not a.apply:
        print("Dry run: nothing written. Re-run with --apply.")
        return

    import snowflake.connector
    from workflow.snowflake_store import SnowflakeStore
    db, sch = a.schema.split(".")
    store = SnowflakeStore(lambda: snowflake.connector.connect(connection_name=a.connection, database=db,
                                                               schema=sch, paramstyle="qmark"))
    applied = skipped = 0
    for cs in changesets:
        try:
            store.apply(cs)
            applied += 1
        except DuplicateAction:
            skipped += 1
    print(f"applied {applied}, already present {skipped}")


if __name__ == "__main__":
    main()
