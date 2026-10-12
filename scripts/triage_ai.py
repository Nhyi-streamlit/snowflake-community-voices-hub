"""Hourly triage job: score Pending events, save results to the Triage tab, and add a one-line Cortex AI note.

  python scripts/triage_ai.py            # dry run: print what would be written
  python scripts/triage_ai.py --write    # update the Triage tab (no emails, no status changes)

Only non-personal event fields are sent to Cortex. If Cortex is unavailable, the rule-based triage is
still saved and the note stays "AI note pending".
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

log = logging.getLogger("cv.triage_ai")
DEFAULT_CONNECTION = "sfcogsops-snowhouse_aws_us_west_2"   # name as in ~/.snowflake/connections.toml
DEFAULT_MODEL = "llama3.3-70b"


def cortex_completer(connection: str, model: str):
    """Returns complete(prompt) -> str using AI_COMPLETE with bound parameters.

    Connects lazily on the first prompt, so hourly runs with nothing to review never open a session
    (important when the connection uses browser SSO)."""
    state = {}

    def complete(prompt: str) -> str:
        if "cur" not in state:
            import snowflake.connector
            state["cur"] = snowflake.connector.connect(connection_name=connection).cursor()
        state["cur"].execute("SELECT AI_COMPLETE(%s, %s)", (model, prompt))
        return str(state["cur"].fetchone()[0] or "").strip().strip('"')[:300]
    return complete


def run(write: bool, complete=None, today=None) -> list[dict]:
    from utils import ops_store as ops
    from utils import triage as tr
    from utils.recap import now_utc

    events, requests = ops.records("Events"), ops.records("Speaker_Requests")
    saved = {r["event_id"]: r for r in ops.records("Triage")}
    results = tr.triage(events, requests, ops.rules(), today=today)
    out = []
    for t in results:
        prev = saved.get(t.event_id, {})
        note = prev.get("ai_rationale", "")
        if not note and complete is not None:
            try:
                note = complete(tr.ai_prompt(t))
            except Exception as e:
                log.warning("AI note failed for %s: %s", t.event_id, type(e).__name__)
        fields = {"checked_at": now_utc().isoformat(timespec="seconds"),
                  "completeness": "complete" if t.complete else "missing: " + ", ".join(t.missing),
                  "duplicate_of": t.duplicate_of, "conflicts": "; ".join(t.conflicts),
                  "fit_score": str(t.score), "fit_reasons": "; ".join(t.reasons),
                  "ai_rationale": note, "decision_draft": t.suggestion}
        out.append({"event_id": t.event_id, **fields})
        if write:
            ops.upsert("Triage", "event_id", t.event_id, fields)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--connection", default=os.environ.get("CV_SNOWFLAKE_CONNECTION", DEFAULT_CONNECTION))
    ap.add_argument("--model", default=os.environ.get("CV_TRIAGE_MODEL", DEFAULT_MODEL))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    complete = None if args.no_ai else cortex_completer(args.connection, args.model)
    rows = run(args.write, complete)
    for r in rows:
        print(f"{r['event_id']}: score {r['fit_score']} · {r['decision_draft'] or 'needs a look'} · {r['ai_rationale'][:80]}")
    print(f"{len(rows)} pending event(s). {'Triage tab updated.' if args.write else '[dry run] nothing written.'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
