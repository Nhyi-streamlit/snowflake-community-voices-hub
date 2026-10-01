"""Workflow records. Plain dataclasses shared by the service, stores, and UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Member roles on an event. Admins are global (subject allowlist) and are not members.
OWNER, DELEGATE, SPEAKER, VENDOR = "OWNER", "DELEGATE", "SPEAKER", "VENDOR"
PROGRAM_ROLES = (OWNER, DELEGATE)
ADMIN = "ADMIN"

# Member status. Only ACTIVE members (bound to a verified OIDC subject) are authorized.
# INVITED members are routable by email but cannot read anything until they sign in.
# SUGGESTED rows come from backfill and are neither routable nor authorized.
SUGGESTED, INVITED, ACTIVE, REMOVED = "SUGGESTED", "INVITED", "ACTIVE", "REMOVED"

# Item status
MISSING, SUBMITTED, CHANGES_REQUESTED, APPROVED = "MISSING", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"

# Event status
PROPOSED, EVENT_ACTIVE, CLOSED = "PROPOSED", "ACTIVE", "CLOSED"

# Outbox status
PENDING, SENDING, SENT, RETRY, DEAD, UNROUTABLE, UNCERTAIN, CANCELLED = (
    "PENDING", "SENDING", "SENT", "RETRY", "DEAD", "UNROUTABLE", "UNCERTAIN", "CANCELLED",
)
EMAIL, SLACK, NO_CHANNEL = "EMAIL", "SLACK", "NONE"


@dataclass(frozen=True)
class Event:
    event_id: str
    name: str
    status: str
    start_date: date | None = None
    city: str = ""
    legacy_event_id: str = ""
    created_by: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class Member:
    member_id: str
    event_id: str
    role: str
    email: str
    status: str
    subject: str = ""
    display_name: str = ""
    slack_user_id: str = ""
    shared_with_vendor: bool = False
    created_by: str = ""
    created_at: datetime | None = None
    bound_at: datetime | None = None


@dataclass(frozen=True)
class Item:
    item_id: str
    event_id: str
    item_type: str
    party: str                      # SPEAKER or VENDOR: who submits it
    title: str
    status: str = MISSING
    due_date: date | None = None
    assignee_member_id: str = ""    # set for speaker items (one speaker per item set)
    vendor_visible: bool = False    # speaker items: vendors may see the approved version
    speaker_action: bool = False    # vendor items: assigned speakers must act/see it
    current_version: int = 0
    approved_version: int = 0
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ItemVersion:
    item_id: str
    version: int
    submitted_by: str
    submitted_role: str
    submitted_at: datetime
    content_sha256: str
    action_key: str
    text_json: str = "{}"
    file_path: str = ""
    file_name: str = ""
    file_sha256: str = ""
    file_size: int = 0


@dataclass(frozen=True)
class AuditEvent:
    audit_id: str
    action_key: str
    event_id: str
    action: str
    actor_subject: str
    actor_role: str
    created_at: datetime
    item_id: str = ""
    from_status: str = ""
    to_status: str = ""
    note: str = ""


@dataclass(frozen=True)
class Notification:
    notification_id: str            # idempotency key: hash(action_key, recipient, channel)
    action_key: str
    event_id: str
    rule: str
    channel: str
    status: str
    created_at: datetime
    next_attempt_at: datetime
    item_id: str = ""
    recipient_member_id: str = ""
    recipient_role: str = ""
    address: str = ""
    subject: str = ""
    body: str = ""
    link: str = ""
    deadline: date | None = None
    attempts: int = 0
    max_attempts: int = 5
    last_error: str = ""
    provider_message_id: str = ""
    claim_token: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ItemUpdate:
    """Optimistic update: applies only if the stored item still has expected_version."""
    item: Item
    expected_version: int


@dataclass(frozen=True)
class MemberUpdate:
    member: Member
    expected_status: str


@dataclass
class ChangeSet:
    """Everything one user action writes. Stores apply it atomically or not at all."""
    audit: list[AuditEvent]
    events: list[Event] = field(default_factory=list)              # inserts
    event_updates: list[Event] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)            # inserts
    member_updates: list[MemberUpdate] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)                # inserts
    item_updates: list[ItemUpdate] = field(default_factory=list)
    versions: list[ItemVersion] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    # (updated notification, expected current status) — admin retry / re-route / cancel
    notification_updates: list[tuple[Notification, str]] = field(default_factory=list)

class DuplicateAction(Exception):
    """The action_key was already recorded: a rerun, double-click, or replay."""


class ConcurrentModification(Exception):
    """The record changed since it was read; the user must refresh."""


class NotAuthorized(Exception):
    pass


class InvalidAction(Exception):
    pass
