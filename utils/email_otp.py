"""Email verification-code sign-in for external users (vendors).

A 6-digit code is emailed via the app's Gmail sender. Only an HMAC of (email, code) is stored, with
a 10-minute expiry, 5 attempts, one-time use, and per-email / per-session / global send limits.
State is in process memory: a restart only means pending codes must be re-sent.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

log = logging.getLogger("cv.otp")

CODE_TTL = 10 * 60
MAX_ATTEMPTS = 5
SESSION_TTL = 12 * 3600
PER_EMAIL_WINDOW, PER_EMAIL_MAX = 15 * 60, 3
PER_EMAIL_DAY_MAX = 10
PER_SESSION_MAX = 5
GLOBAL_HOUR_MAX = 200

_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

# Tests set OVERRIDE["store"] to an OtpStore with a fake clock and sender.
OVERRIDE: dict = {}


def normalize(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    e = normalize(email)
    return len(e) <= 254 and bool(_EMAIL.match(e))


@dataclass
class Reply:
    ok: bool
    message: str
    retry_after: int = 0


@dataclass
class _Pending:
    digest: bytes
    expires: float
    attempts: int = 0


def _default_sender(to: str, subject: str, body_html: str) -> bool:
    from utils.sheets import send_gmail
    return send_gmail([to], subject, body_html)


class OtpStore:
    def __init__(self, sender=_default_sender, clock=time.time, key: bytes | None = None):
        self.sender, self.clock = sender, clock
        self.key = key or os.urandom(32)
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._sends: dict[str, deque] = defaultdict(deque)     # email -> send times (24h)
        self._session_sends: dict[str, int] = defaultdict(int)
        self._global: deque = deque()                          # send times (1h)

    def _digest(self, email, code) -> bytes:
        return hmac.new(self.key, f"{email}|{code}".encode(), hashlib.sha256).digest()

    def _limited(self, email, session_id, now) -> int:
        """Seconds to wait if a limit is hit, else 0."""
        sends = self._sends[email]
        while sends and now - sends[0] > 86400:
            sends.popleft()
        while self._global and now - self._global[0] > 3600:
            self._global.popleft()
        recent = [t for t in sends if now - t <= PER_EMAIL_WINDOW]
        if len(recent) >= PER_EMAIL_MAX:
            return int(PER_EMAIL_WINDOW - (now - recent[0])) + 1
        if len(sends) >= PER_EMAIL_DAY_MAX:
            return int(86400 - (now - sends[0])) + 1
        if self._session_sends[session_id] >= PER_SESSION_MAX:
            return SESSION_TTL
        if len(self._global) >= GLOBAL_HOUR_MAX:
            return int(3600 - (now - self._global[0])) + 1
        return 0

    def request_code(self, email: str, session_id: str) -> Reply:
        email = normalize(email)
        if not valid_email(email):
            return Reply(False, "Please enter a valid email address.")
        now = self.clock()
        with self._lock:
            wait = self._limited(email, session_id, now)
            if wait:
                mins = max(1, (wait + 59) // 60)
                return Reply(False, f"Too many code requests. Please try again in about {mins} minute(s).", wait)
            code = f"{secrets.randbelow(10**6):06d}"
            self._pending[email] = _Pending(self._digest(email, code), now + CODE_TTL)   # replaces any older code
            self._sends[email].append(now)
            self._session_sends[session_id] += 1
            self._global.append(now)
        body = (f"<p>Your Community Voices sign-in code is:</p>"
                f"<p style='font-size:24px;font-weight:bold;letter-spacing:4px'>{html.escape(code)}</p>"
                f"<p>It expires in {CODE_TTL // 60} minutes. If you didn't request it, you can ignore this email.</p>"
                f"<p>— Snowflake Community Voices</p>")
        try:
            sent = self.sender(email, "Your Community Voices sign-in code", body)
        except Exception:
            log.exception("otp send failed")
            sent = False
        if not sent:
            with self._lock:
                self._pending.pop(email, None)
            return Reply(False, "We couldn't send the code right now. Please try again in a minute, "
                                "or email community@snowflake.com.")
        return Reply(True, f"We sent a 6-digit code to {email}. It expires in {CODE_TTL // 60} minutes — "
                           "check your spam folder if you don't see it.")

    def verify_code(self, email: str, code: str) -> Reply:
        email = normalize(email)
        code = re.sub(r"\s", "", code or "")
        now = self.clock()
        with self._lock:
            p = self._pending.get(email)
            if p is None:
                return Reply(False, "No active code for this email. Please send a new code.")
            if now > p.expires:
                self._pending.pop(email, None)
                return Reply(False, "That code has expired. Please send a new one.")
            if p.attempts >= MAX_ATTEMPTS:
                self._pending.pop(email, None)
                return Reply(False, "Too many incorrect attempts. Please send a new code.")
            if not (code.isdigit() and len(code) == 6 and hmac.compare_digest(p.digest, self._digest(email, code))):
                p.attempts += 1
                left = MAX_ATTEMPTS - p.attempts
                if left <= 0:
                    self._pending.pop(email, None)
                    return Reply(False, "Too many incorrect attempts. Please send a new code.")
                return Reply(False, f"That code isn't right. {left} attempt(s) left.")
            self._pending.pop(email, None)                      # one-time use
            return Reply(True, "Signed in.")


# ── Streamlit wiring ──────────────────────────────────────────────────────────

import streamlit as st


@st.cache_resource
def _cached_store() -> OtpStore:
    """One store per server process, shared by all sessions."""
    try:
        secret = str(st.secrets.get("OTP_SECRET", "") or "")
    except Exception:
        secret = ""
    return OtpStore(key=hashlib.sha256(secret.encode()).digest() if secret else None)


def get_store() -> OtpStore:
    if "store" in OVERRIDE:
        return OVERRIDE["store"]
    return _cached_store()


def session_id() -> str:
    return st.session_state.setdefault("_otp_sid", secrets.token_hex(16))


def start_session(email: str) -> None:
    st.session_state["_otp_identity"] = {"email": normalize(email), "verified_at": get_store().clock()}


def session_email() -> str | None:
    """Verified email for this browser session, or None (expired sessions are cleared)."""
    s = st.session_state.get("_otp_identity")
    if not s:
        return None
    if get_store().clock() - s.get("verified_at", 0) > SESSION_TTL:
        st.session_state.pop("_otp_identity", None)
        return None
    return s.get("email") or None


def sign_out() -> None:
    for k in ("_otp_identity", "otp_email", "otp_stage"):
        st.session_state.pop(k, None)
