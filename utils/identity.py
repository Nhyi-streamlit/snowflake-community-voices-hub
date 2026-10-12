"""Verified OIDC identity and event membership checks."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    issuer: str


def current_identity(user):
    if not getattr(user, "is_logged_in", False):
        return None
    issuer = str(user.get("iss", ""))
    subject = str(user.get("sub", ""))
    email = str(user.get("email", "")).strip().lower()
    if issuer != "https://accounts.google.com" or not subject or not email or user.get("email_verified") not in (True, "true"):
        return None
    return Identity(subject, email, issuer)


EMAIL_OTP_ISSUER = "email-otp"


def email_identity(email):
    """Identity for an email verified by a one-time code. Never matches the admin allowlist,
    which holds Google subjects only."""
    import hashlib
    email = (email or "").strip().lower()
    if not email:
        return None
    return Identity("email:" + hashlib.sha256(email.encode()).hexdigest()[:32], email, EMAIL_OTP_ISSUER)


def is_admin(identity):
    import streamlit as st
    if identity is None or identity.issuer != "https://accounts.google.com":
        return False
    try:
        allowed = st.secrets.get("ADMIN_GOOGLE_SUBJECTS", [])
    except Exception:
        allowed = []
    return identity is not None and identity.subject in allowed


# ── Interim password gate ─────────────────────────────────────────────────────
# Used until a dedicated External Google OAuth project exists. Passwords live only in
# managed secrets; there is no built-in default, and previously published defaults are refused.
_PUBLISHED_DEFAULTS = {"community2026", "navan2026"}
_MIN_LENGTH = 12
_MAX_ATTEMPTS = 5


def _configured_password(name):
    import streamlit as st
    try:
        value = str(st.secrets.get(name, "") or "")
    except Exception:
        value = ""
    if len(value) < _MIN_LENGTH or value in _PUBLISHED_DEFAULTS:
        return ""
    return value


def password_unlocked(scope="admin") -> bool:
    import streamlit as st
    unlocked = st.session_state.get("_pw_unlocked", set())
    return "admin" in unlocked or scope in unlocked


def lock_password_session():
    import streamlit as st
    st.session_state.pop("_pw_unlocked", None)


def _password_form(scope):
    """Render the unlock form. Returns only after a successful unlock (via rerun)."""
    import hmac
    import streamlit as st

    secrets = {"admin": _configured_password("ADMIN_PASSWORD")}
    if scope == "navan":
        secrets["navan"] = _configured_password("NAVAN_PASSWORD")
    if not any(secrets.values()):
        st.error("This area is locked. Set a strong ADMIN_PASSWORD (12+ characters, not a previously "
                 "published default) in the app secrets to enable access.")
        st.stop()

    attempts = st.session_state.get("_pw_attempts", 0)
    if attempts >= _MAX_ATTEMPTS:
        st.error("Too many incorrect attempts. Close this tab and try again later.")
        st.stop()

    st.markdown("#### Program team sign-in")
    with st.form(f"pw_gate_{scope}"):
        entered = st.text_input("Password", type="password")
        go = st.form_submit_button("Unlock", type="primary")
    if go:
        for granted, expected in secrets.items():
            if expected and hmac.compare_digest(entered.encode(), expected.encode()):
                st.session_state["_pw_unlocked"] = st.session_state.get("_pw_unlocked", set()) | {granted}
                st.session_state["_pw_attempts"] = 0
                st.rerun()
        st.session_state["_pw_attempts"] = attempts + 1
        if attempts + 1 >= _MAX_ATTEMPTS:
            st.rerun()
        st.error("Incorrect password.")
    st.stop()


def require_admin(scope="admin"):
    """Allow allowlisted Google admins, or a session unlocked with the interim password.

    scope="navan" also accepts NAVAN_PASSWORD (Navan portal only)."""
    import streamlit as st
    identity = current_identity(st.user)
    if is_admin(identity) or password_unlocked(scope):
        return identity
    _password_form(scope)


def can_access(identity, event_id, role, memberships):
    return any(row["event_id"] == event_id and row["subject"] == identity.subject and row["role"] == role for row in memberships)
