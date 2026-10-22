"""Program feedback form (Speaker Portal → After your talk): saves to Program_Feedback and emails Aba."""
import pytest
from streamlit.testing.v1 import AppTest

from test_conference import FakeGmail
from utils import ops_store as ops
from utils import program_feedback as pf
from utils import sheets
from utils.gmail_diag import GmailClient


@pytest.fixture
def env(monkeypatch):
    hub = ops.MemorySheets({})
    ops.OVERRIDE["sheets"] = hub
    gm = FakeGmail()
    creds = {"GOOGLE_CLIENT_ID": "c", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"}
    monkeypatch.setattr(sheets, "_gmail_client", GmailClient(lambda: creds, gm.post, gm.get))
    monkeypatch.setattr(sheets, "_secrets", lambda: {**creds, "GOOGLE_SPREADSHEET_ID": "hub"})
    monkeypatch.setattr(sheets, "_gmail_token", lambda: "tok")
    yield hub, gm
    ops.OVERRIDE.clear()


def rows(hub):
    return ops.records(pf.TAB)


def test_submit_saves_and_emails_aba_escaped(env):
    hub, gm = env
    ok, fid, reason = pf.submit(name="Ada <b>", email="ada@x.com", community="Data Superhero", event="Iceberg Day",
                                topic="Travel & reimbursement", rating=4, went_well="Fast booking",
                                improve="Earlier <script>", follow_up=True)
    assert ok and reason == "" and fid.startswith("PF-")
    [r] = rows(hub)
    assert r["rating"] == "4" and r["follow_up_ok"] == "yes" and r["improve"] == "Earlier <script>"
    [m] = gm.sent
    assert m["to"] == pf.TO and "community@" not in m["to"]
    assert "&lt;script&gt;" in m["body"] and "<script>" not in m["body"] and "Ada &lt;b&gt;" in m["body"]


def test_anonymous_and_follow_up_needs_email(env):
    hub, gm = env
    pf.submit(name="", email="", community="Other", event="", topic="Overall program", rating=5,
              went_well="Great", improve="", follow_up=True)
    assert rows(hub)[0]["follow_up_ok"] == "no" and "Anonymous speaker" in gm.sent[0]["subject"]


def test_empty_feedback_rejected_and_failed_email_still_saves(env):
    hub, gm = env
    with pytest.raises(ValueError):
        pf.submit(name="", email="", community="Other", event="", topic="Other", rating=3, went_well=" ",
                  improve="", follow_up=False)
    gm.fail = True
    ok, _, reason = pf.submit(name="", email="", community="Other", event="", topic="Other", rating=3,
                              went_well="ok", improve="", follow_up=False)
    assert ok and reason == "insufficientPermissions" and len(rows(hub)) == 1


def test_portal_form_submits_signed_out(env):
    hub, gm = env
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = "after"
    at.run()
    assert not at.exception, at.exception
    at.text_area(key="pf_improve").input("More notice before CFP deadlines")
    at.radio(key="pf_rating").set_value(2)
    next(b for b in at.button if b.label == "Send feedback").click().run()
    assert not at.exception, at.exception
    assert any("Thank you" in s.value for s in at.success)
    [r] = rows(hub)
    assert r["rating"] == "2" and r["improve"] == "More notice before CFP deadlines"
    assert len(gm.sent) == 1 and gm.sent[0]["to"] == pf.TO


def test_portal_form_requires_some_text(env):
    hub, gm = env
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = "after"
    at.run()
    next(b for b in at.button if b.label == "Send feedback").click().run()
    assert any("what went well" in w.value for w in at.warning) and rows(hub) == [] and gm.sent == []
