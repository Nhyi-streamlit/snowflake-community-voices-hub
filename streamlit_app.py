import streamlit as st
from utils.identity import current_identity, is_admin

# Public pages work without sign-in (homepage, speaker resources, audience feedback QR links).
# Protected pages are added only for verified identities, and each page re-checks access itself.
pages = [
    st.Page("pages/0_Homepage.py", title="Homepage", icon=":material/home:", default=True),
    st.Page("pages/1_Speaker_Portal.py", title="Speaker Portal", icon=":material/mic:"),
]

def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


auth_configured = bool(_secret("auth"))
identity = current_identity(st.user) if getattr(st.user, "is_logged_in", False) else None
if not getattr(st.user, "is_logged_in", False):
    st.sidebar.caption("Speakers, vendors, and the program team sign in to reach their event workspace.")
    if not auth_configured:
        st.sidebar.warning("Sign-in is not configured yet. Add the [auth] secrets to enable it.")
    elif st.sidebar.button("Sign in with Google", icon=":material/login:"):
        st.login()
elif identity is None:
    st.sidebar.error("Your Google account must have a verified email address.")
    if st.sidebar.button("Sign out"):
        st.logout()
else:
    st.sidebar.caption(f"Signed in as {identity.email}")
    if not _secret("ADMIN_GOOGLE_SUBJECTS"):
        # One-time setup aid: shown only while the admin allowlist is empty.
        st.sidebar.info("Admin setup: add this ID to ADMIN_GOOGLE_SUBJECTS in the app secrets.")
        st.sidebar.code(identity.subject, language=None)
    if st.sidebar.button("Sign out", icon=":material/logout:"):
        st.logout()
    pages += [
        st.Page("pages/5_Workspace.py", title="My event workspace", icon=":material/folder:", url_path="workspace"),
        st.Page("pages/2_Vendor_Portal.py", title="Vendor Portal", icon=":material/storefront:"),
    ]
    if is_admin(identity):
        pages += [
            st.Page("pages/6_Workflow_Admin.py", title="Workflow admin", icon=":material/inbox:",
                    url_path="workflow-admin"),
            st.Page("pages/3_Admin.py", title="Admin Portal", icon=":material/admin_panel_settings:"),
            st.Page("pages/4_Navan_Portal.py", title="Navan Travel Portal", icon=":material/flight:"),
        ]

pg = st.navigation(pages)
pg.run()
