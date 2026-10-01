"""Streamlit wiring for the workflow service: identity, configuration, and form tokens."""
from __future__ import annotations

import logging
import uuid

import streamlit as st

from utils.identity import current_identity, is_admin
from workflow.models import EMAIL, SLACK
from workflow.service import Actor, Config, Result, WorkflowService

log = logging.getLogger("cv.workflow")

# Tests set these to inject a service and identity without OIDC or Snowflake.
OVERRIDE: dict = {}


def get_actor() -> Actor | None:
    if "actor" in OVERRIDE:
        return OVERRIDE["actor"]
    identity = current_identity(st.user)
    if identity is None:
        return None
    return Actor(identity.subject, identity.email, is_admin(identity))


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


@st.cache_resource
def _build_service() -> WorkflowService | None:
    conns = _secret("connections", {}) or {}
    params = dict(conns.get("cv_workflow", {}) or {})
    if not params:
        return None
    import snowflake.connector
    from workflow.files import StageFileStore
    from workflow.snowflake_store import SnowflakeStore

    def connect():
        return snowflake.connector.connect(**params, paramstyle="qmark", client_session_keep_alive=True)

    store = SnowflakeStore(connect)
    files = StageFileStore(connect, lock=store._lock)

    notify = _secret("notify", {}) or {}
    channels = {}
    if notify.get("gmail"):
        from workflow.channels import GmailChannel
        g = notify["gmail"]
        channels[EMAIL] = GmailChannel(client_id=g["client_id"], client_secret=g["client_secret"],
                                       refresh_token=g["refresh_token"], sender=g["sender"])
    if notify.get("slack"):
        from workflow.channels import SlackChannel
        channels[SLACK] = SlackChannel(bot_token=notify["slack"]["bot_token"])
    enabled = frozenset(c for c in (EMAIL, SLACK) if c in channels) or frozenset({EMAIL})
    config = Config(app_base_url=_secret("APP_BASE_URL", ""), enabled_channels=enabled,
                    delivery_enabled=bool(_secret("DELIVERY_ENABLED", False)) and bool(channels))
    return WorkflowService(store, files, config, channels)


def get_service() -> WorkflowService | None:
    if "service" in OVERRIDE:
        return OVERRIDE["service"]
    return _build_service()


def form_token(name: str) -> str:
    """Stable per form instance across reruns; rotated only after a recorded submission."""
    key = f"_wf_token_{name}"
    if key not in st.session_state:
        st.session_state[key] = uuid.uuid4().hex
    return st.session_state[key]


def rotate_token(name: str) -> None:
    st.session_state.pop(f"_wf_token_{name}", None)


def after_action(svc: WorkflowService, result: Result, token_name: str | None = None) -> str:
    """Rotate the form token, try delivery once, and return an honest status message."""
    if result.status != "recorded":
        return result.message
    if token_name:
        rotate_token(token_name)
    msg = result.message
    if result.unroutable:
        msg += " Saved, but no program owner is on record for this event yet; the program team will see it in their queue."
    if not result.queued:
        return msg
    if not svc.config.delivery_enabled:
        return msg + " Notifications are queued; automatic delivery is not enabled yet."
    try:
        s = svc.dispatch(action_key=result.action_key)
    except Exception as exc:  # delivery problems never undo a recorded action
        log.warning("dispatch failed: %s", type(exc).__name__)
        return msg + " Notifications are queued and will be retried."
    if s["sent"] == result.queued:
        return msg + f" {s['sent']} notification(s) delivered to the provider."
    return msg + f" {s['sent']} of {result.queued} notification(s) delivered; the rest are queued for retry."
