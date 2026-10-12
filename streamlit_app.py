import streamlit as st
from utils.email_otp import session_email, sign_out as otp_sign_out
from utils.identity import current_identity, is_admin, lock_password_session, password_unlocked

# Every page is registered so direct URLs keep working (program-team pages gate themselves with
# the interim password or an allowlisted Google sign-in). The sidebar is built here instead of by
# st.navigation so program-team pages are only listed for admins or after a password unlock.
PUBLIC = [
    st.Page("pages/0_Homepage.py", title="Homepage", icon=":material/home:", default=True),
    st.Page("pages/1_Speaker_Portal.py", title="Speaker Portal", icon=":material/mic:"),
    # Keeps the /Vendor_Portal URL that has already been shared with vendors.
    st.Page("pages/2_Vendor_Portal.py", title="Vendor Portal", icon=":material/storefront:", url_path="Vendor_Portal"),
    st.Page("pages/7_Help.py", title="Help & instructions", icon=":material/help:", url_path="help"),
]
WORKSPACE = st.Page("pages/5_Workspace.py", title="My event workspace", icon=":material/folder:", url_path="workspace")
TEAM = [
    st.Page("pages/6_Workflow_Admin.py", title="Workflow admin", icon=":material/inbox:", url_path="workflow-admin"),
    st.Page("pages/3_Admin.py", title="Admin Portal", icon=":material/admin_panel_settings:"),
    st.Page("pages/4_Navan_Portal.py", title="Navan Travel Portal", icon=":material/flight:"),
]


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


auth_configured = bool(_secret("auth"))
logged_in = bool(getattr(st.user, "is_logged_in", False))
identity = current_identity(st.user) if logged_in else None
otp_email = session_email()
signed_in = identity is not None or (not logged_in and bool(otp_email))
team_visible = is_admin(identity) or password_unlocked("admin") or password_unlocked("navan")

pg = st.navigation(PUBLIC + [WORKSPACE] + TEAM, position="hidden")

with st.sidebar:
    for p in PUBLIC:
        st.page_link(p)
    if signed_in:
        st.page_link(WORKSPACE)
    if team_visible:
        st.caption("Program team")
        for p in TEAM:
            st.page_link(p)
    st.divider()

    if not logged_in:
        if otp_email:
            # Signed in with an emailed code (no Google account needed).
            st.caption(f"Signed in as {otp_email}")
            if st.button("Sign out", icon=":material/logout:", key="otp_sign_out"):
                otp_sign_out()
                st.rerun()
        elif auth_configured and st.button("Sign in with Google", icon=":material/login:"):
            st.login()
    elif identity is None:
        st.error("Your Google account must have a verified email address.")
        if st.button("Sign out"):
            st.logout()
    else:
        st.caption(f"Signed in as {identity.email}")
        if not _secret("ADMIN_GOOGLE_SUBJECTS"):
            # One-time setup aid: shown only while the admin allowlist is empty.
            st.info("Admin setup: add this ID to ADMIN_GOOGLE_SUBJECTS in the app secrets.")
            st.code(identity.subject, language=None)
        if st.button("Sign out", icon=":material/logout:"):
            st.logout()

    if team_visible and not is_admin(identity):
        if st.button("Lock program team pages", icon=":material/lock:"):
            lock_password_session()
            st.rerun()
    elif not team_visible:
        # Unobtrusive entry point: the Admin Portal shows the program-team password form.
        st.page_link(TEAM[1], label="Program team sign-in", icon=":material/key:")

pg.run()
