"""Page-level tests with Streamlit AppTest: reruns, access gates, and the admin views."""
import pytest
from streamlit.testing.v1 import AppTest

from conftest import ABA, SPK_A, STRANGER, VND, item_of, make_service, setup_event, tok
from workflow import runtime


@pytest.fixture
def wired():
    svc, email, slack, clock = make_service()
    eid = setup_event(svc)
    svc.dispatch()
    email.sent.clear(); slack.sent.clear()
    runtime.OVERRIDE.clear()
    runtime.OVERRIDE["service"] = svc
    yield svc, email, eid
    runtime.OVERRIDE.clear()


def page(path, actor):
    runtime.OVERRIDE["actor"] = actor
    at = AppTest.from_file(path, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def _submit_button(at, item_id, label="Submit"):
    return next(b for b in at.button if b.proto.form_id == f"form_{item_id}" and b.proto.label == label)


def test_speaker_submit_then_reruns_do_not_duplicate(wired):
    svc, email, eid = wired
    at = page("pages/5_Workspace.py", SPK_A)
    bio = item_of(svc, SPK_A, eid, "bio")
    at.text_area(key=f"{bio.item_id}_bio").input("I build data apps.")
    _submit_button(at, bio.item_id).click()
    at.run()
    assert not at.exception, at.exception
    assert any("Submitted version 1" in s.value for s in at.success)
    assert any("delivered" in s.value for s in at.success)      # fake channels accepted both
    for _ in range(3):                                          # plain reruns (widget interaction, refresh)
        at.run()
    assert len(svc.store.list_versions(bio.item_id)) == 1
    keys = {n.action_key for n in svc.store.list_notifications() if n.item_id == bio.item_id}
    assert len(keys) == 1 and len(email.sent) == 1

    _submit_button(at, bio.item_id, "Update").click()                       # identical content resubmitted
    at.run()
    assert any("nothing changed" in i.value for i in at.info)
    assert len(svc.store.list_versions(bio.item_id)) == 1


def test_workspace_shows_only_own_events(wired):
    svc, email, eid = wired
    at = page("pages/5_Workspace.py", STRANGER)
    assert any("not assigned to any events" in i.value for i in at.info)
    at = page("pages/5_Workspace.py", VND)
    assert at.selectbox(key="ws_event").options == ["Data Summit Lagos (Active)"]


def test_admin_page_rejects_non_admins(wired):
    for actor in (SPK_A, VND, STRANGER, None):
        at = page("pages/6_Workflow_Admin.py", actor)
        assert any("restricted to program administrators" in e.value for e in at.error)


def test_admin_page_shows_queue_and_problems(wired):
    svc, email, eid = wired
    bio = item_of(svc, SPK_A, eid, "bio")
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    svc.propose_event(VND, name="Unowned Meetup", start_date=None, city="Accra",
                               details={"description": "x"}, token=tok()).ref
    at = page("pages/6_Workflow_Admin.py", ABA)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Awaiting review"] == "2" and metrics["Events without owner"] == "1"
    assert metrics["Notification problems"] == "1"
    assert any("Unroutable" in m.value for m in at.markdown)


def test_delivery_disabled_message_is_honest():
    svc, email, slack, clock = make_service(delivery=False)
    eid = setup_event(svc)
    runtime.OVERRIDE.clear()
    runtime.OVERRIDE["service"] = svc
    try:
        at = page("pages/5_Workspace.py", SPK_A)
        bio = item_of(svc, SPK_A, eid, "bio")
        at.text_area(key=f"{bio.item_id}_bio").input("Hello")
        _submit_button(at, bio.item_id).click()
        at.run()
        msg = " ".join(s.value for s in at.success)
        assert "automatic delivery is not enabled" in msg and "delivered" not in msg
        assert email.sent == []
    finally:
        runtime.OVERRIDE.clear()


# ── regressions from the earlier hardening pass ───────────────────────────────

def test_public_pages_render_signed_out():
    runtime.OVERRIDE.clear()
    at = AppTest.from_file("streamlit_app.py", default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    # Sections after a paused one still render (st.stop() used to blank them).
    at.radio(key="spk_section").set_value("resources").run()
    assert not at.exception, at.exception
    assert any("Brand Kit" in t.label for t in at.tabs)


def test_audience_feedback_link_works_without_sign_in():
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params.update({"speaker": "Ada <b>", "event": "Data Summit", "talk": "Streams 101"})
    at.run()
    assert not at.exception, at.exception
    assert "Rate this Talk" in " ".join(m.value for m in at.markdown)
    assert "<b>" not in " ".join(m.value for m in at.markdown if "Rate this Talk" in m.value)


def test_markdown_escaping_neutralizes_links_and_directives():
    from workflow.ui import md
    out = md("[x](https://evil.example/p.png) :red[hi] **b**")
    assert "](" not in out.replace("\\](", "") and "\\[" in out and "\\:" in out and "\\*" in out


def test_review_in_workspace_then_vendor_gets_approved_download(wired):
    svc, email, eid = wired
    slides = item_of(svc, SPK_A, eid, "slides")
    svc.submit_item(SPK_A, slides.item_id, upload=("talk.pdf", b"%PDF"), token=tok())
    svc.submit_item(SPK_A, slides.item_id, upload=("talk.pdf", b"%PDF-2"), token=tok())
    at = page("pages/5_Workspace.py", ABA)
    approve = next(b for b in at.button if b.proto.form_id == f"review_{slides.item_id}" and b.proto.label == "Approve")
    approve.click()
    at.run()
    assert not at.exception, at.exception
    assert svc.store.get_item(slides.item_id).approved_version == 2
    at = page("pages/5_Workspace.py", VND)
    labels = [d.proto.label for d in at.get("download_button")]
    assert labels == ["Download talk\\.pdf"]          # only the approved version
