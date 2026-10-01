"""Notification channels. Each send returns a provider message ID or raises DeliveryError.

Errors never include credentials or response bodies; only a short, safe description.
"""
from __future__ import annotations

import base64
import time
from email.message import EmailMessage

import requests


class DeliveryError(Exception):
    def __init__(self, message: str, *, retryable: bool, uncertain: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain   # request may have reached the provider


def _one_line(s: str, limit: int) -> str:
    return " ".join((s or "").split())[:limit]


def _http_error(resp) -> DeliveryError:
    code = resp.status_code
    return DeliveryError(f"HTTP {code}", retryable=code in (401, 408, 429) or code >= 500)


def _post(url, **kw):
    try:
        return requests.post(url, timeout=20, **kw)
    except requests.exceptions.ReadTimeout:
        raise DeliveryError("Timed out waiting for provider", retryable=False, uncertain=True) from None
    except requests.exceptions.RequestException as exc:
        raise DeliveryError(f"Network error: {type(exc).__name__}", retryable=True) from None


class GmailChannel:
    """Plain-text email via the Gmail API from a configured program mailbox."""

    def __init__(self, *, client_id: str, client_secret: str, refresh_token: str, sender: str):
        self._cid, self._secret, self._refresh, self.sender = client_id, client_secret, refresh_token, sender
        self._token, self._exp = "", 0.0

    def _access_token(self):
        if self._token and time.time() < self._exp:
            return self._token
        resp = _post("https://oauth2.googleapis.com/token", data={
            "client_id": self._cid, "client_secret": self._secret,
            "refresh_token": self._refresh, "grant_type": "refresh_token"})
        if resp.status_code != 200:
            raise DeliveryError(f"Mail auth failed (HTTP {resp.status_code})", retryable=True)
        data = resp.json()
        self._token, self._exp = data["access_token"], time.time() + data.get("expires_in", 3500) - 60
        return self._token

    def send(self, address: str, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["To"] = _one_line(address, 320)
        msg["From"] = _one_line(self.sender, 320)
        msg["Subject"] = _one_line(subject, 200)
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = _post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                     json={"raw": raw}, headers={"Authorization": f"Bearer {self._access_token()}"})
        if resp.status_code != 200:
            raise _http_error(resp)
        mid = resp.json().get("id")
        if not mid:
            raise DeliveryError("Provider returned no message ID", retryable=False, uncertain=True)
        return mid


def slack_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlackChannel:
    """Direct message to an internal Slack user ID via a scoped bot token (chat:write)."""
    PERMANENT = {"user_not_found", "channel_not_found", "not_in_channel", "invalid_auth",
                 "account_inactive", "cannot_dm_bot", "is_archived"}

    def __init__(self, *, bot_token: str):
        self._token = bot_token

    def send(self, address: str, subject: str, body: str) -> str:
        resp = _post("https://slack.com/api/chat.postMessage",
                     json={"channel": address, "text": slack_escape(f"*{subject}*\n{body}"),
                           "unfurl_links": False},
                     headers={"Authorization": f"Bearer {self._token}"})
        if resp.status_code != 200:
            raise _http_error(resp)
        data = resp.json()
        if not data.get("ok"):
            err = str(data.get("error", "unknown"))[:60]
            raise DeliveryError(f"Slack: {err}", retryable=err not in self.PERMANENT)
        return str(data.get("ts"))


class FakeChannel:
    """Test double. `script` is a list of outcomes consumed per send: 'ok', 'retry', 'fail', 'uncertain'."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.sent: list[tuple[str, str, str]] = []

    def send(self, address, subject, body):
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "retry":
            raise DeliveryError("HTTP 503", retryable=True)
        if outcome == "fail":
            raise DeliveryError("HTTP 400", retryable=False)
        if outcome == "uncertain":
            raise DeliveryError("Timed out waiting for provider", retryable=False, uncertain=True)
        self.sent.append((address, subject, body))
        return f"fake-{len(self.sent)}"
