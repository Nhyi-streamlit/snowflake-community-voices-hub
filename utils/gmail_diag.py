"""Gmail send with a diagnosable failure reason.

Turns Google token / Gmail API errors into a short reason code (e.g. SERVICE_DISABLED,
ACCESS_TOKEN_SCOPE_INSUFFICIENT, invalid_grant) plus a trimmed, token-scrubbed message.
Never records tokens, recipients' full addresses, or email bodies.
"""
from __future__ import annotations

import base64
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText

log = logging.getLogger("cv.gmail")

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

# Plain-language fixes shown to admins on the Email health panel.
FIXES = {
    "SERVICE_DISABLED": "The Gmail API is disabled for the OAuth client's Google Cloud project. "
                        "Enable it in Google Cloud console > APIs & Services > Library > Gmail API, "
                        "wait a few minutes, then send a test code.",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "The refresh token lacks the gmail.send scope. Re-authorize the "
                                       "sender mailbox with gmail.send and update GOOGLE_REFRESH_TOKEN.",
    "insufficientPermissions": "The refresh token lacks the gmail.send scope. Re-authorize with gmail.send.",
    "invalid_grant": "The refresh token was revoked or expired. Re-authorize the sender mailbox and update "
                     "GOOGLE_REFRESH_TOKEN in the app secrets.",
    "invalid_client": "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are wrong or the client was deleted.",
    "missing_credentials": "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET or GOOGLE_REFRESH_TOKEN is not set.",
    "rateLimitExceeded": "Gmail is rate-limiting this mailbox. Wait and retry.",
    "dailyLimitExceeded": "The mailbox hit Gmail's daily sending limit. Retry tomorrow or use another sender.",
    "network_error": "Couldn't reach Google. Usually temporary — retry in a minute.",
}

_BEARER = re.compile(r"(ya29\.[\w\-.]+|1//[\w\-.]+|Bearer\s+\S+)", re.I)


def scrub(text: str, limit: int = 200) -> str:
    return _BEARER.sub("[redacted]", str(text or ""))[:limit]


def fix_for(reason: str | None) -> str:
    if not reason:
        return ""
    return FIXES.get(reason, "See the Google error message below and the app logs.")


@dataclass
class SendResult:
    ok: bool
    reason: str = ""          # "" on success
    status: int = 0           # HTTP status, 0 if none
    detail: str = ""          # scrubbed, trimmed Google message

    def __bool__(self) -> bool:   # lets callers keep treating the result as a bool
        return self.ok


class TokenError(Exception):
    def __init__(self, reason: str, detail: str = "", status: int = 0):
        super().__init__(reason)
        self.reason, self.detail, self.status = reason, detail, status


def parse_google_error(status: int, payload) -> SendResult:
    """Reason from an OAuth token error ({"error": "invalid_grant"}) or an API error body."""
    reason, detail = "", ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, str):                         # OAuth token endpoint
            reason, detail = err, payload.get("error_description", "")
        elif isinstance(err, dict):                      # Google API error
            detail = err.get("message", "")
            for d in err.get("details") or []:
                if isinstance(d, dict) and d.get("reason"):
                    reason = d["reason"]
                    break
            if not reason:
                for e in err.get("errors") or []:
                    if isinstance(e, dict) and e.get("reason"):
                        reason = e["reason"]
                        break
            if not reason and "scope" in detail.lower():
                reason = "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
            reason = reason or err.get("status") or ""
    return SendResult(False, reason or f"http_{status}", status, scrub(detail))


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else "?"


class GmailClient:
    """`http_post` / `http_get` follow requests' signatures; tests pass fakes."""

    def __init__(self, creds, http_post, http_get, clock=lambda: datetime.now(timezone.utc)):
        self.creds, self.post, self.get, self.clock = creds, http_post, http_get, clock
        self._lock = threading.Lock()
        self.last: dict = {}           # {"at", "ok", "reason", "detail", "to_domain"}

    def token(self) -> str:
        c = self.creds()
        if not (c.get("GOOGLE_CLIENT_ID") and c.get("GOOGLE_CLIENT_SECRET") and c.get("GOOGLE_REFRESH_TOKEN")):
            raise TokenError("missing_credentials")
        resp = self.post("https://oauth2.googleapis.com/token", data={
            "client_id": c["GOOGLE_CLIENT_ID"], "client_secret": c["GOOGLE_CLIENT_SECRET"],
            "refresh_token": c["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=10)
        if resp.status_code != 200:
            r = parse_google_error(resp.status_code, _json(resp))
            raise TokenError(r.reason, r.detail, r.status)
        return _json(resp)["access_token"]

    def _record(self, res: SendResult, to: list[str]) -> SendResult:
        with self._lock:
            self.last = {"at": self.clock(), "ok": res.ok, "reason": res.reason, "detail": res.detail,
                         "to_domain": ", ".join(sorted({_domain(t) for t in to}))}
        if not res.ok:
            log.warning("gmail send failed reason=%s status=%s", res.reason, res.status)
        return res

    def send(self, to: list[str], subject: str, body_html: str, token_fn=None,
             cc: list[str] | None = None) -> SendResult:
        try:
            token = (token_fn or self.token)()
        except TokenError as e:
            return self._record(SendResult(False, e.reason, e.status, scrub(e.detail)), to)
        except Exception as e:
            return self._record(SendResult(False, "network_error", 0, scrub(type(e).__name__)), to)
        msg = MIMEText(body_html, "html")
        msg["To"], msg["Subject"] = ", ".join(to), subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            resp = self.post(SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        except Exception as e:
            return self._record(SendResult(False, "network_error", 0, scrub(type(e).__name__)), to)
        if resp.status_code == 200:
            return self._record(SendResult(True, "", 200), to)
        return self._record(parse_google_error(resp.status_code, _json(resp)), to)

    def probe(self, token_fn=None) -> dict:
        """{"reachable", "sender", "reason", "detail"} via users/me/profile (read-only)."""
        try:
            token = (token_fn or self.token)()
            resp = self.get(PROFILE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        except TokenError as e:
            return {"reachable": False, "sender": "", "reason": e.reason, "detail": scrub(e.detail)}
        except Exception as e:
            return {"reachable": False, "sender": "", "reason": "network_error", "detail": scrub(type(e).__name__)}
        if resp.status_code == 200:
            return {"reachable": True, "sender": _json(resp).get("emailAddress", ""), "reason": "", "detail": ""}
        r = parse_google_error(resp.status_code, _json(resp))
        if r.reason in SCOPE_REASONS:
            # A gmail.send-only token can't read the profile, but the API answered, so it is enabled.
            return {"reachable": True, "sender": "", "reason": "", "detail": "profile_not_readable"}
        return {"reachable": False, "sender": "", "reason": r.reason, "detail": r.detail}


SCOPE_REASONS = {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return {}
