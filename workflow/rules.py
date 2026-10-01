"""Deterministic workflow rules: required items, status transitions, and notification routing.

Recipients are computed only from explicit EVENT_MEMBERS records. Nothing here guesses
recipients from free text, typed emails, or model output.
"""
from __future__ import annotations

from dataclasses import dataclass

from workflow.models import (
    ACTIVE, APPROVED, CHANGES_REQUESTED, DELEGATE, EMAIL, INVITED, MISSING, OWNER,
    PROGRAM_ROLES, SLACK, SPEAKER, SUBMITTED, VENDOR, InvalidAction, Item, Member,
)

# item_type -> (title, input kind, accepted file types or None)
SPEAKER_ITEMS = {
    "profile":      ("Profile (name, title, company, links)", "text", None),
    "bio":          ("Speaker bio", "text", None),
    "headshot":     ("Headshot", "file", ["png", "jpg", "jpeg", "webp"]),
    "talk_details": ("Talk title and abstract", "text", None),
    "slides":       ("Slides", "file", ["pdf", "pptx", "key"]),
    "availability": ("Availability", "text", None),
}
VENDOR_ITEMS = {
    "event_details":   ("Event details", "text", None),
    "logistics":       ("Logistics (venue, AV, schedule)", "text", None),
    "speaker_request": ("Speaker request", "text", None),
    "materials":       ("Event materials", "file", ["pdf", "pptx", "png", "jpg", "jpeg", "docx"]),
}
# Defaults set at creation; Aba can change them per item in Workflow admin.
VENDOR_VISIBLE_DEFAULT = {"profile", "bio", "headshot", "talk_details", "slides"}
SPEAKER_ACTION_DEFAULT = {"logistics"}
MAX_FILE_BYTES = 25 * 1024 * 1024


def item_spec(item: Item):
    table = SPEAKER_ITEMS if item.party == SPEAKER else VENDOR_ITEMS
    return table[item.item_type]


# ── Status transitions ───────────────────────────────────────────────────────

SUBMITTABLE_FROM = {MISSING, SUBMITTED, CHANGES_REQUESTED, APPROVED}
REVIEWABLE_FROM = {SUBMITTED}


def check_submit(item: Item) -> None:
    if item.status not in SUBMITTABLE_FROM:
        raise InvalidAction(f"Cannot submit an item in status {item.status}.")


def check_review(item: Item, reviewed_version: int) -> None:
    if item.status not in REVIEWABLE_FROM:
        raise InvalidAction(f"Only submitted items can be reviewed (status is {item.status}).")
    if reviewed_version != item.current_version:
        raise InvalidAction("A newer version was submitted. Reload before reviewing.")


# ── Routing ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Recipient:
    member: Member
    action_required: str


@dataclass(frozen=True)
class Route:
    rule: str
    recipients: tuple[Recipient, ...]
    unroutable_reason: str = ""     # set when a required group is empty


def _routable(members, role):
    return [m for m in members if m.role == role and m.status in (ACTIVE, INVITED) and m.email]


def _owners(members):
    return [m for m in members if m.role in PROGRAM_ROLES and m.status in (ACTIVE, INVITED) and m.email]


def route(action: str, *, members: list[Member], actor_subject: str, item: Item | None = None,
          target: Member | None = None, actor_email: str = "") -> list[Route]:
    """Return the routes for an action. Each route is one rule with its recipient group.

    Rules (actor is never notified of their own action):
      ITEM_SUBMITTED (speaker)   -> owners: review
      ITEM_SUBMITTED (vendor)    -> owners: review; + speakers if item.speaker_action
      EVENT_PROPOSED             -> owners: review proposal
      ITEM_APPROVED              -> submitting party; + vendors if speaker item is vendor_visible
      CHANGES_REQUESTED          -> submitting party: revise
      SPEAKER_ASSIGNED / VENDOR_ASSIGNED -> target member
      SPEAKER_CONFIRMED          -> vendors: FYI
      OWNER_ASSIGNED             -> target member (new owner/delegate)
      DEADLINE_CHANGED           -> submitting party
    """
    def party(it: Item):
        if it.party == SPEAKER:
            return [m for m in _routable(members, SPEAKER) if m.member_id == it.assignee_member_id]
        return _routable(members, VENDOR)

    groups: list[tuple[str, list[Member], str, bool]] = []  # rule, members, action text, required
    if action == "ITEM_SUBMITTED":
        groups.append(("submission_to_owner", _owners(members), f"Review {item.title}", True))
        if item.party == VENDOR and item.speaker_action:
            groups.append(("vendor_item_to_speaker", _routable(members, SPEAKER),
                           f"Action needed: {item.title}", False))
    elif action == "EVENT_PROPOSED":
        groups.append(("proposal_to_owner", _owners(members), "Review new event proposal", True))
    elif action == "ITEM_APPROVED":
        groups.append(("approval_to_submitter", party(item), "None. Approved.", False))
        if item.party == SPEAKER and item.vendor_visible:
            groups.append(("approved_material_to_vendor", _routable(members, VENDOR),
                           f"New approved material: {item.title}", False))
    elif action == "CHANGES_REQUESTED":
        groups.append(("changes_to_submitter", party(item), f"Revise {item.title}", True))
    elif action in ("SPEAKER_ASSIGNED", "VENDOR_ASSIGNED"):
        groups.append(("assignment_to_assignee", [target], "Complete your checklist", True))
    elif action == "SPEAKER_CONFIRMED":
        groups.append(("confirmed_speaker_to_vendor", _routable(members, VENDOR),
                       "Speaker confirmed", False))
    elif action == "OWNER_ASSIGNED":
        groups.append(("ownership_to_owner", [target], "You are now responsible for this event", True))
    elif action == "DEADLINE_CHANGED":
        groups.append(("deadline_to_submitter", party(item), f"New deadline for {item.title}", False))
    elif action == "EVENT_STATUS_CHANGED":
        groups.append(("event_status_to_participants",
                       _routable(members, SPEAKER) + _routable(members, VENDOR), "FYI: event status changed", False))
    else:
        raise ValueError(f"No routing rule for action {action}")

    routes = []
    for rule, group, text, required in groups:
        recips = tuple(Recipient(m, text) for m in group
                       if m is not None and not (actor_subject and m.subject == actor_subject)
                       and not (actor_email and m.email == actor_email))
        reason = ""
        if required and not group:
            reason = "No program owner is assigned to this event." if "owner" in rule else "No recipient on record."
        routes.append(Route(rule, recips, reason))
    return routes


def channels_for(member: Member, enabled: set[str]) -> list[tuple[str, str]]:
    """(channel, address) pairs. Slack is internal-only: program roles with an admin-set Slack ID."""
    out = []
    if EMAIL in enabled and member.email:
        out.append((EMAIL, member.email))
    if SLACK in enabled and member.role in (OWNER, DELEGATE) and member.slack_user_id:
        out.append((SLACK, member.slack_user_id))
    return out
