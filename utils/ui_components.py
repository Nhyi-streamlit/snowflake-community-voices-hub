"""Shared UI building blocks so every page looks like the Vendor Portal.

Rule: HTML is only emitted from constant templates. Every argument interpolated into HTML goes
through html.escape. Everything else uses native Streamlit elements, and user data passed
to Markdown must go through workflow.ui.md().
"""
from __future__ import annotations

import html

import streamlit as st

from workflow.ui import md  # noqa: F401  (re-exported for pages)

CONTACT_EMAIL = "community@snowflake.com"

HERO_THEMES = {
    "navy": "linear-gradient(135deg,#0E2346 0%,#1B3A6B 100%)",      # Homepage / Help
    "sky": "linear-gradient(135deg,#0B5394 0%,#29B5E8 100%)",       # Speaker Portal
    "purple": "linear-gradient(135deg,#44337A 0%,#6B46C1 100%)",    # Vendor Portal
}

# Help page section keys, used for ?topic= deep links.
HELP_TOPICS = {
    "speakers": "Speakers",
    "organizers": "Event organizers",
    "signin": "Signing in",
    "bulk": "Bulk upload template",
    "travel": "Travel & reimbursement",
    "contact": "Contact",
}

BADGE = {"Pending": ("orange", ":material/hourglass_top:"), "Approved": ("green", ":material/check_circle:"),
         "Waitlisted": ("blue", ":material/schedule:"), "Not a Fit": ("red", ":material/cancel:"),
         "Not a fit": ("red", ":material/cancel:"), "Closed": ("gray", ":material/event_busy:")}


def hero(eyebrow: str, title: str, body: str, theme: str = "navy") -> None:
    bg = HERO_THEMES.get(theme, HERO_THEMES["navy"])
    e, t, b = (html.escape(str(x)) for x in (eyebrow, title, body))
    st.markdown(f"""
<div class="page-hero" style="background:{bg};">
  <div class="eyebrow">{e}</div>
  <h1>{t}</h1>
  <p>{b}</p>
</div>""", unsafe_allow_html=True)


def step_cards(steps: list[tuple[str, str]]) -> None:
    """Numbered "How it works" cards: [(title, caption), ...]. Static copy only."""
    cols = st.columns(len(steps))
    for i, (col, (title, caption)) in enumerate(zip(cols, steps), start=1):
        with col, st.container(border=True, height="stretch"):
            st.markdown(f"**{i}. {title}**")
            st.caption(caption)


_URLS = {"pages/0_Homepage.py": "/", "pages/1_Speaker_Portal.py": "/Speaker_Portal",
         "pages/2_Vendor_Portal.py": "/Vendor_Portal", "pages/7_Help.py": "/help", "pages/5_Workspace.py": "/workspace"}


def page_link(page: str, label: str, icon: str | None = None, query_params: dict | None = None, **kw) -> None:
    """st.page_link that degrades to a plain link when the page isn't registered (page run standalone)."""
    try:
        st.page_link(page, label=label, icon=icon, query_params=query_params, **kw)
    except Exception:
        from urllib.parse import urlencode
        url = _URLS.get(page, "/") + (f"?{urlencode(query_params)}" if query_params else "")
        st.markdown(f"[{label}]({url})")


def cta_row(ctas: list[dict]) -> None:
    """Big call-to-action cards: [{"page", "label", "caption", "icon"}, ...]."""
    cols = st.columns(len(ctas), gap="medium")
    for col, c in zip(cols, ctas):
        with col, st.container(border=True, height="stretch"):
            st.markdown(f"### {c['icon']} {c['label']}")
            st.caption(c["caption"])
            page_link(c["page"], label=c.get("button", "Get started"), icon=":material/arrow_forward:",
                      width="stretch")


def faq(items: list[tuple[str, str]]) -> None:
    for q, a in items:
        with st.expander(q):
            st.markdown(a)


def status_badge(status: str) -> None:
    color, icon = BADGE.get(status, ("gray", ":material/help:"))
    st.badge(status or "Unknown", color=color, icon=icon)


def coming_soon(title: str, body: str = "") -> None:
    """The single friendly card shown for paused features."""
    with st.container(border=True):
        st.markdown(f"#### :material/schedule: {title}: coming soon")
        st.markdown(body or "We're finishing this part of the portal.")
        st.markdown(f"In the meantime, contact the program team at [{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL}) "
                    "and we'll take care of it for you.")


def help_link(topic: str, label: str | None = None) -> None:
    """Link to a section of the Help & instructions page."""
    page_link("pages/7_Help.py", label=label or f"Help: {HELP_TOPICS.get(topic, 'instructions')}",
              icon=":material/help:", query_params={"topic": topic})


def otp_sign_in(prefix: str = "otp") -> None:
    """Email one-time-code sign-in panel (no Google account needed). On success it reruns signed in."""
    from utils import email_otp as otp
    ss = st.session_state
    store = otp.get_store()
    with st.container(border=True):
        st.markdown("#### Sign in with your email")
        if ss.get("otp_stage") != "code":
            st.caption("We'll email you a 6-digit code. No password or account needed.")
            with st.form(f"{prefix}_email_form", border=False):
                email = st.text_input("Email address", key=f"{prefix}_email_input", placeholder="you@company.com")
                send = st.form_submit_button("Email me a code", type="primary", width="stretch")
            if send:
                with st.spinner("Sending…"):
                    r = store.request_code(email, otp.session_id())
                if r.ok:
                    ss.otp_email, ss.otp_stage, ss.otp_notice = otp.normalize(email), "code", r.message
                    st.rerun()
                st.error(r.message, icon=":material/error:")
        else:
            st.success(ss.get("otp_notice", "Code sent."), icon=":material/mark_email_read:")
            with st.form(f"{prefix}_code_form", border=False):
                code = st.text_input("6-digit code", key=f"{prefix}_code_input", max_chars=7, placeholder="123456")
                verify = st.form_submit_button("Sign in", type="primary", width="stretch")
            if verify:
                r = store.verify_code(ss.otp_email, code)
                if r.ok:
                    otp.start_session(ss.otp_email)
                    for k in ("otp_stage", "otp_notice"):
                        ss.pop(k, None)
                    st.rerun()
                st.error(r.message, icon=":material/error:")
            c1, c2 = st.columns(2)
            if c1.button("Resend code", key=f"{prefix}_resend", width="stretch"):
                r = store.request_code(ss.otp_email, otp.session_id())
                ss.otp_notice = r.message
                if not r.ok:
                    st.error(r.message, icon=":material/error:")
                else:
                    st.rerun()
            if c2.button("Use a different email", key=f"{prefix}_change", width="stretch"):
                for k in ("otp_stage", "otp_email", "otp_notice"):
                    ss.pop(k, None)
                st.rerun()
        help_link("signin", "Didn't get a code?")
