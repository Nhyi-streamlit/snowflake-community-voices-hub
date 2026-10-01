"""Idempotency, audit retention, and delivery reliability."""
from datetime import timedelta
from dataclasses import replace

import pytest

from conftest import ABA, SPK_A, VND, item_of, make_service, setup_event, tok
from workflow.channels import FakeChannel
from workflow.models import EMAIL, SLACK, SENDING
from workflow.service import Config, WorkflowService


# ── repeat submissions ────────────────────────────────────────────────────────

def test_same_token_resubmission_is_a_no_op(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    t = tok()
    first = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t)
    again = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t)
    assert (first.status, again.status) == ("recorded", "no_change")
    assert len(svc.store.list_versions(bio.item_id)) == 1
    assert len(svc.store.list_notifications(action_key=first.action_key)) == 2  # owner email + slack


def test_double_click_race_records_once(env):
    """Two submissions with the same token racing past the pre-check: the store rejects the second."""
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    t = tok()
    store = svc.store
    real = store.action_exists
    store.action_exists = lambda k: False      # simulate both requests passing the pre-check
    try:
        r1 = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t)
        # Second request read the item before the first committed.
        store.items[bio.item_id] = replace(store.items[bio.item_id], current_version=0, status="MISSING")
        store.versions.clear()
        r2 = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t)
    finally:
        store.action_exists = real
    assert r1.status == "recorded" and r2.status == "duplicate"


def test_revision_keeps_previous_version_and_file(env):
    svc, email, slack, clock, eid = env
    head = item_of(svc, SPK_A, eid, "headshot")
    svc.submit_item(SPK_A, head.item_id, upload=("me.png", b"png-1"), token=tok())
    clock.advance(minutes=5)
    svc.submit_item(SPK_A, head.item_id, upload=("me.png", b"png-2"), token=tok())
    versions, audit = svc.history(SPK_A, head.item_id)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].file_path != versions[1].file_path
    assert svc.download(SPK_A, head.item_id, 1)[1] == b"png-1"
    assert svc.download(SPK_A, head.item_id, 2)[1] == b"png-2"
    assert [a.note for a in sorted(audit, key=lambda a: a.created_at)] == ["first submission", "revision"]


def test_identical_content_new_session_is_no_change(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    assert r.status == "no_change" and len(svc.store.list_versions(bio.item_id)) == 1


def test_resubmit_after_changes_requested_creates_new_version(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.review_item(ABA, bio.item_id, version=1, approve=False, note="Longer please")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi, longer"}, token=tok())
    assert r.status == "recorded" and svc.store.get_item(bio.item_id).current_version == 2


def test_double_review_is_idempotent(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    assert svc.review_item(ABA, bio.item_id, version=1, approve=True).status == "recorded"
    with pytest.raises(Exception):
        svc.review_item(ABA, bio.item_id, version=1, approve=True)
    assert len([a for a in svc.store.list_audit() if a.action == "ITEM_APPROVED"]) == 1


# ── failure isolation ─────────────────────────────────────────────────────────

def test_storage_failure_records_nothing(env):
    svc, email, slack, clock, eid = env
    head = item_of(svc, SPK_A, eid, "headshot")
    svc.files.fail_next_put = True
    with pytest.raises(RuntimeError):
        svc.submit_item(SPK_A, head.item_id, upload=("me.png", b"png"), token=tok())
    assert svc.store.list_versions(head.item_id) == [] and svc.store.get_item(head.item_id).status == "MISSING"


def test_database_failure_rolls_back_everything_and_retry_succeeds(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    before = len(svc.store.list_notifications())
    svc.store.fail_next_apply = True
    t = tok()
    with pytest.raises(RuntimeError):
        svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t)
    assert svc.store.list_versions(bio.item_id) == [] and len(svc.store.list_notifications()) == before
    assert svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=t).status == "recorded"


def test_notification_failure_keeps_the_upload(env):
    svc, email, slack, clock, eid = env
    email.script = ["fail"]
    slack.script = ["fail"]
    head = item_of(svc, SPK_A, eid, "headshot")
    r = svc.submit_item(SPK_A, head.item_id, upload=("me.png", b"png"), token=tok())
    summary = svc.dispatch(action_key=r.action_key)
    assert summary["dead"] == 2 and summary["sent"] == 0
    assert svc.store.get_item(head.item_id).status == "SUBMITTED"
    assert svc.download(ABA, head.item_id, 1)[1] == b"png"
    assert all(n.status == "DEAD" and n.provider_message_id == ""
               for n in svc.store.list_notifications(action_key=r.action_key))


# ── delivery ──────────────────────────────────────────────────────────────────

def test_retry_with_backoff_then_sent(env):
    svc, email, slack, clock, eid = env
    email.script = ["retry", "retry"]
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.dispatch(action_key=r.action_key)
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == EMAIL)
    assert (n.status, n.attempts, n.next_attempt_at) == ("RETRY", 1, clock.now + timedelta(minutes=1))
    assert svc.dispatch(action_key=r.action_key)["sent"] == 0       # not due yet
    clock.advance(minutes=1)
    svc.dispatch(action_key=r.action_key)
    clock.advance(minutes=4)
    svc.dispatch(action_key=r.action_key)
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == EMAIL)
    assert (n.status, n.attempts, n.provider_message_id) == ("SENT", 3, "fake-1")
    assert len(email.sent) == 1


def test_bounded_retries_end_dead_then_admin_retry_delivers(env):
    svc, email, slack, clock, eid = env
    email.script = ["retry"] * 5
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    for _ in range(6):
        svc.dispatch(action_key=r.action_key)
        clock.advance(hours=1)
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == EMAIL)
    assert (n.status, n.attempts) == ("DEAD", 5) and email.sent == []
    assert n in svc.admin_queue(ABA)["notifications"]
    svc.retry_notification(ABA, n.notification_id, tok())
    svc.dispatch(action_key=r.action_key)
    n = svc.store.get_notification(n.notification_id)
    assert n.status == "SENT" and len(email.sent) == 1


def test_uncertain_send_is_not_auto_resent(env):
    svc, email, slack, clock, eid = env
    email.script = ["uncertain"]
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.dispatch(action_key=r.action_key)
    clock.advance(hours=2)
    svc.dispatch(action_key=r.action_key)
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == EMAIL)
    assert n.status == "UNCERTAIN" and email.sent == []


def test_crashed_sender_marks_uncertain(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    claimed = svc.store.claim_notifications(now=clock.now, limit=10, token="crashed", action_key=r.action_key)
    assert claimed and all(n.status == SENDING for n in claimed)
    clock.advance(minutes=11)
    svc.dispatch()
    assert {n.status for n in svc.store.list_notifications(action_key=r.action_key)} == {"UNCERTAIN"}
    assert email.sent == []


def test_dispatch_twice_sends_once(env):
    svc, email, slack, clock, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.dispatch(action_key=r.action_key)
    svc.dispatch(action_key=r.action_key)
    svc.dispatch()
    assert len(email.sent) == 1 and len(slack.sent) == 1


def test_delivery_disabled_sends_nothing_and_says_so():
    svc, email, slack, clock = make_service(delivery=False)
    eid = setup_event(svc)
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    s = svc.dispatch(action_key=r.action_key)
    assert s["sent"] == 0 and s["skipped"] == 2 and email.sent == []
    assert {n.status for n in svc.store.list_notifications(action_key=r.action_key)} == {"PENDING"}


def test_unconfigured_channel_does_not_claim_delivery(env):
    svc, email, slack, clock, eid = env
    svc.channels = {EMAIL: email}          # Slack enabled in config but no client available
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.dispatch(action_key=r.action_key)
    n = next(x for x in svc.store.list_notifications(action_key=r.action_key) if x.channel == SLACK)
    assert n.status == "RETRY" and "not configured" in n.last_error


# ── end to end ────────────────────────────────────────────────────────────────

def test_full_speaker_upload_to_owner_notification_flow():
    svc, email, slack, clock = make_service()
    eid = svc.create_event(ABA, name="Data Summit Lagos", start_date=None, city="Lagos", token=tok()).ref
    svc.invite(ABA, eid, role="OWNER", email=ABA.email, slack_user_id="U_ABA", token=tok())
    svc.bind_invites(ABA)
    svc.invite(ABA, eid, role="SPEAKER", email=SPK_A.email, token=tok())
    svc.dispatch()
    assert [a for a, *_ in email.sent] == [SPK_A.email]          # invitation reached the speaker
    assert svc.bind_invites(SPK_A) == 1                          # speaker signs in

    slides = item_of(svc, SPK_A, eid, "slides")
    svc.update_item_settings(ABA, slides.item_id, due_date=clock.now.date() + timedelta(days=14),
                             vendor_visible=True, speaker_action=False, token=tok())
    svc.dispatch()
    email.sent.clear()

    r = svc.submit_item(SPK_A, slides.item_id, upload=("talk.pdf", b"%PDF"), token=tok())
    assert svc.dispatch(action_key=r.action_key) == {"sent": 2, "retry": 0, "dead": 0, "uncertain": 0, "skipped": 0}
    [(to, subject, body)] = email.sent
    assert to == ABA.email and "Review Slides" in subject
    assert "Deadline: 2026-10-15" in body and f"event={eid}" in body
    assert slack.sent[0][0] == "U_ABA"
    sent = svc.store.list_notifications(action_key=r.action_key)
    assert all(n.status == "SENT" and n.provider_message_id for n in sent)
