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


def is_admin(identity):
    import streamlit as st
    allowed = st.secrets.get("ADMIN_GOOGLE_SUBJECTS", [])
    return identity is not None and identity.subject in allowed


def require_admin():
    import streamlit as st
    identity = current_identity(st.user)
    if not is_admin(identity):
        st.error("This area is restricted to program administrators.")
        st.stop()
    return identity


def can_access(identity, event_id, role, memberships):
    return any(row["event_id"] == event_id and row["subject"] == identity.subject and row["role"] == role for row in memberships)
