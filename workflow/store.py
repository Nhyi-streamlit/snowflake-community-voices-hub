"""Store interface and the in-memory implementation used by unit tests.

SnowflakeStore (workflow/snowflake_store.py) implements the same interface against hybrid
tables; tests/test_store_contract.py runs one contract suite against both.
"""
from __future__ import annotations

import copy
import threading
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from workflow.models import (
    PENDING, RETRY, SENDING, UNCERTAIN, AuditEvent, ChangeSet, ConcurrentModification,
    DuplicateAction, Event, InvalidAction, Item, ItemVersion, Member, Notification,
)


class Store(Protocol):
    def action_exists(self, action_key: str) -> bool: ...
    def apply(self, cs: ChangeSet) -> None: ...
    def get_event(self, event_id: str) -> Event | None: ...
    def list_events(self) -> list[Event]: ...
    def list_members(self, *, event_id: str | None = None, subject: str | None = None,
                     email: str | None = None) -> list[Member]: ...
    def list_items(self, event_id: str | None) -> list[Item]: ...
    def get_notification(self, notification_id: str) -> Notification | None: ...
    def get_item(self, item_id: str) -> Item | None: ...
    def list_versions(self, item_id: str) -> list[ItemVersion]: ...
    def list_audit(self, *, event_id: str | None = None, limit: int = 200) -> list[AuditEvent]: ...
    def list_notifications(self, *, statuses: tuple[str, ...] | None = None, event_id: str | None = None,
                           action_key: str | None = None, limit: int = 500) -> list[Notification]: ...
    def claim_notifications(self, *, now: datetime, limit: int, token: str,
                            action_key: str | None = None) -> list[Notification]: ...
    def finish_notification(self, n: Notification, token: str) -> bool: ...
    def mark_stale_uncertain(self, *, before: datetime, now: datetime) -> int: ...


class MemoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.events: dict[str, Event] = {}
        self.members: dict[str, Member] = {}
        self.items: dict[str, Item] = {}
        self.versions: dict[tuple[str, int], ItemVersion] = {}
        self.audit: dict[str, AuditEvent] = {}
        self.outbox: dict[str, Notification] = {}
        self.fail_next_apply = False    # test hook: simulate a database failure

    # ── writes ────────────────────────────────────────────────────────────────
    def action_exists(self, action_key):
        return any(a.action_key == action_key for a in self.audit.values())

    def apply(self, cs: ChangeSet) -> None:
        with self._lock:
            snapshot = copy.deepcopy((self.events, self.members, self.items, self.versions,
                                      self.audit, self.outbox))
            try:
                self._apply(cs)
            except Exception:
                (self.events, self.members, self.items, self.versions,
                 self.audit, self.outbox) = snapshot
                raise

    def _apply(self, cs: ChangeSet):
        for a in cs.audit:
            if self.action_exists(a.action_key) or a.audit_id in self.audit:
                raise DuplicateAction(a.action_key)
            self.audit[a.audit_id] = a
        for e in cs.events:
            if e.event_id in self.events:
                raise DuplicateAction(e.event_id)
            self.events[e.event_id] = e
        for e in cs.event_updates:
            if e.event_id not in self.events:
                raise ConcurrentModification(e.event_id)
            self.events[e.event_id] = e
        for m in cs.members:
            if m.member_id in self.members or any(
                    x.event_id == m.event_id and x.role == m.role and x.email == m.email
                    for x in self.members.values()):
                raise InvalidAction("That person already has this role on the event.")
            self.members[m.member_id] = m
        for mu in cs.member_updates:
            cur = self.members.get(mu.member.member_id)
            if cur is None or cur.status != mu.expected_status:
                raise ConcurrentModification(mu.member.member_id)
            self.members[mu.member.member_id] = mu.member
        for it in cs.items:
            if it.item_id in self.items:
                raise DuplicateAction(it.item_id)
            self.items[it.item_id] = it
        for iu in cs.item_updates:
            cur = self.items.get(iu.item.item_id)
            if cur is None or cur.current_version != iu.expected_version:
                raise ConcurrentModification(iu.item.item_id)
            self.items[iu.item.item_id] = iu.item
        for v in cs.versions:
            key = (v.item_id, v.version)
            if key in self.versions or any(x.action_key == v.action_key for x in self.versions.values()):
                raise DuplicateAction(v.action_key)
            self.versions[key] = v
        for n in cs.notifications:
            if n.notification_id in self.outbox:
                raise DuplicateAction(n.notification_id)
            self.outbox[n.notification_id] = n
        for n, expected in cs.notification_updates:
            cur = self.outbox.get(n.notification_id)
            if cur is None or cur.status != expected:
                raise ConcurrentModification(n.notification_id)
            self.outbox[n.notification_id] = n
        if self.fail_next_apply:
            self.fail_next_apply = False
            raise RuntimeError("simulated database failure")

    # ── reads ─────────────────────────────────────────────────────────────────
    def get_event(self, event_id):
        return self.events.get(event_id)

    def list_events(self):
        return sorted(self.events.values(), key=lambda e: e.event_id)

    def list_members(self, *, event_id=None, subject=None, email=None):
        out = self.members.values()
        if event_id is not None:
            out = [m for m in out if m.event_id == event_id]
        if subject is not None:
            out = [m for m in out if m.subject == subject]
        if email is not None:
            out = [m for m in out if m.email == email]
        return sorted(out, key=lambda m: m.member_id)

    def list_items(self, event_id):
        return sorted((i for i in self.items.values() if event_id is None or i.event_id == event_id),
                      key=lambda i: i.item_id)

    def get_notification(self, notification_id):
        return self.outbox.get(notification_id)

    def get_item(self, item_id):
        return self.items.get(item_id)

    def list_versions(self, item_id):
        return sorted((v for v in self.versions.values() if v.item_id == item_id), key=lambda v: v.version)

    def list_audit(self, *, event_id=None, limit=200):
        out = [a for a in self.audit.values() if event_id is None or a.event_id == event_id]
        return sorted(out, key=lambda a: a.created_at, reverse=True)[:limit]

    def list_notifications(self, *, statuses=None, event_id=None, action_key=None, limit=500):
        out = [n for n in self.outbox.values()
               if (statuses is None or n.status in statuses)
               and (event_id is None or n.event_id == event_id)
               and (action_key is None or n.action_key == action_key)]
        return sorted(out, key=lambda n: n.created_at, reverse=True)[:limit]

    # ── outbox delivery ───────────────────────────────────────────────────────
    def claim_notifications(self, *, now, limit, token, action_key=None):
        with self._lock:
            due = [n for n in self.outbox.values()
                   if n.status in (PENDING, RETRY) and n.next_attempt_at <= now
                   and (action_key is None or n.action_key == action_key)]
            due.sort(key=lambda n: n.created_at)
            claimed = []
            for n in due[:limit]:
                c = replace(n, status=SENDING, claim_token=token, updated_at=now)
                self.outbox[n.notification_id] = c
                claimed.append(c)
            return claimed

    def finish_notification(self, n, token):
        with self._lock:
            cur = self.outbox.get(n.notification_id)
            if cur is None or cur.status != SENDING or cur.claim_token != token:
                return False
            self.outbox[n.notification_id] = n
            return True

    def mark_stale_uncertain(self, *, before, now):
        with self._lock:
            count = 0
            for k, n in list(self.outbox.items()):
                if n.status == SENDING and (n.updated_at or n.created_at) < before:
                    self.outbox[k] = replace(n, status=UNCERTAIN, updated_at=now,
                                             last_error="Send was interrupted; delivery unknown.")
                    count += 1
            return count
