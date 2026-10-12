"""Email delivery diagnostics: Google error reasons, no secret leakage, friendly vendor copy, admin self-test."""
import logging
import re

import pytest
from streamlit.testing.v1 import AppTest

from conftest import ABA, VND
from utils import email_health, email_otp as otp
from utils.gmail_diag import GmailClient, SendResult, fix_for, parse_google_error
from workflow import runtime
from workflow.service import Actor

TOKEN = "ya29.SECRET-ACCESS-TOKEN"
REFRESH = "1//SECRET-REFRESH"
BODY = "<p>secret body 123456</p>"
CREDS = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "csecret", "GOOGLE_REFRESH_TOKEN": REFRESH}


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


def api_error(status, reason=None, errors_reason=None, message="err", api_status="PERMISSION_DENIED"):
    err = {"code": status, "message": message, "status": api_status}
    if reason:
        err["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    if errors_reason:
        err["errors"] = [{"reason": errors_reason, "message": message}]
    return {"error": err}


class FakeHttp:
    """Token endpoint and Gmail endpoints answer with configurable responses."""

    def __init__(self, token=None, send=None, profile=None):
        self.token = token or Resp(200, {"access_token": TOKEN, "expires_in": 3600})
        self.send, self.profile = send or Resp(200, {"id": "m1"}), profile or Resp(200, {"emailAddress": "cv@x.com"})
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(url)
        r = self.token if "oauth2" in url else self.send
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, **kw):
        if isinstance(self.profile, Exception):
            raise self.profile
        return self.profile


def client(http, creds=CREDS):
    return GmailClient(lambda: dict(creds), http.post, http.get)


CASES = [
    ("SERVICE_DISABLED", FakeHttp(send=Resp(403, api_error(
        403, reason="SERVICE_DISABLED", errors_reason="accessNotConfigured",
        message=f"Gmail API has not been used in project 25733770608 before or it is disabled. {TOKEN}")))),
    ("ACCESS_TOKEN_SCOPE_INSUFFICIENT", FakeHttp(send=Resp(403, api_error(
        403, reason="ACCESS_TOKEN_SCOPE_INSUFFICIENT", errors_reason="insufficientPermissions",
        message="Request had insufficient authentication scopes.")))),
    ("insufficientPermissions", FakeHttp(send=Resp(403, api_error(
        403, errors_reason="insufficientPermissions", message="Insufficient Permission")))),
    ("invalid_grant", FakeHttp(token=Resp(400, {"error": "invalid_grant",
                                                "error_description": "Token has been expired or revoked."}))),
    ("network_error", FakeHttp(send=ConnectionError(f"boom {TOKEN}"))),
    ("http_500", FakeHttp(send=Resp(500, ValueError("not json")))),
]


@pytest.mark.parametrize("reason,http", CASES, ids=[c[0] for c in CASES])
def test_each_failure_reports_google_reason_without_secrets(reason, http, caplog):
    caplog.set_level(logging.DEBUG)
    c = client(http)
    r = c.send(["someone@example.com"], "Subj", BODY)
    assert not r and r.reason == reason
    assert fix_for(r.reason)
    blob = " ".join([r.detail, str(c.last), caplog.text])
    for secret in (TOKEN, REFRESH, "csecret", BODY, "123456", "someone@"):
        assert secret not in blob
    assert c.last["reason"] == reason and c.last["to_domain"] == "example.com"
    assert reason in caplog.text            # the reason itself is logged for diagnosis


def test_success_and_missing_credentials():
    c = client(FakeHttp())
    assert c.send(["a@b.com"], "s", BODY).ok and c.last["ok"]
    r = client(FakeHttp(), creds={}).send(["a@b.com"], "s", BODY)
    assert r.reason == "missing_credentials" and "not set" in fix_for(r.reason)


def test_scope_detected_from_message_only():
    r = parse_google_error(403, {"error": {"message": "Request had insufficient authentication scopes."}})
    assert r.reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT"


def test_probe_reachability():
    assert client(FakeHttp()).probe() == {"reachable": True, "sender": "cv@x.com", "reason": "", "detail": ""}
    p = client(FakeHttp(profile=CASES[0][1].send)).probe()       # SERVICE_DISABLED on the profile call
    assert not p["reachable"] and p["reason"] == "SERVICE_DISABLED"
    # gmail.send-only tokens can't read the profile, but the API answered, so it's enabled.
    http = FakeHttp(profile=Resp(403, api_error(403, reason="ACCESS_TOKEN_SCOPE_INSUFFICIENT")))
    assert client(http).probe()["reachable"] is True
    assert client(FakeHttp(token=CASES[3][1].token)).probe()["reason"] == "invalid_grant"


# ── OTP store: vendors keep the friendly message; the reason is recorded and logged ─────────────

@pytest.mark.parametrize("reason", ["SERVICE_DISABLED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "invalid_grant"])
def test_vendor_sees_friendly_message_and_reason_is_recorded(reason, caplog):
    caplog.set_level(logging.DEBUG)
    store = otp.OtpStore(sender=lambda *a: SendResult(False, reason, 403), key=b"k" * 32)
    r = store.request_code("Vendor@EventCo.example", "sid")
    assert not r.ok and r.message == otp.FRIENDLY_SEND_ERROR and reason not in r.message
    assert store.last_send["reason"] == reason and not store.last_send["ok"]
    assert reason in caplog.text and "eventco" not in caplog.text.lower()
    assert not re.search(r"\b\d{6}\b", caplog.text)


def test_sender_exception_is_recorded_not_raised():
    def boom(*a):
        raise RuntimeError("x")
    store = otp.OtpStore(sender=boom, key=b"k" * 32)
    assert not store.request_code("a@b.com", "s").ok
    assert store.last_send["reason"] == "exception:RuntimeError"


# ── Admin Email health panel ─────────────────────────────────────────────────────────────────────

class Box:
    def __init__(self, result=True):
        self.sent, self.result = [], result

    def __call__(self, to, subject, body):
        self.sent.append(to)
        return self.result


@pytest.fixture
def admin_page():
    def _run(actor, probe=None, last=None, box=None):
        runtime.OVERRIDE.clear()
        runtime.OVERRIDE["actor"] = actor
        box = box or Box()
        otp.OVERRIDE["store"] = otp.OtpStore(sender=box, key=b"k" * 32)
        email_health.OVERRIDE["probe"] = lambda: probe or {"reachable": True, "sender": "cv@x.com",
                                                          "reason": "", "detail": ""}
        email_health.OVERRIDE["last"] = lambda: last or {}
        at = AppTest.from_file("pages/6_Workflow_Admin.py", default_timeout=30)
        at.query_params["tab"] = "workflow"
        at.run()
        assert not at.exception, at.exception
        return at, box
    yield _run
    runtime.OVERRIDE.clear(); otp.OVERRIDE.clear(); email_health.OVERRIDE.clear()


def _btn(at, start):
    return next(b for b in at.button if b.label.startswith(start))


def test_health_panel_shows_reason_and_fix_even_without_workflow_store(admin_page):
    at, _ = admin_page(ABA, probe={"reachable": False, "sender": "", "reason": "SERVICE_DISABLED",
                                   "detail": "Gmail API has not been used in project 25733770608"},
                       last={"ok": False, "reason": "SERVICE_DISABLED", "at": 1_760_000_000.0, "detail": ""})
    text = " ".join(m.value for m in at.markdown)
    assert "Email health" in text and "SERVICE\\_DISABLED" in text
    _btn(at, "Check now").click().run()
    assert any("Enable it in Google Cloud console" in e.value for e in at.error)
    assert any("25733770608" in c.value for c in at.caption)
    assert any("Workflow store is not configured" in w.value for w in at.warning)   # panel came first


def test_test_button_sends_only_to_signed_in_admin(admin_page):
    at, box = admin_page(ABA)
    _btn(at, "Send test code to me").click().run()
    assert box.sent == [ABA.email]
    assert any("Test code sent" in s.value for s in at.success)


def test_test_button_reports_failure_reason(admin_page):
    at, box = admin_page(ABA, box=Box(SendResult(False, "SERVICE_DISABLED", 403)))
    _btn(at, "Send test code to me").click().run()
    assert any("SERVICE\\_DISABLED" in e.value and "Gmail API is disabled" in e.value for e in at.error)


def test_password_only_admin_cannot_send_test(admin_page):
    at, box = admin_page(Actor("interim-password-admin", "", is_admin=True))
    assert _btn(at, "Send test code to me").disabled
    assert box.sent == []


def test_non_admin_never_sees_panel(admin_page):
    at, box = admin_page(VND)
    assert not any("Email health" in m.value for m in at.markdown)
    assert any("restricted" in e.value for e in at.error)
