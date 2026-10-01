"""Access boundaries for each role. Every check goes through the service, as the pages do."""
from datetime import date

import pytest

from conftest import ABA, DELEG, SPK_A, SPK_B, STRANGER, VND, VND2, item_of, make_service, setup_event, tok
from workflow.models import NotAuthorized, InvalidAction
from workflow.service import Actor


def test_stranger_sees_nothing(env):
    svc, *_, eid = env
    assert svc.my_events(STRANGER) == []
    with pytest.raises(NotAuthorized):
        svc.event_view(STRANGER, eid)
    item = item_of(svc, SPK_A, eid, "bio")
    with pytest.raises(NotAuthorized):
        svc.submit_item(STRANGER, item.item_id, text={"bio": "x"}, token=tok())
    with pytest.raises(NotAuthorized):
        svc.history(STRANGER, item.item_id)


def test_same_email_different_subject_is_not_authorized(env):
    """Access is bound to the verified subject, not to an email address."""
    svc, *_, eid = env
    impostor = Actor("sub-impostor", SPK_A.email)
    assert svc.bind_invites(impostor) == 0      # invite already bound to the real subject
    with pytest.raises(NotAuthorized):
        svc.event_view(impostor, eid)


def test_invited_but_not_signed_in_has_no_access():
    svc, *_ = make_service()
    eid = setup_event(svc, speakers=())
    svc.invite(ABA, eid, role="SPEAKER", email=SPK_B.email, token=tok())
    with pytest.raises(NotAuthorized):
        svc.event_view(SPK_B, eid)
    assert svc.bind_invites(SPK_B) == 1
    assert svc.event_view(SPK_B, eid).roles == {"SPEAKER"}


def test_speaker_cannot_touch_another_speakers_items():
    svc, *_ = make_service()
    eid = setup_event(svc, speakers=(SPK_A, SPK_B))
    a_items = [i for i in svc.event_view(SPK_A, eid).items if i.party == "SPEAKER"]
    b_items = [i for i in svc.event_view(SPK_B, eid).items if i.party == "SPEAKER"]
    assert a_items and b_items and not {i.item_id for i in a_items} & {i.item_id for i in b_items}
    with pytest.raises(NotAuthorized):
        svc.submit_item(SPK_B, a_items[0].item_id, text={"profile": "x"}, token=tok())


def test_vendor_sees_only_approved_vendor_visible_version():
    svc, *_ = make_service()
    eid = setup_event(svc)
    slides = item_of(svc, SPK_A, eid, "slides")
    svc.submit_item(SPK_A, slides.item_id, upload=("deck-v1.pdf", b"%PDF v1"), token=tok())
    assert slides.item_id not in {i.item_id for i in svc.event_view(VND, eid).items}
    with pytest.raises(NotAuthorized):
        svc.download(VND, slides.item_id, 1)

    svc.review_item(ABA, slides.item_id, version=1, approve=True)
    assert svc.download(VND, slides.item_id, 1) == ("deck-v1.pdf", b"%PDF v1")

    # A newer unreviewed revision stays hidden from the vendor; the approved one remains.
    svc.submit_item(SPK_A, slides.item_id, upload=("deck-v2.pdf", b"%PDF v2"), token=tok())
    with pytest.raises(NotAuthorized):
        svc.download(VND, slides.item_id, 2)
    assert svc.download(VND, slides.item_id, 1)[1] == b"%PDF v1"
    versions, audit = svc.history(VND, slides.item_id)
    assert [v.version for v in versions] == [1] and audit == []


def test_vendor_cannot_see_non_shared_speaker_items_or_unconfirmed_speakers(env):
    svc, *_, eid = env
    avail = item_of(svc, SPK_A, eid, "availability")
    svc.submit_item(SPK_A, avail.item_id, text={"availability": "Nov 19-21"}, token=tok())
    svc.review_item(ABA, avail.item_id, version=1, approve=True)
    assert avail.item_id not in {i.item_id for i in svc.event_view(VND, eid).items}
    emails = {m.email for m in svc.event_view(VND, eid).members}
    assert SPK_A.email not in emails
    spk = next(m for m in svc.event_view(ABA, eid).members if m.email == SPK_A.email)
    svc.confirm_speaker(ABA, spk.member_id)
    assert SPK_A.email in {m.email for m in svc.event_view(VND, eid).members}


def test_vendor_restricted_to_own_events(env):
    svc, *_, eid = env
    other = svc.propose_event(VND2, name="Other Conf", start_date=None, city="Accra",
                              details={"description": "x"}, token=tok()).ref
    assert [e.event_id for e in svc.my_events(VND2)] == [other]
    with pytest.raises(NotAuthorized):
        svc.event_view(VND2, eid)
    with pytest.raises(NotAuthorized):
        svc.event_view(VND, other)


def test_speaker_sees_vendor_items_only_when_action_needed(env):
    svc, *_, eid = env
    ids = {i.item_type for i in svc.event_view(SPK_A, eid).items if i.party == "VENDOR"}
    assert ids == {"logistics"}


def test_admin_only_operations_rejected_for_others(env):
    svc, *_, eid = env
    for actor in (SPK_A, VND, STRANGER):
        with pytest.raises(NotAuthorized):
            svc.invite(actor, eid, role="SPEAKER", email="x@example.com", token=tok())
        with pytest.raises(NotAuthorized):
            svc.admin_queue(actor)
        with pytest.raises(NotAuthorized):
            svc.create_event(actor, name="x", start_date=None, city="", token=tok())


def test_reviewer_permissions():
    svc, *_ = make_service()
    eid = setup_event(svc, with_delegate=True)
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hello"}, token=tok())
    with pytest.raises(NotAuthorized):
        svc.review_item(SPK_A, bio.item_id, version=1, approve=True)
    with pytest.raises(NotAuthorized):
        svc.review_item(VND, bio.item_id, version=1, approve=True)
    assert svc.review_item(DELEG, bio.item_id, version=1, approve=True).status == "recorded"
    with pytest.raises(NotAuthorized):   # delegates review but do not administer
        svc.invite(DELEG, eid, role="SPEAKER", email="x@example.com", token=tok())


def test_slack_only_for_internal_roles(env):
    svc, *_, eid = env
    with pytest.raises(InvalidAction):
        svc.invite(ABA, eid, role="VENDOR", email="v2@x.example", slack_user_id="U1", token=tok())


def test_stale_review_rejected(env):
    svc, *_, eid = env
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "v1"}, token=tok())
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "v2"}, token=tok())
    with pytest.raises(InvalidAction):
        svc.review_item(ABA, bio.item_id, version=1, approve=True)
