"""Workflow service: the only entry point pages use. Verifies authorization on every call,
records each action atomically with its audit and outbox rows, and never sends inline.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Callable

from workflow import authz, rules
from workflow.files import object_path
from workflow.models import (
    ACTIVE, ADMIN, APPROVED, CANCELLED, CHANGES_REQUESTED, DEAD, DELEGATE, EMAIL, EVENT_ACTIVE,
    INVITED, MISSING, NO_CHANNEL, OWNER, PENDING, PROGRAM_ROLES, PROPOSED, REMOVED, RETRY,
    SPEAKER, SUBMITTED, SUGGESTED, UNCERTAIN, UNROUTABLE, VENDOR, AuditEvent, ChangeSet,
    ConcurrentModification, DuplicateAction, Event, InvalidAction, Item, ItemUpdate, ItemVersion,
    Member, MemberUpdate, NotAuthorized, Notification,
)
from workflow.outbox import dispatch as _dispatch

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EVENT_STATUSES = (PROPOSED, EVENT_ACTIVE, "CLOSED")
ATTENTION = (PENDING, RETRY, DEAD, UNROUTABLE, UNCERTAIN)


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str
    is_admin: bool = False


@dataclass(frozen=True)
class Config:
    app_base_url: str = ""
    enabled_channels: frozenset = frozenset({EMAIL})
    delivery_enabled: bool = False
    max_attempts: int = 5
    max_open_proposals: int = 5


@dataclass(frozen=True)
class Result:
    status: str                   # recorded | duplicate | no_change
    action_key: str = ""
    message: str = ""
    queued: int = 0               # notifications queued for delivery
    unroutable: int = 0
    ref: str = ""                 # id of the created record, when there is one


@dataclass(frozen=True)
class EventView:
    event: Event
    roles: frozenset
    is_reviewer: bool
    items: list
    members: list
    submittable: frozenset = frozenset()   # item_ids this identity may submit


def _h(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowService:
    def __init__(self, store, files, config: Config, channels: dict | None = None,
                 clock: Callable[[], datetime] = _utcnow):
        self.store, self.files, self.config = store, files, config
        self.channels = channels or {}
        self.clock = clock

    # ── helpers ───────────────────────────────────────────────────────────────
    def _audit(self, key, event_id, action, actor: Actor, role, item_id="", frm="", to="", note=""):
        return AuditEvent(audit_id=uuid.uuid4().hex, action_key=key, event_id=event_id, action=action,
                          actor_subject=actor.subject, actor_role=ADMIN if actor.is_admin else role,
                          created_at=self.clock(), item_id=item_id, from_status=frm, to_status=to,
                          note=note[:4000])

    def _link(self, event_id, item_id=""):
        base = self.config.app_base_url.rstrip("/")
        return f"{base}/workspace?event={event_id}" + (f"&item={item_id}" if item_id else "")

    def _compose(self, event: Event, action_required, item: Item | None, note=""):
        lines = [f"Event: {event.name}"]
        if item:
            lines.append(f"Item: {item.title}")
        lines.append(f"Action required: {action_required}")
        if item and item.due_date:
            lines.append(f"Deadline: {item.due_date.isoformat()}")
        if note:
            lines.append(f"Note from the program team: {note}")
        lines += ["", f"Open your workspace: {self._link(event.event_id, item.item_id if item else '')}",
                  "", "Sign in with your Google account to view details. Files are never attached to this message."]
        return f"[Community Voices] {event.name}: {action_required}"[:200], "\n".join(lines)

    def _notifications(self, action, key, event, members, actor: Actor, item=None, target=None, note=""):
        now = self.clock()
        out, seen = [], set()
        for r in rules.route(action, members=members, actor_subject=actor.subject, item=item, target=target,
                             actor_email=actor.email):
            if r.unroutable_reason:
                subj, body = self._compose(event, f"Unroutable: {r.rule}", item)
                out.append(Notification(
                    notification_id=_h(key, r.rule, UNROUTABLE), action_key=key, event_id=event.event_id,
                    rule=r.rule, channel=NO_CHANNEL, status=UNROUTABLE, created_at=now, next_attempt_at=now,
                    item_id=item.item_id if item else "", subject=subj, body=body,
                    link=self._link(event.event_id), last_error=r.unroutable_reason,
                    max_attempts=self.config.max_attempts, updated_at=now))
                continue
            for rec in r.recipients:
                pairs = rules.channels_for(rec.member, set(self.config.enabled_channels))
                if not pairs:
                    pairs = [(NO_CHANNEL, "")]
                for channel, address in pairs:
                    nid = _h(key, rec.member.member_id, channel)   # one ping per person+channel per action
                    if nid in seen:
                        continue
                    seen.add(nid)
                    subj, body = self._compose(event, rec.action_required, item, note)
                    out.append(Notification(
                        notification_id=nid, action_key=key, event_id=event.event_id, rule=r.rule,
                        channel=channel, status=PENDING if channel != NO_CHANNEL else UNROUTABLE,
                        created_at=now, next_attempt_at=now, item_id=item.item_id if item else "",
                        recipient_member_id=rec.member.member_id, recipient_role=rec.member.role,
                        address=address, subject=subj, body=body,
                        link=self._link(event.event_id, item.item_id if item else ""),
                        deadline=item.due_date if item else None, max_attempts=self.config.max_attempts,
                        last_error="" if channel != NO_CHANNEL else "Recipient has no configured channel.",
                        updated_at=now))
        return out

    def _commit(self, key, cs: ChangeSet, message="", ref="") -> Result:
        try:
            self.store.apply(cs)
        except DuplicateAction:
            return Result("duplicate", key, "Already recorded.", ref=ref)
        q = sum(1 for n in cs.notifications if n.status == PENDING)
        u = sum(1 for n in cs.notifications if n.status == UNROUTABLE)
        return Result("recorded", key, message, q, u, ref)

    def _require_admin(self, actor: Actor):
        if not actor.is_admin:
            raise NotAuthorized("Administrators only.")

    def _event_ctx(self, actor: Actor, event_id):
        event = self.store.get_event(event_id)
        members = self.store.list_members(event_id=event_id)
        if event is None or not authz.can_view_event(actor.subject, actor.is_admin, event_id, members):
            raise NotAuthorized("You do not have access to this event.")
        return event, members

    def _item_ctx(self, actor: Actor, item_id):
        item = self.store.get_item(item_id)
        if item is None:
            raise NotAuthorized("You do not have access to this item.")
        event, members = self._event_ctx(actor, item.event_id)
        if not authz.can_see_item(actor.subject, actor.is_admin, item, members):
            raise NotAuthorized("You do not have access to this item.")
        return item, event, members

    def _new_items(self, event_id, party, member_id="", due=None):
        table = rules.SPEAKER_ITEMS if party == SPEAKER else rules.VENDOR_ITEMS
        return [Item(item_id=uuid.uuid4().hex, event_id=event_id, item_type=t, party=party, title=spec[0],
                     due_date=due, assignee_member_id=member_id,
                     vendor_visible=party == SPEAKER and t in rules.VENDOR_VISIBLE_DEFAULT,
                     speaker_action=party == VENDOR and t in rules.SPEAKER_ACTION_DEFAULT,
                     updated_at=self.clock()) for t, spec in table.items()]

    # ── identity binding ──────────────────────────────────────────────────────
    def bind_invites(self, actor: Actor) -> int:
        """Bind INVITED rows for this verified email to the signed-in subject (once each)."""
        bound = 0
        for m in self.store.list_members(email=actor.email):
            if m.status != INVITED or m.subject:
                continue
            key = _h("bind", m.member_id)
            new = replace(m, status=ACTIVE, subject=actor.subject, bound_at=self.clock())
            cs = ChangeSet(audit=[self._audit(key, m.event_id, "INVITE_ACCEPTED", Actor(actor.subject, actor.email),
                                              m.role, note=f"member {m.member_id}")],
                           member_updates=[MemberUpdate(new, INVITED)])
            try:
                self.store.apply(cs)
                bound += 1
            except (DuplicateAction, ConcurrentModification):
                pass
        return bound

    # ── reads ─────────────────────────────────────────────────────────────────
    def my_events(self, actor: Actor) -> list[Event]:
        if actor.is_admin:
            return self.store.list_events()
        ids = {m.event_id for m in self.store.list_members(subject=actor.subject) if m.status == ACTIVE}
        return [e for e in (self.store.get_event(i) for i in sorted(ids)) if e]

    def event_view(self, actor: Actor, event_id) -> EventView:
        event, members = self._event_ctx(actor, event_id)
        roles = frozenset(authz.active_roles(actor.subject, event_id, members))
        reviewer = authz.can_review(actor.subject, actor.is_admin, event_id, members)
        items = [i for i in self.store.list_items(event_id)
                 if authz.can_see_item(actor.subject, actor.is_admin, i, members)]
        if reviewer:
            visible = [m for m in members if m.status != REMOVED]
        else:
            visible = [m for m in members if m.role in PROGRAM_ROLES and m.status in (ACTIVE, INVITED)]
            if VENDOR in roles:
                visible += authz.visible_speakers_for_vendor(event_id, members)
            visible += [m for m in members if m.subject == actor.subject and m.status == ACTIVE]
        return EventView(event, roles, reviewer, items, visible,
                         frozenset(i.item_id for i in items if authz.can_submit(actor.subject, i, members)))

    def history(self, actor: Actor, item_id):
        item, _, members = self._item_ctx(actor, item_id)
        readable = authz.readable_versions(actor.subject, actor.is_admin, item, members)
        versions = [v for v in self.store.list_versions(item_id) if v.version in readable]
        audit = []
        if authz.can_review(actor.subject, actor.is_admin, item.event_id, members) or \
                authz.can_submit(actor.subject, item, members):
            audit = [a for a in self.store.list_audit(event_id=item.event_id, limit=1000) if a.item_id == item_id]
        return versions, audit

    def download(self, actor: Actor, item_id, version: int):
        item, _, members = self._item_ctx(actor, item_id)
        if not authz.can_read_version(actor.subject, actor.is_admin, item, version, members):
            raise NotAuthorized("You do not have access to this file.")
        v = next((x for x in self.store.list_versions(item_id) if x.version == version), None)
        if v is None or not v.file_path:
            raise InvalidAction("This version has no file.")
        return v.file_name, self.files.get(v.file_path)

    # ── vendor / speaker actions ──────────────────────────────────────────────
    def propose_event(self, actor: Actor, *, name, start_date, city, details: dict, token) -> Result:
        name = (name or "").strip()
        if not name:
            raise InvalidAction("Event name is required.")
        key = _h("propose", actor.subject, token)
        if self.store.action_exists(key):
            return Result("duplicate", key, "Already recorded.")
        mine = [m for m in self.store.list_members(subject=actor.subject) if m.role == VENDOR]
        open_props = [e for e in (self.store.get_event(m.event_id) for m in mine)
                      if e and e.status == PROPOSED and e.created_by == actor.subject]
        if len(open_props) >= self.config.max_open_proposals:
            raise InvalidAction("You have too many proposals awaiting review.")
        now = self.clock()
        event = Event(f"EV-{uuid.uuid4().hex[:12].upper()}", name[:500], PROPOSED, start_date,
                      (city or "")[:200], created_by=actor.subject, created_at=now)
        me = Member(uuid.uuid4().hex, event.event_id, VENDOR, actor.email, ACTIVE, subject=actor.subject,
                    created_by=actor.subject, created_at=now, bound_at=now)
        items = self._new_items(event.event_id, VENDOR)
        details_item = next(i for i in items if i.item_type == "event_details")
        text_json = json.dumps(details or {}, sort_keys=True)
        content = _h(text_json, "")
        items = [replace(i, status=SUBMITTED, current_version=1) if i is details_item else i for i in items]
        version = ItemVersion(details_item.item_id, 1, actor.subject, VENDOR, now, content, key, text_json)
        members = [me]
        notes = self._notifications("EVENT_PROPOSED", key, event, members, actor)
        cs = ChangeSet(audit=[self._audit(key, event.event_id, "EVENT_PROPOSED", actor, VENDOR, to=PROPOSED)],
                       events=[event], members=members, items=items, versions=[version], notifications=notes)
        return self._commit(key, cs, "Event proposal submitted.", event.event_id)

    def submit_item(self, actor: Actor, item_id, *, text: dict | None = None,
                    upload: tuple[str, bytes] | None = None, token: str) -> Result:
        item = self.store.get_item(item_id)
        if item is None:
            raise NotAuthorized("You do not have access to this item.")
        event, members = self._event_ctx(actor, item.event_id)
        if not authz.can_submit(actor.subject, item, members):
            raise NotAuthorized("You cannot submit this item.")
        rules.check_submit(item)
        _, kind, exts = rules.item_spec(item)
        text = {k: (v or "").strip() for k, v in (text or {}).items()}
        if kind == "text" and not any(text.values()):
            raise InvalidAction("Please fill in the requested details.")
        file_sha, fname, data = "", "", b""
        if kind == "file":
            if not upload:
                raise InvalidAction("Please choose a file to upload.")
            fname, data = upload
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext not in exts:
                raise InvalidAction(f"Accepted file types: {', '.join(exts)}.")
            if not data or len(data) > rules.MAX_FILE_BYTES:
                raise InvalidAction("File is empty or larger than 25 MB.")
            file_sha = hashlib.sha256(data).hexdigest()
        text_json = json.dumps(text, sort_keys=True)
        content = _h(text_json, file_sha)
        versions = self.store.list_versions(item_id)
        if versions and versions[-1].content_sha256 == content and item.status in (SUBMITTED, APPROVED):
            return Result("no_change", "", "This is identical to your current submission; nothing changed.")
        key = _h("submit", item_id, token, content)
        if self.store.action_exists(key):
            return Result("duplicate", key, "Already recorded.")
        n = item.current_version + 1
        path = ""
        if kind == "file":
            path = object_path(item.event_id, item_id, n, file_sha, fname)
            self.files.put(path, data)    # before the transaction; failure records nothing
        now = self.clock()
        role = SPEAKER if item.party == SPEAKER else VENDOR
        new_item = replace(item, status=SUBMITTED, current_version=n, updated_at=now)
        version = ItemVersion(item_id, n, actor.subject, role, now, content, key, text_json,
                              path, fname[:500], file_sha, len(data))
        cs = ChangeSet(
            audit=[self._audit(key, item.event_id, "ITEM_SUBMITTED", actor, role, item_id, item.status,
                               SUBMITTED, "revision" if n > 1 else "first submission")],
            item_updates=[ItemUpdate(new_item, item.current_version)], versions=[version],
            notifications=self._notifications("ITEM_SUBMITTED", key, event, members, actor, item=new_item))
        return self._commit(key, cs, f"Submitted version {n}.", item_id)

    # ── review ────────────────────────────────────────────────────────────────
    def review_item(self, actor: Actor, item_id, *, version: int, approve: bool, note: str = "") -> Result:
        item = self.store.get_item(item_id)
        if item is None:
            raise NotAuthorized("You do not have access to this item.")
        event, members = self._event_ctx(actor, item.event_id)
        if not authz.can_review(actor.subject, actor.is_admin, item.event_id, members):
            raise NotAuthorized("Only the program owner can review.")
        rules.check_review(item, version)
        note = (note or "").strip()
        if not approve and not note:
            raise InvalidAction("Explain what needs to change.")
        status = APPROVED if approve else CHANGES_REQUESTED
        key = _h("review", item_id, version)
        new_item = replace(item, status=status, updated_at=self.clock(),
                           approved_version=version if approve else item.approved_version)
        action = "ITEM_APPROVED" if approve else "CHANGES_REQUESTED"
        role = next(iter(authz.active_roles(actor.subject, item.event_id, members) & set(PROGRAM_ROLES)), OWNER)
        cs = ChangeSet(audit=[self._audit(key, item.event_id, action, actor, role, item_id, item.status, status, note)],
                       item_updates=[ItemUpdate(new_item, item.current_version)],
                       notifications=self._notifications(action, key, event, members, actor, item=new_item,
                                                         note="" if approve else note))
        return self._commit(key, cs, "Approved." if approve else "Changes requested.", item_id)

    def update_item_settings(self, actor: Actor, item_id, *, due_date: date | None, vendor_visible: bool,
                             speaker_action: bool, token) -> Result:
        item = self.store.get_item(item_id)
        if item is None:
            raise NotAuthorized("You do not have access to this item.")
        event, members = self._event_ctx(actor, item.event_id)
        if not authz.can_review(actor.subject, actor.is_admin, item.event_id, members):
            raise NotAuthorized("Only the program owner can change item settings.")
        new_item = replace(item, due_date=due_date, vendor_visible=vendor_visible and item.party == SPEAKER,
                           speaker_action=speaker_action and item.party == VENDOR, updated_at=self.clock())
        if new_item == replace(item, updated_at=new_item.updated_at):
            return Result("no_change", "", "No changes.")
        key = _h("settings", item_id, token)
        notes = []
        if new_item.due_date != item.due_date:
            notes = self._notifications("DEADLINE_CHANGED", key, event, members, actor, item=new_item)
        cs = ChangeSet(audit=[self._audit(key, item.event_id, "ITEM_SETTINGS", actor, OWNER, item_id,
                                          note=f"due={due_date} vendor_visible={new_item.vendor_visible} "
                                               f"speaker_action={new_item.speaker_action}")],
                       item_updates=[ItemUpdate(new_item, item.current_version)], notifications=notes)
        return self._commit(key, cs, "Saved.", item_id)

    # ── admin: events, people, routing ────────────────────────────────────────
    def create_event(self, actor: Actor, *, name, start_date, city, token, legacy_event_id="") -> Result:
        self._require_admin(actor)
        if not (name or "").strip():
            raise InvalidAction("Event name is required.")
        key = _h("create_event", token)
        event = Event(f"EV-{uuid.uuid4().hex[:12].upper()}", name.strip()[:500], EVENT_ACTIVE, start_date,
                      (city or "").strip()[:200], legacy_event_id, actor.subject, self.clock())
        cs = ChangeSet(audit=[self._audit(key, event.event_id, "EVENT_CREATED", actor, ADMIN, to=EVENT_ACTIVE)],
                       events=[event])
        return self._commit(key, cs, "Event created.", event.event_id)

    def set_event_status(self, actor: Actor, event_id, status, token) -> Result:
        self._require_admin(actor)
        if status not in EVENT_STATUSES:
            raise InvalidAction("Unknown status.")
        event, members = self._event_ctx(actor, event_id)
        if event.status == status:
            return Result("no_change", "", "No changes.")
        key = _h("event_status", event_id, token)
        cs = ChangeSet(audit=[self._audit(key, event_id, "EVENT_STATUS_CHANGED", actor, ADMIN,
                                          frm=event.status, to=status)],
                       event_updates=[replace(event, status=status)],
                       notifications=self._notifications("EVENT_STATUS_CHANGED", key, replace(event, status=status),
                                                         members, actor))
        return self._commit(key, cs, f"Event is now {status}.", event_id)

    def invite(self, actor: Actor, event_id, *, role, email, display_name="", slack_user_id="",
               due_date: date | None = None, token) -> Result:
        """Assign a speaker, vendor, owner, or delegate to an event (admin only)."""
        self._require_admin(actor)
        event, members = self._event_ctx(actor, event_id)
        email = (email or "").strip().lower()
        if role not in (OWNER, DELEGATE, SPEAKER, VENDOR):
            raise InvalidAction("Unknown role.")
        if not EMAIL_RE.match(email):
            raise InvalidAction("Enter a valid email address.")
        if slack_user_id and role not in PROGRAM_ROLES:
            raise InvalidAction("Slack notifications are for internal program owners only.")
        key = _h("invite", event_id, role, email, token)
        if self.store.action_exists(key):
            return Result("duplicate", key, "Already recorded.")
        now = self.clock()
        # A subject already verified for this exact email elsewhere can be bound directly.
        known = next((m.subject for m in self.store.list_members(email=email) if m.status == ACTIVE and m.subject), "")
        suggested = next((m for m in members if m.role == role and m.email == email and m.status == SUGGESTED), None)
        member = Member(suggested.member_id if suggested else uuid.uuid4().hex, event_id, role, email,
                        ACTIVE if known else INVITED, subject=known,
                        display_name=display_name.strip()[:300], slack_user_id=slack_user_id.strip()[:64],
                        created_by=actor.subject, created_at=now, bound_at=now if known else None)
        items = []
        if role == SPEAKER:
            items = self._new_items(event_id, SPEAKER, member.member_id, due_date)
        elif role == VENDOR and not any(i.party == VENDOR for i in self.store.list_items(event_id)):
            items = self._new_items(event_id, VENDOR, due=due_date)
        action = {SPEAKER: "SPEAKER_ASSIGNED", VENDOR: "VENDOR_ASSIGNED"}.get(role, "OWNER_ASSIGNED")
        cs = ChangeSet(audit=[self._audit(key, event_id, action, actor, ADMIN, note=f"{role} {email}")],
                       members=[] if suggested else [member],
                       member_updates=[MemberUpdate(member, SUGGESTED)] if suggested else [], items=items,
                       notifications=self._notifications(action, key, event,
                                                         [m for m in members if m is not suggested] + [member],
                                                         actor, target=member))
        return self._commit(key, cs, f"{role.title()} assigned.", member.member_id)

    def update_routing(self, actor: Actor, member_id, *, email, slack_user_id, display_name, token) -> Result:
        self._require_admin(actor)
        m = next((x for x in self.store.list_members() if x.member_id == member_id), None)
        if m is None:
            raise InvalidAction("Member not found.")
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise InvalidAction("Enter a valid email address.")
        if slack_user_id and m.role not in PROGRAM_ROLES:
            raise InvalidAction("Slack notifications are for internal program owners only.")
        new = replace(m, email=email, slack_user_id=(slack_user_id or "").strip()[:64],
                      display_name=(display_name or "").strip()[:300])
        if new == m:
            return Result("no_change", "", "No changes.")
        key = _h("routing", member_id, token)
        cs = ChangeSet(audit=[self._audit(key, m.event_id, "ROUTING_UPDATED", actor, ADMIN,
                                          note=f"member {member_id}: email/slack updated")],
                       member_updates=[MemberUpdate(new, m.status)])
        return self._commit(key, cs, "Routing updated.", member_id)

    def remove_member(self, actor: Actor, member_id, token) -> Result:
        self._require_admin(actor)
        m = next((x for x in self.store.list_members() if x.member_id == member_id), None)
        if m is None or m.status == REMOVED:
            return Result("no_change", "", "Nothing to remove.")
        key = _h("remove", member_id)
        cs = ChangeSet(audit=[self._audit(key, m.event_id, "MEMBER_REMOVED", actor, ADMIN, frm=m.status, to=REMOVED,
                                          note=f"{m.role} {m.email}")],
                       member_updates=[MemberUpdate(replace(m, status=REMOVED), m.status)])
        return self._commit(key, cs, "Removed.", member_id)

    def confirm_speaker(self, actor: Actor, member_id) -> Result:
        self._require_admin(actor)
        m = next((x for x in self.store.list_members() if x.member_id == member_id), None)
        if m is None or m.role != SPEAKER or m.status != ACTIVE:
            raise InvalidAction("Only a signed-in speaker can be confirmed to vendors.")
        if m.shared_with_vendor:
            return Result("no_change", "", "Already confirmed.")
        event, members = self._event_ctx(actor, m.event_id)
        key = _h("confirm", member_id)
        cs = ChangeSet(audit=[self._audit(key, m.event_id, "SPEAKER_CONFIRMED", actor, ADMIN, note=m.email)],
                       member_updates=[MemberUpdate(replace(m, shared_with_vendor=True), m.status)],
                       notifications=self._notifications("SPEAKER_CONFIRMED", key, event, members, actor))
        return self._commit(key, cs, "Speaker confirmed to vendor.", member_id)

    # ── admin: queue and notifications ────────────────────────────────────────
    def admin_queue(self, actor: Actor):
        self._require_admin(actor)
        events = {e.event_id: e for e in self.store.list_events()}
        items = self.store.list_items(None)
        return {
            "events": events,
            "to_review": [i for i in items if i.status == SUBMITTED],
            "outstanding": [i for i in items if i.status in (MISSING, CHANGES_REQUESTED)],
            "notifications": self.store.list_notifications(statuses=ATTENTION),
            "no_owner": [e for e in events.values() if e.status != "CLOSED" and not any(
                m.role in PROGRAM_ROLES and m.status in (ACTIVE, INVITED)
                for m in self.store.list_members(event_id=e.event_id))],
        }

    def audit_log(self, actor: Actor, limit: int = 200):
        self._require_admin(actor)
        return self.store.list_audit(limit=limit)

    def _get_notification(self, nid):
        return self.store.get_notification(nid)

    def retry_notification(self, actor: Actor, nid, token) -> Result:
        self._require_admin(actor)
        n = self._get_notification(nid)
        if n is None or n.status not in (DEAD, UNCERTAIN, RETRY):
            raise InvalidAction("Only failed, uncertain, or waiting notifications can be retried.")
        key = _h("retry", nid, token)
        now = self.clock()
        cs = ChangeSet(audit=[self._audit(key, n.event_id, "NOTIFICATION_RETRY", actor, ADMIN, n.item_id,
                                          n.status, PENDING, f"notification {nid[:12]}")],
                       notification_updates=[(replace(n, status=PENDING, attempts=0, next_attempt_at=now,
                                                      claim_token="", updated_at=now), n.status)])
        return self._commit(key, cs, "Queued for retry.", nid)

    def cancel_notification(self, actor: Actor, nid, token) -> Result:
        self._require_admin(actor)
        n = self._get_notification(nid)
        if n is None or n.status not in ATTENTION:
            raise InvalidAction("This notification cannot be cancelled.")
        key = _h("cancel", nid, token)
        cs = ChangeSet(audit=[self._audit(key, n.event_id, "NOTIFICATION_CANCELLED", actor, ADMIN, n.item_id,
                                          n.status, CANCELLED, f"notification {nid[:12]}")],
                       notification_updates=[(replace(n, status=CANCELLED, updated_at=self.clock()), n.status)])
        return self._commit(key, cs, "Cancelled.", nid)

    def reroute(self, actor: Actor, nid, token) -> Result:
        """Recompute recipients for an UNROUTABLE notification from the current routing record."""
        self._require_admin(actor)
        n = self._get_notification(nid)
        if n is None or n.status != UNROUTABLE:
            raise InvalidAction("Only unroutable notifications can be re-routed.")
        original = next((a for a in self.store.list_audit(event_id=n.event_id, limit=100000)
                         if a.action_key == n.action_key), None)
        if original is None:
            raise InvalidAction("Original action not found.")
        event, members = self._event_ctx(actor, n.event_id)
        item = self.store.get_item(n.item_id) if n.item_id else None
        orig_actor = Actor(original.actor_subject, "")
        target = next((m for m in members if m.member_id == n.recipient_member_id), None)
        fresh = [x for x in self._notifications(original.action, n.action_key, event, members, orig_actor,
                                                item=item, target=target)
                 if x.rule == n.rule and x.status == PENDING]
        if not fresh:
            raise InvalidAction("Still no recipient with a configured channel. Assign an owner first.")
        existing = {x.notification_id for x in self.store.list_notifications(action_key=n.action_key)}
        fresh = [x for x in fresh if x.notification_id not in existing]
        key = _h("reroute", nid, token)
        cs = ChangeSet(audit=[self._audit(key, n.event_id, "NOTIFICATION_REROUTED", actor, ADMIN, n.item_id,
                                          UNROUTABLE, CANCELLED, f"{len(fresh)} new notification(s)")],
                       notifications=fresh,
                       notification_updates=[(replace(n, status=CANCELLED, last_error="Re-routed",
                                                      updated_at=self.clock()), UNROUTABLE)])
        return self._commit(key, cs, f"Re-routed to {len(fresh)} recipient channel(s).", nid)

    # ── delivery ──────────────────────────────────────────────────────────────
    def dispatch(self, action_key: str | None = None, limit: int = 20) -> dict:
        return _dispatch(self.store, self.channels, now=self.clock(), enabled=self.config.delivery_enabled,
                         limit=limit, action_key=action_key)
