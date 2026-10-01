"""Interim password gate for program-team pages."""
from streamlit.testing.v1 import AppTest

STRONG = "correct-horse-battery-staple-42"


def _gate_app(scope="admin"):
    import streamlit as st
    from utils.identity import require_admin
    require_admin(scope)
    st.write("UNLOCKED")


def run(secrets, scope="admin", attempts=()):
    at = AppTest.from_function(_gate_app, args=(scope,), default_timeout=30)
    for k, v in secrets.items():
        at.secrets[k] = v
    at.run()
    for pw in attempts:
        at.text_input[0].input(pw)
        at.button[0].click()
        at.run()
    assert not at.exception, at.exception
    return at


def unlocked(at):
    return any("UNLOCKED" in m.value for m in at.markdown)


def test_locked_when_no_password_configured():
    at = run({})
    assert not unlocked(at) and any("locked" in e.value for e in at.error)
    assert len(at.text_input) == 0


def test_published_defaults_and_short_passwords_are_refused():
    for weak in ("community2026", "navan2026", "short"):
        at = run({"ADMIN_PASSWORD": weak})
        assert any("locked" in e.value for e in at.error) and not unlocked(at)


def test_wrong_then_right_password():
    at = run({"ADMIN_PASSWORD": STRONG}, attempts=["nope"])
    assert any("Incorrect" in e.value for e in at.error) and not unlocked(at)
    at.text_input[0].input(STRONG)
    at.button[0].click()
    at.run()
    assert unlocked(at)
    assert "admin" in at.session_state["_pw_unlocked"]    # persists for the rest of the session


def test_attempts_are_limited():
    at = run({"ADMIN_PASSWORD": STRONG}, attempts=["x"] * 5)
    assert any("Too many" in e.value for e in at.error)
    at.session_state["_pw_attempts"] = 5          # even the right password is refused once locked
    at.run()
    assert not unlocked(at) and any("Too many" in e.value for e in at.error)


def test_navan_password_opens_navan_but_not_admin():
    secrets = {"ADMIN_PASSWORD": STRONG, "NAVAN_PASSWORD": "navan-team-only-password-9"}
    at = run(secrets, scope="navan", attempts=["navan-team-only-password-9"])
    assert unlocked(at)
    at = run(secrets, scope="admin", attempts=["navan-team-only-password-9"])
    assert not unlocked(at)
