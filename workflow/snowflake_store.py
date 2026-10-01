"""Snowflake implementation of the workflow Store, backed by hybrid tables.

Uses a dedicated least-privilege service connection (never an end-user's credentials).
Operations are serialized on one connection with a lock: this app's write volume is low, and
it keeps transactions from interleaving across Streamlit sessions.
"""
from __future__ import annotations

import dataclasses
import threading
from typing import Callable

from workflow.models import (
    PENDING, RETRY, SENDING, UNCERTAIN, AuditEvent, ChangeSet, ConcurrentModification,
    DuplicateAction, Event, InvalidAction, Item, ItemVersion, Member, Notification,
)

TABLES = {
    Event: ("WF_EVENTS", ("event_id",)),
    Member: ("WF_MEMBERS", ("member_id",)),
    Item: ("WF_ITEMS", ("item_id",)),
    ItemVersion: ("WF_ITEM_VERSIONS", ("item_id", "version")),
    AuditEvent: ("WF_AUDIT", ("audit_id",)),
    Notification: ("WF_OUTBOX", ("notification_id",)),
}


def _cols(cls):
    return [f.name for f in dataclasses.fields(cls)]


def _row_to(cls, row: dict):
    kwargs = {}
    for f in dataclasses.fields(cls):
        v = row.get(f.name.upper())
        if v is None and f.default is not dataclasses.MISSING and f.default is not None:
            v = f.default
        if isinstance(v, bool) or f.type in ("bool",):
            v = bool(v)
        elif f.type in ("int",) and v is not None:
            v = int(v)
        kwargs[f.name] = v
    return cls(**kwargs)


def _is_unique_violation(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "duplicate key" in msg or "unique constraint" in msg or "primary key" in msg and "violat" in msg


class SnowflakeStore:
    def __init__(self, connect: Callable[[], object]):
        """`connect` returns a snowflake.connector connection created with paramstyle='qmark'."""
        self._connect = connect
        self._conn = None
        self._lock = threading.RLock()

    # ── plumbing ──────────────────────────────────────────────────────────────
    def _c(self):
        if self._conn is None or self._conn.is_closed():
            self._conn = self._connect()
        return self._conn

    def _query(self, sql, params=()):
        from snowflake.connector import DictCursor
        with self._lock:
            cur = self._c().cursor(DictCursor)
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                cur.close()

    def _select(self, cls, where="", params=(), order="", limit=None):
        table, _ = TABLES[cls]
        sql = f"SELECT {', '.join(c.upper() for c in _cols(cls))} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_row_to(cls, r) for r in self._query(sql, params)]

    @staticmethod
    def _insert(cur, obj):
        table, _ = TABLES[type(obj)]
        cols = _cols(type(obj))
        sql = (f"INSERT INTO {table} ({', '.join(c.upper() for c in cols)}) "
               f"VALUES ({', '.join('?' for _ in cols)})")
        cur.execute(sql, [getattr(obj, c) for c in cols])

    @staticmethod
    def _update(cur, obj, guard_col=None, guard_val=None) -> int:
        table, keys = TABLES[type(obj)]
        cols = [c for c in _cols(type(obj)) if c not in keys]
        sql = (f"UPDATE {table} SET {', '.join(f'{c.upper()} = ?' for c in cols)} "
               f"WHERE {' AND '.join(f'{k.upper()} = ?' for k in keys)}")
        params = [getattr(obj, c) for c in cols] + [getattr(obj, k) for k in keys]
        if guard_col:
            sql += f" AND {guard_col} = ?"
            params.append(guard_val)
        cur.execute(sql, params)
        return cur.rowcount

    # ── writes ────────────────────────────────────────────────────────────────
    def action_exists(self, action_key):
        return bool(self._query("SELECT 1 FROM WF_AUDIT WHERE ACTION_KEY = ? LIMIT 1", [action_key]))

    def apply(self, cs: ChangeSet) -> None:
        with self._lock:
            conn = self._c()
            cur = conn.cursor()
            cur.execute("BEGIN")
            try:
                for a in cs.audit:
                    self._insert(cur, a)
                for e in cs.events:
                    self._insert(cur, e)
                for e in cs.event_updates:
                    if self._update(cur, e) != 1:
                        raise ConcurrentModification(e.event_id)
                for m in cs.members:
                    try:
                        self._insert(cur, m)
                    except Exception as exc:
                        if _is_unique_violation(exc):
                            raise InvalidAction("That person already has this role on the event.") from None
                        raise
                for mu in cs.member_updates:
                    if self._update(cur, mu.member, "STATUS", mu.expected_status) != 1:
                        raise ConcurrentModification(mu.member.member_id)
                for it in cs.items:
                    self._insert(cur, it)
                for iu in cs.item_updates:
                    if self._update(cur, iu.item, "CURRENT_VERSION", iu.expected_version) != 1:
                        raise ConcurrentModification(iu.item.item_id)
                for v in cs.versions:
                    self._insert(cur, v)
                for n in cs.notifications:
                    self._insert(cur, n)
                for n, expected in cs.notification_updates:
                    if self._update(cur, n, "STATUS", expected) != 1:
                        raise ConcurrentModification(n.notification_id)
                cur.execute("COMMIT")
            except Exception as exc:
                cur.execute("ROLLBACK")
                if isinstance(exc, (ConcurrentModification, InvalidAction)):
                    raise
                if _is_unique_violation(exc):
                    raise DuplicateAction(cs.audit[0].action_key if cs.audit else "") from None
                raise
            finally:
                cur.close()

    # ── reads ─────────────────────────────────────────────────────────────────
    def get_event(self, event_id):
        rows = self._select(Event, "EVENT_ID = ?", [event_id])
        return rows[0] if rows else None

    def list_events(self):
        return self._select(Event, order="EVENT_ID")

    def list_members(self, *, event_id=None, subject=None, email=None):
        clauses, params = [], []
        for col, val in (("EVENT_ID", event_id), ("SUBJECT", subject), ("EMAIL", email)):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        return self._select(Member, " AND ".join(clauses), params, order="MEMBER_ID")

    def list_items(self, event_id):
        if event_id is None:
            return self._select(Item, order="ITEM_ID")
        return self._select(Item, "EVENT_ID = ?", [event_id], order="ITEM_ID")

    def get_notification(self, notification_id):
        rows = self._select(Notification, "NOTIFICATION_ID = ?", [notification_id])
        return rows[0] if rows else None

    def get_item(self, item_id):
        rows = self._select(Item, "ITEM_ID = ?", [item_id])
        return rows[0] if rows else None

    def list_versions(self, item_id):
        return self._select(ItemVersion, "ITEM_ID = ?", [item_id], order="VERSION")

    def list_audit(self, *, event_id=None, limit=200):
        if event_id is None:
            return self._select(AuditEvent, order="CREATED_AT DESC", limit=limit)
        return self._select(AuditEvent, "EVENT_ID = ?", [event_id], order="CREATED_AT DESC", limit=limit)

    def list_notifications(self, *, statuses=None, event_id=None, action_key=None, limit=500):
        clauses, params = [], []
        if statuses:
            clauses.append(f"STATUS IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if event_id is not None:
            clauses.append("EVENT_ID = ?")
            params.append(event_id)
        if action_key is not None:
            clauses.append("ACTION_KEY = ?")
            params.append(action_key)
        return self._select(Notification, " AND ".join(clauses), params, order="CREATED_AT DESC", limit=limit)

    # ── outbox delivery ───────────────────────────────────────────────────────
    def claim_notifications(self, *, now, limit, token, action_key=None):
        with self._lock:
            cur = self._c().cursor()
            try:
                where = "STATUS IN (?, ?) AND NEXT_ATTEMPT_AT <= ?"
                params = [PENDING, RETRY, now]
                if action_key is not None:
                    where += " AND ACTION_KEY = ?"
                    params.append(action_key)
                cur.execute(f"SELECT NOTIFICATION_ID FROM WF_OUTBOX WHERE {where} "
                            f"ORDER BY CREATED_AT LIMIT {int(limit)}", params)
                ids = [r[0] for r in cur.fetchall()]
                for nid in ids:
                    # Conditional update: a concurrent dispatcher that claimed it first wins.
                    cur.execute("UPDATE WF_OUTBOX SET STATUS = ?, CLAIM_TOKEN = ?, UPDATED_AT = ? "
                                "WHERE NOTIFICATION_ID = ? AND STATUS IN (?, ?)",
                                [SENDING, token, now, nid, PENDING, RETRY])
            finally:
                cur.close()
        return self._select(Notification, "CLAIM_TOKEN = ? AND STATUS = ?", [token, SENDING], order="CREATED_AT")

    def finish_notification(self, n, token):
        with self._lock:
            cur = self._c().cursor()
            try:
                table, keys = TABLES[Notification]
                cols = [c for c in _cols(Notification) if c not in keys]
                cur.execute(
                    f"UPDATE {table} SET {', '.join(f'{c.upper()} = ?' for c in cols)} "
                    f"WHERE NOTIFICATION_ID = ? AND STATUS = ? AND CLAIM_TOKEN = ?",
                    [getattr(n, c) for c in cols] + [n.notification_id, SENDING, token])
                return cur.rowcount == 1
            finally:
                cur.close()

    def mark_stale_uncertain(self, *, before, now):
        with self._lock:
            cur = self._c().cursor()
            try:
                cur.execute("UPDATE WF_OUTBOX SET STATUS = ?, UPDATED_AT = ?, LAST_ERROR = ? "
                            "WHERE STATUS = ? AND COALESCE(UPDATED_AT, CREATED_AT) < ?",
                            [UNCERTAIN, now, "Send was interrupted; delivery unknown.", SENDING, before])
                return cur.rowcount
            finally:
                cur.close()
