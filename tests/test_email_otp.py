"""Email one-time-code sign-in: hashing, expiry, attempts, one-time use, and rate limits."""
import re

import pytest

from utils import email_otp as otp
from utils.identity import email_identity, is_admin


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class Outbox:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, to, subject, body):
        if self.ok is None:
            raise ConnectionError("gmail down")
        self.sent.append((to, subject, body))
        return self.ok

    def last_code(self):
        return re.search(r">(\d{6})<", self.sent[-1][2]).group(1)


@pytest.fixture
def mk():
    def _mk(ok=True):
        clock, box = Clock(), Outbox(ok)
        return otp.OtpStore(sender=box, clock=clock, key=b"k" * 32), box, clock
    return _mk


def test_right_code_signs_in_once(mk):
    s, box, _ = mk()
    assert s.request_code("Vendor@EventCo.example ", "sid").ok
    assert box.sent[0][0] == "vendor@eventco.example"
    code = box.last_code()
    assert s.verify_code("vendor@eventco.example", f" {code[:3]} {code[3:]} ").ok      # spaces tolerated
    assert not s.verify_code("vendor@eventco.example", code).ok                        # one-time use


def test_code_never_stored_in_plain_text(mk):
    s, box, _ = mk()
    s.request_code("a@b.example", "sid")
    code = box.last_code()
    assert code.encode() not in repr(s._pending).encode()
    assert len(s._pending["a@b.example"].digest) == 32


def test_wrong_attempts_then_locked(mk):
    s, box, _ = mk()
    s.request_code("a@b.example", "sid")
    code = box.last_code()
    wrong = "000000" if code != "000000" else "111111"
    msgs = [s.verify_code("a@b.example", wrong).message for _ in range(5)]
    assert "4 attempt(s) left" in msgs[0] and "Too many incorrect" in msgs[-1]
    assert not s.verify_code("a@b.example", code).ok                                   # locked out after 5


def test_code_expires(mk):
    s, box, clock = mk()
    s.request_code("a@b.example", "sid")
    clock.t += otp.CODE_TTL + 1
    r = s.verify_code("a@b.example", box.last_code())
    assert not r.ok and "expired" in r.message


def test_new_code_replaces_old(mk):
    s, box, clock = mk()
    s.request_code("a@b.example", "sid")
    first = box.last_code()
    s.request_code("a@b.example", "sid")
    second = box.last_code()
    if first != second:
        assert not s.verify_code("a@b.example", first).ok
        s.request_code("a@b.example", "sid2")
    assert s.verify_code("a@b.example", box.last_code()).ok


def test_rate_limits(mk, monkeypatch):
    s, box, clock = mk()
    for _ in range(3):
        assert s.request_code("a@b.example", "s1").ok
    r = s.request_code("a@b.example", "s2")
    assert not r.ok and "Too many code requests" in r.message and r.retry_after > 0
    clock.t += otp.PER_EMAIL_WINDOW + 1
    assert s.request_code("a@b.example", "s3").ok                                      # window rolled over

    for i in range(otp.PER_SESSION_MAX - 0):
        s.request_code(f"u{i}@b.example", "same-session")
    assert not s.request_code("fresh@b.example", "same-session").ok                    # per-session cap

    monkeypatch.setattr(otp, "GLOBAL_HOUR_MAX", len(s._global))
    assert not s.request_code("other@b.example", "new-session").ok                     # global cap


def test_daily_limit(mk):
    s, _, clock = mk()
    for i in range(otp.PER_EMAIL_DAY_MAX):
        assert s.request_code("a@b.example", f"s{i}").ok
        clock.t += otp.PER_EMAIL_WINDOW + 1
    assert not s.request_code("a@b.example", "late").ok


def test_bad_email_rejected_without_sending(mk):
    s, box, _ = mk()
    for bad in ("", "nope", "a@b", "a b@c.example", "x@y.example\nBcc: z@w.example"):
        assert not s.request_code(bad, "sid").ok
    assert box.sent == []


@pytest.mark.parametrize("ok", [False, None])
def test_send_failure_is_friendly_and_leaves_no_code(mk, ok):
    s, box, _ = mk(ok)
    r = s.request_code("a@b.example", "sid")
    assert not r.ok and "couldn't send" in r.message
    assert "a@b.example" not in s._pending


def test_email_identity_is_stable_and_never_admin():
    a, b = email_identity("Vendor@X.example"), email_identity("vendor@x.example")
    assert a == b and a.subject.startswith("email:") and a.email == "vendor@x.example"
    assert email_identity("") is None
    assert not is_admin(a)
