"""Backfill from legacy sheet rows: no access or routing is inferred from legacy emails."""
from datetime import datetime

import pytest

from conftest import ABA, VND, make_service, tok
from workflow.backfill import plan
from workflow.models import DuplicateAction, NotAuthorized

EVENTS = [
    {"event_id": "EV-2026-AAAA1111", "status": "Approved", "event_name": "Lagos Data Day",
     "event_start": "2026-11-20", "event_city": "Lagos", "organizer_email": VND.email, "organizer_name": "Org"},
    {"event_id": "EV-2026-BBBB2222", "status": "Pending", "event_name": "Bad date", "event_start": "soon",
     "organizer_email": "not-an-email"},
    {"event_id": "", "event_name": "No id"},
]
APPS = [{"email": "Speaker.Legacy@Example.com", "matched_event": "EV-2026-AAAA1111"}]


def test_backfill_creates_events_with_suggested_members_only():
    svc, email, slack, clock = make_service()
    changesets, report = plan(EVENTS, APPS, now=datetime(2026, 10, 1), actor_subject=ABA.subject)
    assert report == {"events": 2, "skipped_no_id": 1, "suggested_vendors": 1, "suggested_speakers": 1,
                      "unparsed_dates": 1}
    for cs in changesets:
        svc.store.apply(cs)
    for cs in plan(EVENTS, APPS, now=datetime(2026, 10, 2), actor_subject=ABA.subject)[0]:
        with pytest.raises(DuplicateAction):        # idempotent re-run
            svc.store.apply(cs)

    assert svc.store.list_notifications() == []
    assert svc.bind_invites(VND) == 0               # SUGGESTED rows are not invitations
    assert svc.my_events(VND) == []
    ev = next(e for e in svc.store.list_events() if e.legacy_event_id == "EV-2026-AAAA1111")
    with pytest.raises(NotAuthorized):
        svc.event_view(VND, ev.event_id)
    assert ev.event_id in {e.event_id for e in svc.admin_queue(ABA)["no_owner"]}

    # Admin confirms the suggestion: the row upgrades to an invite and the vendor is notified.
    r = svc.invite(ABA, ev.event_id, role="VENDOR", email=VND.email, token=tok())
    assert [n.address for n in svc.store.list_notifications(action_key=r.action_key)] == [VND.email]
    assert len([m for m in svc.store.list_members(event_id=ev.event_id) if m.email == VND.email]) == 1
    assert svc.bind_invites(VND) == 1 and [e.event_id for e in svc.my_events(VND)] == [ev.event_id]
