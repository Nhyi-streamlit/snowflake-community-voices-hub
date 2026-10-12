#!/bin/bash
# Community Voices ops jobs, run hourly from cron on Aba's Mac. Nothing here sends to vendors, speakers,
# team channels or email lists: the recap job DMs Aba only, triage writes the Triage tab, content jobs record
# reminders in the outbox (delivered only when DELIVERY_ENABLED is on), and the digest rewrites the Digest tab.
#   crontab:  5 * * * *  /Users/amicah/.snowflake/cortex/playground/workspace/community-voices-hub/scripts/run_ops_jobs.sh
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
LOG="logs/ops-$(date +%Y-%m-%d).log"
PY="${CV_PYTHON:-/usr/local/bin/python3}"
{
  echo "=== $(date -u +%FT%TZ) ==="
  "$PY" scripts/weekly_recap.py --publish-draft --scheduled
  "$PY" scripts/triage_ai.py --write
  # Idempotent: each reminder is recorded once per item and offset day; AI reviews only new versions.
  "$PY" scripts/content_jobs.py --reminders --ai-review
  "$PY" scripts/daily_digest.py --write
} >> "$LOG" 2>&1
