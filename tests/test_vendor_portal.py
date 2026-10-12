"""Vendor Portal: sign-in gating, guided flow, validation, bulk upload, and My events scoping."""
from datetime import date, timedelta

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import ABA, VND, VND2, make_service
from utils import email_otp as otp
from utils import vendor_backend as vb
from utils import vendor_validation as vv
from workflow import runtime

PAGE = "pages/2_Vendor_Portal.py"
START = date.today() + timedelta(days=60)


class FakeOtp:
    """OtpStore with a fake clock and an outbox that captures codes instead of emailing them."""

    class _Clock:
        t = 1_000_000.0

        def __call__(self):
            return self.t

    def __init__(self):
        self.clock = self._Clock()
        self.box = type("Box", (), {"sent": []})()
        self.store = otp.OtpStore(sender=self._send, clock=self.clock, key=b"k" * 32)

    def _send(self, to, subject, body):
        self.box.sent.append((to, subject, body))
        return True

    def code(self):
        import re
        return re.search(r">(\d{6})<", self.box.sent[-1][2]).group(1)


class FakeSheets:
    def __init__(self, fail=False):
        self.tabs = {"Events": [], "Speaker_Requests": []}
        self.fail = fail

    def _cols(self, tab):
        return vb.EVENT_COLS if tab == "Events" else vb.REQUEST_COLS

    def read_tab(self, tab):
        if self.fail:
            raise ConnectionError("sheets down")
        return pd.DataFrame(self.tabs[tab], columns=self._cols(tab))

    def append_row(self, tab, row):
        if self.fail:
            return False
        self.tabs[tab].append(list(row))
        return True

    def update_row(self, tab, sheet_row, values):
        self.tabs[tab][sheet_row - 2] = list(values)
        return True

    def events(self):
        return pd.DataFrame(self.tabs["Events"], columns=vb.EVENT_COLS)


def draft(**kw):
    d = {"organizer_name": "Ada", "organizer_org": "EventCo", "event_name": "Data Summit",
         "event_start": START.isoformat(), "event_city": "Accra", "event_country": "Ghana",
         "event_format": "In-person conference", "speaker_topic": "AI apps on Snowflake"}
    d.update(kw)
    return d


@pytest.fixture
def sheets():
    fake = FakeSheets()
    runtime.OVERRIDE.clear()
    runtime.OVERRIDE["service"] = None          # no workflow store -> Sheets fallback
    vb.SHEETS_OVERRIDE["api"] = fake
    yield fake
    runtime.OVERRIDE.clear()
    vb.SHEETS_OVERRIDE.clear()


@pytest.fixture
def workflow():
    svc, *_ = make_service()
    runtime.OVERRIDE.clear()
    runtime.OVERRIDE["service"] = svc
    yield svc
    runtime.OVERRIDE.clear()


def page(actor, secrets=None):
    runtime.OVERRIDE["actor"] = actor
    at = AppTest.from_file(PAGE, default_timeout=30)
    for k, v in (secrets or {}).items():
        at.secrets[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def click(at, key):
    at.button(key=key).click()
    at.run()
    assert not at.exception, at.exception
    return at


def fill_steps(at, **over):
    d = draft(**over)
    at.text_input(key="vnd_f_organizer_name").input(d["organizer_name"])
    at.text_input(key="vnd_f_organizer_org").input(d["organizer_org"])
    click(at, "vnd_next")
    at.text_input(key="vnd_f_event_name").input(d["event_name"])
    at.date_input(key="vnd_f_event_start").set_value(vv.to_date(d["event_start"]))
    if d.get("event_end"):
        at.date_input(key="vnd_f_event_end").set_value(vv.to_date(d["event_end"]))
    at.text_input(key="vnd_f_event_city").input(d["event_city"])
    at.text_input(key="vnd_f_event_country").input(d["event_country"])
    at.selectbox(key="vnd_f_event_format").select(d["event_format"])
    if d.get("event_website"):
        at.text_input(key="vnd_f_event_website").input(d["event_website"])
    click(at, "vnd_next")
    return at, d


# ── unit: validation ──────────────────────────────────────────────────────────

def test_validation_rules():
    today = date.today()
    assert vv.validate(draft()) == {}
    errs = vv.validate(draft(event_name="", event_end=(START - timedelta(days=1)).isoformat(),
                             event_website="yourevent", cfp_deadline=(START + timedelta(days=1)).isoformat()))
    assert set(errs) == {"event_name", "event_end", "event_website", "cfp_deadline"}
    assert "past" in vv.validate(draft(event_start=(today - timedelta(days=1)).isoformat()))["event_start"]
    assert vv.validate(draft(event_website="https://x.example/a"), ["event_website"]) == {}
    assert "event_format" in vv.validate(draft(event_format="Rave"))


def test_validate_bulk_reports_row_and_column():
    df = pd.DataFrame([draft(), draft(event_name="B", cfp_link="nope"), draft(event_name="C")])
    valid, errors, missing = vv.validate_bulk(df)
    assert missing == [] and len(valid) == 2
    assert errors.to_dict(orient="records") == [
        {"row": 3, "column": "cfp_link", "problem": "CFP link must be a full link starting with https://"}]
    _, _, missing = vv.validate_bulk(df.drop(columns=["event_city"]))
    assert missing == ["event_city"]


# ── unit: backend ─────────────────────────────────────────────────────────────

def test_sheets_submit_and_scoping(sheets):
    out = vb.submit_event(VND, draft(), "t1")
    assert out.ok and out.ref.startswith("EV-")
    ev = sheets.events()
    assert ev.loc[0, "organizer_email"] == VND.email and ev.loc[0, "status"] == "Pending"
    assert "+00:00" in ev.loc[0, "submitted_at"]                       # timezone-aware
    assert sheets.tabs["Speaker_Requests"][0][3] == out.ref
    assert [e.ref for e in vb.list_my_events(VND)] == [out.ref]
    assert vb.list_my_events(VND2) == []


def test_sheets_edit_only_own_pending(sheets):
    ref = vb.submit_event(VND, draft(), "t1").ref
    assert not vb.update_pending(VND2, ref, draft(event_name="Hijack"), "x").ok
    assert vb.update_pending(VND, ref, draft(event_name="Renamed"), "x").ok
    assert sheets.events().loc[0, "event_name"] == "Renamed"
    sheets.tabs["Events"][0][2] = "Approved"
    assert not vb.update_pending(VND, ref, draft(event_name="Again"), "x").ok


def test_backend_errors_are_friendly(sheets):
    sheets.fail = True
    out = vb.submit_event(VND, draft(), "t1")
    assert not out.ok and out.message == vb.RETRY_MSG
    with pytest.raises(RuntimeError, match="couldn't load"):
        vb.list_my_events(VND)


def test_bulk_skips_duplicates(sheets):
    vb.submit_event(VND, draft(), "t0")
    rows = [dict(draft(), _row=2), dict(draft(event_name="Two"), _row=3), dict(draft(event_name="two"), _row=4)]
    res = vb.submit_bulk(VND, rows, "bulk")
    assert [r["result"] for r in res] == ["Skipped", "Submitted", "Skipped"]
    assert len(sheets.tabs["Events"]) == 2


def test_workflow_mode_uses_propose_event(workflow):
    svc = workflow
    out = vb.submit_event(VND, draft(), "t1")
    assert out.ok and vb.mode() == vb.WORKFLOW
    assert svc.store.get_event(out.ref).status == "PROPOSED"
    mine = vb.list_my_events(VND)
    assert [(e.ref, e.status, e.details["speaker_topic"]) for e in mine] == [(out.ref, "Pending", "AI apps on Snowflake")]
    assert vb.list_my_events(VND2) == []
    assert vb.submit_event(VND, draft(), "t1").duplicate               # same form token: no second record
    assert vb.update_pending(VND, out.ref, draft(event_city="Kumasi"), "t2").ok
    assert vb.list_my_events(VND)[0].details["event_city"] == "Kumasi"
    assert not vb.update_pending(VND2, out.ref, draft(), "t3").ok


# ── page: sign-in gating ──────────────────────────────────────────────────────

def test_signed_out_sees_landing_and_email_sign_in(sheets):
    at = page(None)                                                     # no [auth]: email codes only
    assert not at.error and not at.exception
    assert at.text_input(key="otp_email_input") is not None
    assert any(b.label == "Email me a code" for b in at.button)
    assert not any(b.label == "Sign in with Google" for b in at.button)
    assert any("Why do I need to sign in" in e.label for e in at.expander)
    at = page(None, {"auth": {"client_id": "x"}})                       # Google offered as a secondary option
    assert any(b.label == "Sign in with Google" for b in at.button)


@pytest.fixture
def otp_store():
    fake = FakeOtp()
    otp.OVERRIDE["store"] = fake.store
    yield fake
    otp.OVERRIDE.clear()


def real_page():
    """Run the page with the real get_actor (no actor override), as an anonymous visitor would."""
    runtime.OVERRIDE.pop("actor", None)
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def press(at, label):
    next(b for b in at.button if b.label == label).click()
    at.run()
    assert not at.exception, at.exception
    return at


def test_email_code_sign_in_end_to_end(sheets, otp_store):
    at = real_page()
    at.text_input(key="otp_email_input").input("Vendor@EventCo.example")
    press(at, "Email me a code")
    assert otp_store.box.sent and otp_store.box.sent[0][0] == "vendor@eventco.example"
    assert any("We sent a 6-digit code" in s.value for s in at.success)
    at.text_input(key="otp_code_input").input("000000" if otp_store.code() != "000000" else "111111")
    press(at, "Sign in")
    assert any("4 attempt(s) left" in e.value for e in at.error)
    at.text_input(key="otp_code_input").input(otp_store.code())
    press(at, "Sign in")
    assert "Signed in as vendor@eventco\\.example" in " ".join(c.value for c in at.caption)   # markdown-escaped
    assert at.radio(key="vnd_view") is not None                         # portal is shown
    assert not any("Mode:" in w.value for w in at.warning)              # OTP users are never admins
    at.radio(key="vnd_view").set_value("Help")
    at.run()
    press(at, "Sign out")
    assert any(b.label == "Email me a code" for b in at.button)


def test_email_code_session_expires(sheets, otp_store):
    at = real_page()
    at.text_input(key="otp_email_input").input("vendor@eventco.example")
    press(at, "Email me a code")
    at.text_input(key="otp_code_input").input(otp_store.code())
    press(at, "Sign in")
    assert at.radio(key="vnd_view") is not None
    otp_store.clock.t += otp.SESSION_TTL + 1
    at.run()
    assert any(b.label == "Email me a code" for b in at.button)         # back to the sign-in screen


def test_email_code_users_get_only_their_events(sheets, otp_store):
    vb.submit_event(VND2, draft(event_name="Someone else's event"), "t")
    at = real_page()
    at.text_input(key="otp_email_input").input(VND.email)
    press(at, "Email me a code")
    at.text_input(key="otp_code_input").input(otp_store.code())
    press(at, "Sign in")
    at.radio(key="vnd_view").set_value("My events")
    at.run()
    assert not at.exception
    assert "Someone else" not in " ".join(m.value for m in at.markdown)
    assert any("haven't registered any events" in i.value for i in at.info)


def test_mode_banner_only_for_admins(sheets):
    assert any("Google Sheets fallback" in w.value for w in page(ABA).warning)
    at = page(VND)
    assert not any("Mode:" in e.value for e in list(at.warning) + list(at.info))


# ── page: guided flow ─────────────────────────────────────────────────────────

def test_step_validation_blocks_next_and_back_keeps_draft(sheets):
    at = page(VND)
    click(at, "vnd_next")
    assert at.session_state["vnd_step"] == 0
    assert any("Your full name is required" in e.value for e in at.error)
    at.text_input(key="vnd_f_organizer_name").input("Ada")
    at.text_input(key="vnd_f_organizer_org").input("EventCo")
    click(at, "vnd_next")
    assert at.session_state["vnd_step"] == 1
    at.text_input(key="vnd_f_event_name").input("Data Summit")
    at.date_input(key="vnd_f_event_start").set_value(START)
    at.date_input(key="vnd_f_event_end").set_value(START - timedelta(days=1))
    click(at, "vnd_next")
    assert at.session_state["vnd_step"] == 1
    msgs = " ".join(e.value for e in at.error)
    assert "End date must be on or after" in msgs and "City is required" in msgs
    click(at, "vnd_back")
    assert at.text_input(key="vnd_f_organizer_name").value == "Ada"
    click(at, "vnd_next")
    assert at.text_input(key="vnd_f_event_name").value == "Data Summit"


def test_full_flow_submits_once_and_shows_reference(sheets):
    at, _ = fill_steps(page(VND))
    at.text_area(key="vnd_f_speaker_topic").input("AI apps")
    at.date_input(key="vnd_f_cfp_deadline").set_value(START + timedelta(days=5))
    click(at, "vnd_next")
    assert any("CFP deadline must be on or before" in e.value for e in at.error)
    at.date_input(key="vnd_f_cfp_deadline").set_value(START - timedelta(days=5))
    click(at, "vnd_next")
    assert at.session_state["vnd_step"] == 3
    click(at, "vnd_submit")
    ref = sheets.events().loc[0, "event_id"]
    assert any(ref in c.value for c in at.code)
    assert "What happens next" in " ".join(m.value for m in at.markdown)
    for _ in range(2):
        at.run()
    assert len(sheets.tabs["Events"]) == 1


def test_submit_failure_keeps_answers(sheets):
    at, _ = fill_steps(page(VND))
    at.text_area(key="vnd_f_speaker_topic").input("AI apps")
    click(at, "vnd_next")
    sheets.fail = True
    click(at, "vnd_submit")
    assert any("couldn't save" in e.value for e in at.error)
    assert at.session_state["vnd_draft"]["event_name"] == "Data Summit"


# ── page: My events ───────────────────────────────────────────────────────────

def test_my_events_scoped_escaped_and_editable(sheets):
    ref = vb.submit_event(VND, draft(event_name="Summit [click](https://evil.example)"), "t").ref
    vb.submit_event(VND2, draft(event_name="Someone else's event"), "t2")
    at = page(VND)
    at.radio(key="vnd_view").set_value("My events")
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "Someone else" not in text
    assert "](https://evil" not in text and "\\[click\\]" in text
    click(at, f"vnd_edit_{ref}")
    assert at.session_state["vnd_edit_ref"] == ref and at.session_state["vnd_view"] == "Register an event"
    assert at.text_input(key="vnd_f_organizer_name").value == "Ada"
    for _ in range(3):
        click(at, "vnd_next")
    click(at, "vnd_submit")
    assert any("Changes saved" in s.value for s in at.success)
    assert len(sheets.tabs["Events"]) == 2


def test_my_events_load_failure_is_friendly(sheets):
    sheets.fail = True
    at = page(VND)
    at.radio(key="vnd_view").set_value("My events")
    at.run()
    assert not at.exception
    assert any("couldn't load" in e.value for e in at.error)


# ── page: bulk upload ─────────────────────────────────────────────────────────

def test_bulk_page_renders_and_three_row_upload_submits(sheets):
    at = page(VND)
    at.radio(key="vnd_view").set_value("Bulk upload")
    at.run()
    assert not at.exception
    assert "Download the template" in " ".join(m.value for m in at.markdown)
    # AppTest can't drive st.file_uploader, so exercise the exact functions the page calls on upload.
    csv = pd.DataFrame([draft(event_name=f"Event {i}") for i in range(3)]).to_csv(index=False)
    df = vv.read_upload("events.csv", pd.io.common.StringIO(csv))
    valid, errors, missing = vv.validate_bulk(df)
    assert errors.empty and not missing
    res = vb.submit_bulk(VND, valid, "bulk")
    assert [r["result"] for r in res] == ["Submitted"] * 3
    assert len(vb.list_my_events(VND)) == 3
    assert len(vb.submit_bulk(VND, valid, "bulk2")) == 3 and len(sheets.tabs["Events"]) == 3   # re-upload: all skipped


def test_template_has_example_row():
    assert list(vv.EXAMPLE_ROW) == vv.BULK_COLUMNS
    assert vv.validate(vv.EXAMPLE_ROW, today=date(2026, 1, 1)) == {}
