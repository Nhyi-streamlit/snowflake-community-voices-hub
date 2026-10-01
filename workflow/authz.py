"""Event-level authorization. Every service read and write goes through these checks.

Identity is the verified OIDC subject. Access comes only from ACTIVE EVENT_MEMBERS rows bound
to that subject, or from the admin subject allowlist held in managed secrets.
"""
from __future__ import annotations

from workflow.models import ACTIVE, PROGRAM_ROLES, SPEAKER, VENDOR, Item, Member


def active_roles(subject: str, event_id: str, members: list[Member]) -> set[str]:
    return {m.role for m in members
            if m.event_id == event_id and m.status == ACTIVE and subject and m.subject == subject}


def my_member(subject: str, event_id: str, role: str, members: list[Member]) -> Member | None:
    for m in members:
        if m.event_id == event_id and m.role == role and m.status == ACTIVE and subject and m.subject == subject:
            return m
    return None


def can_view_event(subject, is_admin, event_id, members) -> bool:
    return is_admin or bool(active_roles(subject, event_id, members))


def can_review(subject, is_admin, event_id, members) -> bool:
    return is_admin or bool(active_roles(subject, event_id, members) & set(PROGRAM_ROLES))


def can_submit(subject, item: Item, members) -> bool:
    if item.party == SPEAKER:
        m = my_member(subject, item.event_id, SPEAKER, members)
        return m is not None and m.member_id == item.assignee_member_id
    return my_member(subject, item.event_id, VENDOR, members) is not None


def readable_versions(subject, is_admin, item: Item, members) -> set[int]:
    """Version numbers this identity may read (empty set = item hidden).

    Submitters and reviewers see full history. Vendors see only the approved version of
    vendor-visible speaker items. Speakers see vendor items flagged speaker_action.
    """
    if can_review(subject, is_admin, item.event_id, members) or can_submit(subject, item, members):
        return set(range(1, item.current_version + 1))
    roles = active_roles(subject, item.event_id, members)
    if VENDOR in roles and item.party == SPEAKER and item.vendor_visible and item.approved_version:
        return {item.approved_version}
    if SPEAKER in roles and item.party == VENDOR and item.speaker_action:
        return set(range(1, item.current_version + 1))
    return set()


def can_see_item(subject, is_admin, item: Item, members) -> bool:
    if can_review(subject, is_admin, item.event_id, members) or can_submit(subject, item, members):
        return True
    if SPEAKER in active_roles(subject, item.event_id, members) and item.party == VENDOR and item.speaker_action:
        return True
    return bool(readable_versions(subject, is_admin, item, members))


def can_read_version(subject, is_admin, item: Item, version: int, members) -> bool:
    return version in readable_versions(subject, is_admin, item, members)


def visible_speakers_for_vendor(event_id, members) -> list[Member]:
    return [m for m in members if m.event_id == event_id and m.role == SPEAKER
            and m.shared_with_vendor and m.status in (ACTIVE,)]
