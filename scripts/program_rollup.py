"""Program sheet roll-up (cron, hourly): feedback, headcount, partner metrics and speaker updates → Speaker-Events.

  python scripts/program_rollup.py           # dry run: reads the real sheets, prints what it would write, writes nothing
  python scripts/program_rollup.py --write   # fill blank cells, copy new ratings, record unmatched rows in Needs_Review

Never sends anything.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


class DryRun:
    """Reads pass through to the real sheet; writes are printed instead of made."""

    def __init__(self, real, label):
        self.real, self.label = real, label

    def read(self, tab):
        return self.real.read(tab)

    def append(self, tab, row):
        print(f"  [{self.label}] would append to {tab}: {row[:6]}")
        return True

    def update(self, tab, sheet_row, row):
        print(f"  [{self.label}] would update {tab} row {sheet_row}: {row[:6]}")
        return True

    def set(self, tab, sheet_row, column, value):
        print(f"  [{self.label}] would set {tab} row {sheet_row} {column} = {value}")
        return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    from utils import ops_store as ops
    from utils import rollup
    from utils import slots as sl

    if not args.write:
        sl.OVERRIDE["program"] = DryRun(sl.SheetProgram(), "program")
        ops.OVERRIDE["sheets"] = DryRun(ops.GoogleSheets(), "hub")
    out = rollup.run()
    print(f"Feedback copied: {out['feedback_copied']} · cells filled: {len(out['filled'])} "
          f"· flagged for review: {out['flagged']} · updates retried: {out['retried']}"
          + ("" if args.write else "  (dry run: nothing written)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
