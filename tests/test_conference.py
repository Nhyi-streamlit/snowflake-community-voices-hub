"""Conference support requests: detection, Aba's notification, approve/decline, Navan send-once, admin UI.

Nothing reaches Google: the form sheet is SHEETS_OVERRIDE, the hub sheet is a MemorySheets, and Gmail is a real
GmailClient wired to fake HTTP so the To/Cc headers are checked as sent.
"""
import base64
import email
from email.header import decode_header, make_header

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import ABA, VND
from utils import conference as cf
from utils import email_health, ops_admin, ops_store as ops
from utils import sheets
from utils.gmail_diag import GmailClient
from workflow import runtime

FORM_COLS = ["Submission ID", "Submitted At", "First Name", "Last Name", "Email", "Country", "City", "Community",
             "Years w/ Snowflake", "Event Name", "Event Link", "Talk Title", "Session Type", "Snowflake Topics",
             "Departure Date", "Return Date", "Traveling From", "Traveling To", "Event Type Interest", "Notes",
             "Swag Requested", "Swag Shipping Details", "Flight Booked", "Hotel Booked", "Ground Transport Booked",
             "Preferred Travel Mode"]


def form_row(sid, at, first, mail, event="NDSML Summit 2026", mode="Flight", notes="Hotel near venue <b>"):
    d = dict.fromkeys(FORM_COLS, "")
    d.update({"Submission ID": sid, "Submitted At": at, "First Name": first, "Last Name": "Stefanska",
              "Email": mail, "Country": "Germany", "City": "Berlin", "Community": "Snowflake Data Superhero",
              "Event Name": event, "Event Link": "https://ndsmlsummit.com/", "Departure Date": "2026-11-09",
              "Return Date": "2026-11-11", "Traveling From": "Berlin", "Traveling To": "Stockholm",
              "Notes": notes, "Preferred Travel Mode": mode})
    return d


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class FakeGmail:
    """HTTP layer for GmailClient: token endpoint + send endpoint. `fail` makes sends return a Gmail error."""

    def __init__(self):
        self.sent, self.fail = [], False

    def post(self, url, **kw):
        if "oauth2" in url:
            return Resp(200, {"access_token": "tok", "expires_in": 3600})
        if self.fail:
            return Resp(403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                                        "errors": [{"reason": "insufficientPermissions"}]}})
        msg = email.message_from_bytes(base64.urlsafe_b64decode(kw["json"]["raw"]))
        self.sent.append({"to": msg["To"], "cc": msg["Cc"], "subject": str(make_header(decode_header(msg["Subject"]))),
                          "body": msg.get_payload(decode=True).decode()})
        return Resp(200, {"id": "m1"})

    def get(self, url, **kw):
        return Resp(200, {"emailAddress": "cv@x.com"})

    def to(self, addr):
        return [m for m in self.sent if addr in (m["to"] or "")]


@pytest.fixture
def env(monkeypatch):
    form = [form_row("a", "2026-10-01T10:00:00Z", "Old", "old@x.com")]
    cf.SHEETS_OVERRIDE["source"] = lambda: pd.DataFrame(form, columns=FORM_COLS)
    hub = ops.MemorySheets({})
    ops.OVERRIDE["sheets"] = hub
    gm = FakeGmail()
    creds = {"GOOGLE_CLIENT_ID": "c", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"}
    monkeypatch.setattr(sheets, "_gmail_client", GmailClient(lambda: creds, gm.post, gm.get))
    monkeypatch.setattr(sheets, "_secrets", lambda: {**creds, "GOOGLE_SPREADSHEET_ID": "hub"})
    monkeypatch.setattr(sheets, "_gmail_token", lambda: "tok")
    yield form, hub, gm
    cf.SHEETS_OVERRIDE.clear()
    ops.OVERRIDE.clear()


def add_new(form):
    form.append(form_row("b", "2026-10-22T13:09:31Z", "Anastasiia", "Resheras@gmail.com"))
    return "2026-10-22T13:09:31Z|resheras@gmail.com"


# ── Detection + notification ─────────────────────────────────────────────────────────────────────────────────

def test_first_run_without_baseline_records_and_sends_nothing(env):
    form, hub, gm = env
    r = cf.check(notify=True)
    assert "baseline" in r["blocked"] and gm.sent == [] and ops.records(cf.TAB) == []


def test_baseline_then_only_new_rows_notify_aba(env):
    form, hub, gm = env
    assert cf.check(baseline=True)["new"] == 1 and gm.sent == []
    assert ops.records(cf.TAB)[0]["status"] == cf.BASELINE
    key = add_new(form)
    r = cf.check(notify=True, base_url="https://hub.example/")
    assert (r["new"], r["notified"]) == (1, 1)
    [m] = gm.sent
    assert m["to"] == cf.ADMIN_EMAIL and m["cc"] is None
    assert "https://hub.example/workflow-admin?tab=conference" in m["body"]
    assert "Preferred mode of travel" in m["body"] and "Flight" in m["body"]
    assert "&lt;b&gt;" in m["body"] and "<b>Hotel" not in m["body"]          # form text is escaped
    t = cf.tracked()[key]
    assert t["status"] == cf.PENDING and t["notified_at"] and t["conference"] == "NDSML Summit 2026"
    assert t["dates"] == "2026-11-09 to 2026-11-11"
    assert set(ops.HEADERS[cf.TAB]) == {"key", "name", "email", "conference", "dates", "submitted_at", "status",
                                        "notified_at", "decided_by", "decided_at", "navan_sent_at", "notes"}
    assert cf.check(notify=True)["new"] == 0 and len(gm.sent) == 1          # hourly rerun: nothing new


def test_failed_notification_is_retried_next_run(env):
    form, hub, gm = env
    cf.check(baseline=True)
    key = add_new(form)
    gm.fail = True
    r = cf.check(notify=True)
    assert r["failed"] == ["insufficientPermissions"] and not cf.tracked()[key]["notified_at"]
    gm.fail = False
    assert cf.check(notify=True)["notified"] == 1 and cf.tracked()[key]["notified_at"]


def test_baseline_before_keeps_recent_rows_pending(env):
    form, hub, gm = env
    key = add_new(form)
    form.append(form_row("u", "", "Undated", "u@x.com"))
    r = cf.check(baseline=True, baseline_before="2026-10-02")
    t = cf.tracked()
    assert r["new"] == 3 and gm.sent == []
    assert t[key]["status"] == cf.PENDING and t["|u@x.com"]["status"] == cf.BASELINE
    assert t["2026-10-01T10:00:00Z|old@x.com"]["status"] == cf.BASELINE
    assert cf.check(notify=True)["notified"] == 1 and gm.sent[0]["to"] == cf.ADMIN_EMAIL


def test_key_is_timestamp_plus_email_and_duplicates_collapse(env):
    form, hub, gm = env
    cf.check(baseline=True)
    form.append(form_row("b", "2026-10-22T13:09:31Z", "A", "x@y.com"))
    form.append(form_row("b2", "2026-10-22T13:09:31Z", "A", "X@Y.com", event="Updated"))
    form.append(form_row("c", "", "NoEmail", ""))                          # no email → ignored
    assert cf.check(notify=True)["new"] == 1
    assert cf.tracked()["2026-10-22T13:09:31Z|x@y.com"]["conference"] == "Updated"


# ── Approve / decline / Navan ────────────────────────────────────────────────────────────────────────────────

def pending(env):
    form, hub, gm = env
    cf.check(baseline=True)
    key = add_new(form)
    cf.check(notify=True)
    gm.sent.clear()
    return key


def test_approve_sends_one_navan_email_cc_aba_and_never_resends(env):
    key = pending(env)
    gm = env[2]
    ok, msg = cf.decide(key, cf.APPROVED, ABA.email, note="Prepaid hotel please")
    assert ok, msg
    [m] = gm.sent
    assert m["to"] == ", ".join(cf.NAVAN_TO) and m["cc"] == cf.ADMIN_EMAIL
    for s in ("Anastasiia Stefanska", "Resheras@gmail.com", "NDSML Summit 2026", "2026-11-09", "2026-11-11",
              "Stockholm", "Preferred mode of travel", "Flight", "Prepaid hotel please"):
        assert s in m["body"], s
    t = cf.tracked()[key]
    assert t["status"] == cf.APPROVED and t["decided_by"] == ABA.email and t["decided_at"] and t["navan_sent_at"]
    assert cf.decide(key, cf.APPROVED, ABA.email)[0] and cf.send_navan(key)[0]
    assert len(gm.sent) == 1                                               # idempotent
    assert not cf.decide(key, cf.DECLINED, ABA.email)[0]                    # can't decline after approval


def test_failed_navan_send_stays_approved_unsent_until_retry(env):
    key = pending(env)
    gm = env[2]
    gm.fail = True
    ok, msg = cf.decide(key, cf.APPROVED, ABA.email)
    assert not ok and "insufficientPermissions" in msg
    t = cf.tracked()[key]
    assert t["status"] == cf.APPROVED and not t["navan_sent_at"]
    gm.fail = False
    assert cf.send_navan(key)[0] and cf.tracked()[key]["navan_sent_at"] and len(gm.to("navan.com")) == 1


def test_decline_records_only(env):
    key = pending(env)
    ok, _ = cf.decide(key, cf.DECLINED, ABA.email, note="Out of budget")
    t = cf.tracked()[key]
    assert ok and env[2].sent == [] and t["status"] == cf.DECLINED and t["notes"] == "Out of budget"
    assert not cf.send_navan(key)[0] and env[2].sent == []


def test_navan_test_send_goes_to_aba_only_and_records_nothing(env):
    key = pending(env)
    before = cf.tracked()[key]
    assert cf.send_navan_test_to_admin(key, "test note")
    [m] = env[2].sent
    assert m["to"] == cf.ADMIN_EMAIL and m["cc"] is None and "navan" not in (m["to"] + str(m["cc"])).lower()
    assert cf.tracked()[key] == before


# ── Workflow admin (AppTest) ─────────────────────────────────────────────────────────────────────────────────

def admin(actor):
    runtime.OVERRIDE.clear()
    runtime.OVERRIDE["actor"] = actor
    ops_admin.OVERRIDE.update(config={"slack_channel": "", "email_list": []})
    email_health.OVERRIDE.update(probe=lambda: {"reachable": True, "sender": "", "reason": "", "detail": ""},
                                 last=lambda: {})
    at = AppTest.from_file("pages/6_Workflow_Admin.py", default_timeout=30)
    at.query_params["tab"] = "conference"
    at.run()
    assert not at.exception, at.exception
    return at


def btn(at, label):
    return next(b for b in at.button if b.label == label)


def texts(at):
    return " ".join(m.value for m in at.markdown) + " ".join(m.value for m in [*at.success, *at.error])


@pytest.fixture
def clean_admin():
    yield
    runtime.OVERRIDE.clear()
    ops_admin.OVERRIDE.clear()
    email_health.OVERRIDE.clear()


def test_admin_conference_area_is_admin_only(env, clean_admin):
    pending(env)
    at = admin(VND)
    assert any("restricted" in e.value for e in at.error) and "Anastasiia" not in texts(at)


def test_admin_approve_flow_then_check_now_button(env, clean_admin):
    key = pending(env)
    form, hub, gm = env
    at = admin(ABA)
    assert at.radio(key="admin_area").value == "conference"
    assert "Pending · 1" in texts(at) and "Anastasiia Stefanska" in texts(at)
    at.text_input(key="conf_note_3").input("Window seat")
    btn(at, "Approve").click().run()
    assert not at.exception, at.exception
    assert "emailed Navan" in texts(at) and "Pending · 0" in texts(at)
    assert len(gm.to("navan.com")) == 1 and "Window seat" in gm.sent[0]["body"]

    form.append(form_row("d", "2026-10-22T15:00:00Z", "Kofi", "kofi@x.com", event="Iceberg Day"))
    btn(at, "Check for new requests now").click().run()
    assert "1 new, 1 emailed to you" in texts(at) and "Kofi Stefanska" in texts(at)
    assert gm.sent[-1]["to"] == cf.ADMIN_EMAIL


def test_admin_failed_send_shows_reason_and_retry(env, clean_admin):
    pending(env)
    gm = env[2]
    gm.fail = True
    at = admin(ABA)
    btn(at, "Approve").click().run()
    assert "insufficientPermissions" in texts(at) and "Approved but not sent to Navan · 1" in texts(at)
    gm.fail = False
    btn(at, "Retry").click().run()
    assert not at.exception and len(gm.to("navan.com")) == 1 and "Approved but not sent" not in texts(at)


def test_admin_decline_sends_nothing(env, clean_admin):
    key = pending(env)
    at = admin(ABA)
    btn(at, "Decline").click().run()
    assert env[2].sent == [] and cf.tracked()[key]["status"] == cf.DECLINED


# ── Speaker Portal links ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section", ["start", "travel"])
def test_speaker_portal_links_to_conference_form(section):
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = section
    at.run()
    # Signed-out errors further down the travel section are covered by test_public_pages; the link renders first.
    links = [e.proto for e in at.get("link_button")]
    assert any(p.url == cf_url() and "Request conference support (Data Superheroes & Streamlit Creators)" in p.label
               for p in links)


def cf_url():
    return "https://app-superhero-creator-form-5rkbvp9kjmrkjjkqfbslqj.streamlit.app/"
