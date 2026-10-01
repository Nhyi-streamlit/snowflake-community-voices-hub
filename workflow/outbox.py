"""Outbox dispatcher: claims due notifications, sends them, and records the true outcome."""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from workflow.channels import DeliveryError
from workflow.models import DEAD, RETRY, SENT, UNCERTAIN, Notification

STALE_AFTER = timedelta(minutes=10)


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=1) * (4 ** max(attempts - 1, 0)), timedelta(hours=1))


def dispatch(store, channels: dict, *, now: datetime, enabled: bool, limit: int = 20,
             action_key: str | None = None) -> dict:
    """Send due notifications. Returns counts. Never raises for a delivery failure."""
    summary = {"sent": 0, "retry": 0, "dead": 0, "uncertain": 0, "skipped": 0}
    if not enabled:
        summary["skipped"] = len(store.list_notifications(statuses=("PENDING", "RETRY"), action_key=action_key))
        return summary
    store.mark_stale_uncertain(before=now - STALE_AFTER, now=now)
    token = uuid.uuid4().hex
    for n in store.claim_notifications(now=now, limit=limit, token=token, action_key=action_key):
        result = _send_one(n, channels.get(n.channel), now)
        if store.finish_notification(result, token):
            summary[{SENT: "sent", RETRY: "retry", DEAD: "dead", UNCERTAIN: "uncertain"}[result.status]] += 1
    return summary


def _send_one(n: Notification, sender, now: datetime) -> Notification:
    attempts = n.attempts + 1
    if sender is None:
        err = DeliveryError(f"Channel {n.channel} is not configured", retryable=True)
    else:
        try:
            mid = sender.send(n.address, n.subject, n.body)
            return replace(n, status=SENT, attempts=attempts, provider_message_id=mid,
                           last_error="", updated_at=now)
        except DeliveryError as exc:
            err = exc
        except Exception as exc:  # unexpected client bug: do not assume delivery
            err = DeliveryError(f"Unexpected error: {type(exc).__name__}", retryable=False, uncertain=True)
    if err.uncertain:
        return replace(n, status=UNCERTAIN, attempts=attempts, last_error=str(err)[:500], updated_at=now)
    if err.retryable and attempts < n.max_attempts:
        return replace(n, status=RETRY, attempts=attempts, last_error=str(err)[:500],
                       next_attempt_at=now + backoff(attempts), updated_at=now)
    return replace(n, status=DEAD, attempts=attempts, last_error=str(err)[:500], updated_at=now)
