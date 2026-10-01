"""Every routing rule in the matrix, plus missing-owner handling."""
from datetime import date

import pytest

from conftest import ABA, DELEG, SPK_A, SPK_B, VND, VND2, item_of, make_service, setup_event, tok
from workflow.models import InvalidAction


def outbox(svc, key):
    return sorted((n.recipient_role, n.channel, n.address, n.rule, n.status)
                  for n in svc.store.list_notifications(action_key=key))


def test_speaker_upload_routes_to_owner_and_delegate_only():
    svc, *_ = make_service()
    eid = setup_event(svc, with_delegate=True)
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    assert outbox(svc, r.action_key) == [
        ("DELEGATE", "EMAIL", DELEG.email, "submission_to_owner", "PENDING"),
        ("OWNER", "EMAIL", ABA.email, "submission_to_owner", "PENDING"),
        ("OWNER", "SLACK", "U_ABA", "submission_to_owner", "PENDING"),
    ]


def test_approval_vendor_visible_notifies_speaker_and_vendor(env):
    svc, *_, eid = env
    slides = item_of(svc, SPK_A, eid, "slides")
    svc.submit_item(SPK_A, slides.item_id, upload=("d.pdf", b"x"), token=tok())
    r = svc.review_item(ABA, slides.item_id, version=1, approve=True)
    assert outbox(svc, r.action_key) == [
        ("SPEAKER", "EMAIL", SPK_A.email, "approval_to_submitter", "PENDING"),
        ("VENDOR", "EMAIL", VND.email, "approved_material_to_vendor", "PENDING"),
    ]


def test_approval_not_vendor_visible_notifies_speaker_only(env):
    svc, *_, eid = env
    avail = item_of(svc, SPK_A, eid, "availability")
    svc.submit_item(SPK_A, avail.item_id, text={"availability": "Nov"}, token=tok())
    r = svc.review_item(ABA, avail.item_id, version=1, approve=True)
    assert outbox(svc, r.action_key) == [("SPEAKER", "EMAIL", SPK_A.email, "approval_to_submitter", "PENDING")]


def test_changes_requested_routes_to_submitter_with_note(env):
    svc, *_, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    r = svc.review_item(ABA, bio.item_id, version=1, approve=False, note="Please shorten to 100 words")
    rows = svc.store.list_notifications(action_key=r.action_key)
    assert [(n.recipient_role, n.address) for n in rows] == [("SPEAKER", SPK_A.email)]
    assert "Please shorten" in rows[0].body and "Revise Speaker bio" in rows[0].subject

    det = item_of(svc, VND, eid, "event_details")
    svc.submit_item(VND, det.item_id, text={"description": "x"}, token=tok())
    r2 = svc.review_item(ABA, det.item_id, version=1, approve=False, note="Add venue")
    assert [(n.recipient_role, n.address) for n in svc.store.list_notifications(action_key=r2.action_key)] == \
        [("VENDOR", VND.email)]


def test_vendor_upload_routes_to_owner_and_speaker_when_action_needed(env):
    svc, *_, eid = env
    logistics = item_of(svc, VND, eid, "logistics")
    r = svc.submit_item(VND, logistics.item_id, text={"logistics": "Hall B, 10am"}, token=tok())
    assert {(n.recipient_role, n.rule) for n in svc.store.list_notifications(action_key=r.action_key)} == {
        ("OWNER", "submission_to_owner"), ("SPEAKER", "vendor_item_to_speaker")}

    req = item_of(svc, VND, eid, "speaker_request")
    r2 = svc.submit_item(VND, req.item_id, text={"request": "Need a dbt talk"}, token=tok())
    assert {n.recipient_role for n in svc.store.list_notifications(action_key=r2.action_key)} == {"OWNER"}


def test_assignment_notifies_assignee():
    svc, *_ = make_service()
    eid = setup_event(svc, speakers=(), vendor=False)
    r = svc.invite(ABA, eid, role="SPEAKER", email=SPK_B.email, due_date=date(2026, 11, 5), token=tok())
    rows = svc.store.list_notifications(action_key=r.action_key)
    assert [(n.address, n.rule) for n in rows] == [(SPK_B.email, "assignment_to_assignee")]
    r2 = svc.invite(ABA, eid, role="VENDOR", email=VND.email, token=tok())
    assert [n.address for n in svc.store.list_notifications(action_key=r2.action_key)] == [VND.email]


def test_owner_assigned_notifies_new_owner_and_slack_internal():
    svc, *_ = make_service()
    eid = setup_event(svc, with_owner=False, speakers=(), vendor=False)
    r = svc.invite(ABA, eid, role="DELEGATE", email=DELEG.email, slack_user_id="U_DEL", token=tok())
    assert {(n.channel, n.address) for n in svc.store.list_notifications(action_key=r.action_key)} == {
        ("EMAIL", DELEG.email), ("SLACK", "U_DEL")}


def test_speaker_confirmed_notifies_vendor(env):
    svc, *_, eid = env
    spk = next(m for m in svc.event_view(ABA, eid).members if m.email == SPK_A.email)
    r = svc.confirm_speaker(ABA, spk.member_id)
    assert [(n.recipient_role, n.rule) for n in svc.store.list_notifications(action_key=r.action_key)] == \
        [("VENDOR", "confirmed_speaker_to_vendor")]


def test_deadline_change_notifies_submitter(env):
    svc, *_, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.update_item_settings(ABA, bio.item_id, due_date=date(2026, 10, 20), vendor_visible=True,
                                 speaker_action=False, token=tok())
    rows = svc.store.list_notifications(action_key=r.action_key)
    assert [(n.address, n.deadline) for n in rows] == [(SPK_A.email, date(2026, 10, 20))]


def test_event_status_change_notifies_participants(env):
    svc, *_, eid = env
    r = svc.set_event_status(ABA, eid, "CLOSED", tok())
    assert {n.address for n in svc.store.list_notifications(action_key=r.action_key)} == {SPK_A.email, VND.email}


def test_actor_is_never_notified_of_own_action():
    svc, *_ = make_service()
    setup_event(svc, speakers=(), vendor=False)   # Aba assigned herself as owner
    assert not [n for n in svc.store.list_notifications() if n.address == ABA.email]


def test_notification_contents(env):
    svc, *_, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == "EMAIL")
    assert "Data Summit Lagos" in n.subject and "Review Speaker bio" in n.subject
    for expected in ("Event: Data Summit Lagos", "Item: Speaker bio", "Action required: Review Speaker bio",
                     "Deadline: 2026-11-01", f"https://cv.example/workspace?event={eid}&item={bio.item_id}"):
        assert expected in n.body
    assert "@" not in n.body    # no one's email address is embedded in message bodies


# ── missing owner ─────────────────────────────────────────────────────────────

def test_missing_owner_is_unroutable_then_rerouted_once():
    svc, email, slack, clock = make_service()
    eid = setup_event(svc, with_owner=False)
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    assert r.status == "recorded" and r.unroutable == 1 and r.queued == 0
    [n] = svc.store.list_notifications(action_key=r.action_key)
    assert n.status == "UNROUTABLE" and "No program owner" in n.last_error
    assert n in svc.admin_queue(ABA)["notifications"]
    assert eid in {e.event_id for e in svc.admin_queue(ABA)["no_owner"]}

    email.sent.clear()
    svc.dispatch()
    assert email.sent == [] or all(a != ABA.email for a, *_ in email.sent)

    with pytest.raises(InvalidAction):           # still no owner
        svc.reroute(ABA, n.notification_id, tok())
    svc.invite(ABA, eid, role="OWNER", email=DELEG.email, token=tok())
    rr = svc.reroute(ABA, n.notification_id, tok())
    assert rr.status == "recorded"
    rows = svc.store.list_notifications(action_key=r.action_key)
    assert sorted((x.status, x.address) for x in rows) == [("CANCELLED", ""), ("PENDING", DELEG.email)]
    with pytest.raises(InvalidAction):           # second re-route cannot duplicate
        svc.reroute(ABA, n.notification_id, tok())


def test_vendor_proposal_without_owner_is_visible_to_admin():
    svc, *_ = make_service()
    r = svc.propose_event(VND2, name="New Meetup", start_date=None, city="Nairobi",
                          details={"description": "Monthly"}, token=tok())
    assert r.unroutable == 1
    q = svc.admin_queue(ABA)
    assert r.ref in {e.event_id for e in q["no_owner"]}
    assert any(i.event_id == r.ref for i in q["to_review"])
