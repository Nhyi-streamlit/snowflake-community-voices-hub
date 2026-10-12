"""Admin-only Email health panel: sender, Gmail API reachability, last error, self-test."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from utils import email_otp as otp
from utils.gmail_diag import fix_for
from workflow.ui import md

# Tests set OVERRIDE["probe"] (callable -> dict) and OVERRIDE["last"] (callable -> dict).
OVERRIDE: dict = {}


def _probe() -> dict:
    if "probe" in OVERRIDE:
        return OVERRIDE["probe"]()
    from utils.sheets import gmail_probe
    return gmail_probe()


def _last_gmail() -> dict:
    if "last" in OVERRIDE:
        return OVERRIDE["last"]()
    from utils.sheets import gmail_client
    return dict(gmail_client().last)


def _configured_sender() -> str:
    try:
        return str(st.secrets.get("GMAIL_SENDER", "") or "")
    except Exception:
        return ""


def _when(ts) -> str:
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "—"


def render(actor) -> None:
    """Call only after admin authorization. `actor.email` may be empty (password-only admin)."""
    with st.container(border=True):
        st.markdown("#### :material/mail: Email health")
        st.caption("Sign-in codes and notifications are sent from this mailbox through the Gmail API.")
        if st.button("Check now", icon=":material/refresh:", key="eh_check"):
            st.session_state["eh_probe"] = _probe()
        p = st.session_state.get("eh_probe")
        c1, c2, c3 = st.columns(3)
        sender = (p or {}).get("sender") or _configured_sender() or "Unknown (send-only token)"
        c1.markdown(f"**Sender**  \n{md(sender)}")
        if p is None:
            c2.markdown("**Gmail API**  \nNot checked yet")
        elif p["reachable"]:
            c2.markdown("**Gmail API**  \n:green[:material/check_circle: Reachable]")
        else:
            c2.markdown(f"**Gmail API**  \n:red[:material/error: Unreachable]: `{md(p['reason'])}`")
        last = _last_gmail()
        if not last:
            c3.markdown("**Last send**  \nNone since app start")
        elif last.get("ok"):
            c3.markdown(f"**Last send**  \n:green[OK] · {_when(last.get('at'))}")
        else:
            c3.markdown(f"**Last send**  \n:red[`{md(last.get('reason'))}`] · {_when(last.get('at'))}")
        reason = (p and not p["reachable"] and p["reason"]) or (last and not last.get("ok") and last.get("reason"))
        if reason:
            st.error(fix_for(reason), icon=":material/build:")
            detail = (p or {}).get("detail") if p and not p["reachable"] else last.get("detail")
            if detail:
                st.caption(f"Google said: {md(detail)}")

        if not actor.email:
            st.button("Send test code to me", icon=":material/send:", key="eh_test", disabled=True,
                      help="Sign in with Google to test: password-only sessions have no email address.")
            return
        if st.button(f"Send test code to me ({actor.email})", icon=":material/send:", key="eh_test"):
            # Recipient is always the signed-in admin, never a typed address.
            r = otp.get_store().request_code(actor.email, otp.session_id())
            if r.ok:
                st.success(f"Test code sent to {md(actor.email)}. It should arrive within a minute.",
                           icon=":material/mark_email_read:")
            elif r.retry_after:
                st.warning(r.message, icon=":material/schedule:")
            else:
                why = otp.get_store().last_send.get("reason")
                st.error(f"Test send failed{f': `{md(why)}`' if why else ''}. {fix_for(why)}",
                         icon=":material/error:")
