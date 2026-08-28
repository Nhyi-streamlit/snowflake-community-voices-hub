import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.styles import inject_css
from utils.sheets import read_tab

st.set_page_config(
    page_title="Check My Status — Community Voices",
    page_icon="🔍",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Application Status</div>
  <h1>Check your application status</h1>
  <p>
    Enter the email address you applied with and the Confirmation ID you received
    after submitting. Your ID looks like <strong style="color:#fff;">CV-2026-XXXXXXXX</strong>.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Lookup form ────────────────────────────────────────────────────────────────
with st.form("status_lookup"):
    email_input = st.text_input("Email address", placeholder="ada@example.com")
    cid_input   = st.text_input("Confirmation ID", placeholder="CV-2026-A4F82E1B").strip().upper()
    submitted   = st.form_submit_button("Check Status", type="primary", use_container_width=True)

if not submitted:
    st.stop()

if not email_input or not cid_input:
    st.warning("Please enter both your email address and Confirmation ID.")
    st.stop()

# ── Lookup ─────────────────────────────────────────────────────────────────────
with st.spinner("Looking up your application..."):
    try:
        df = read_tab("Speaker_Applications")
    except Exception as e:
        st.error(f"Could not reach the database. Please try again in a moment. ({e})")
        st.stop()

if df.empty or "confirmation_id" not in df.columns:
    st.info("No applications found yet.")
    st.stop()

match = df[
    (df["confirmation_id"].str.strip().str.upper() == cid_input) &
    (df["email"].str.strip().str.lower() == email_input.strip().lower())
]

if match.empty:
    st.error("No application found with that email and Confirmation ID. Please double-check both and try again.")
    st.stop()

row = match.iloc[0]

# ── Status display ─────────────────────────────────────────────────────────────
status = row.get("status", "Pending")

STATUS_STYLES = {
    "Pending":    ("status-pending",    "⏳ Under Review"),
    "Approved":   ("status-approved",   "✅ Approved"),
    "Waitlisted": ("status-waitlisted", "📋 Waitlisted"),
    "Not a Fit":  ("status-not-a-fit",  "❌ Not a Fit"),
}
badge_class, badge_label = STATUS_STYLES.get(status, ("status-pending", status))

st.markdown(f"""
<div class="info-card" style="border-color: #29B5E8;">
  <div style="display:flex; align-items:center; gap:12px; margin-bottom: 16px;">
    <span class="status-badge {badge_class}">{badge_label}</span>
    <span style="font-size:0.85rem; color:#718096;">ID: <strong>{row.get('confirmation_id','')}</strong></span>
  </div>
  <h4 style="margin-bottom:4px;">{row.get('talk_title','Your Talk')}</h4>
  <p style="margin-bottom:2px;">
    <strong>{row.get('first_name','')} {row.get('last_name','')}</strong> &nbsp;·&nbsp;
    {row.get('event_name','')} &nbsp;·&nbsp; {row.get('event_city','')}, {row.get('event_country','')}
  </p>
  <p style="margin-top:6px; color:#718096; font-size:0.82rem;">
    Submitted: {row.get('submitted_at','')}
  </p>
</div>
""", unsafe_allow_html=True)

# ── Status-specific next steps ─────────────────────────────────────────────────
if status == "Approved":
    st.success("Your application has been approved! Check your email for next steps from the Community Voices team.")
    st.markdown("**While you wait for our email:**")
    st.page_link("pages/4_Feedback.py", label="Generate your talk feedback QR code", icon="📱")
    st.page_link("pages/5_Resources.py", label="Download your speaker resource kit", icon="📦")

elif status == "Pending":
    st.info("Your application is currently under review. We aim to respond within **5 business days**.", icon="⏳")
    st.markdown("In the meantime, you can prepare by visiting the **Speaker Resources** page.")
    st.page_link("pages/5_Resources.py", label="Speaker Resources", icon="📦")

elif status == "Waitlisted":
    st.warning("You're on the waitlist for this event. We'll reach out if a spot opens up.", icon="📋")

elif status == "Not a Fit":
    st.error(
        "Unfortunately your application wasn't a match for this cycle. "
        "This doesn't reflect on the quality of your work — availability and fit vary by event.",
        icon="❌",
    )
    st.markdown("You're welcome to apply for a future event.")
    st.page_link("pages/1_Apply.py", label="Apply for another event", icon="🎤")

# ── Admin notes (only show if non-empty) ─────────────────────────────────────
admin_notes = row.get("admin_notes", "")
if admin_notes and str(admin_notes).strip():
    st.info(f"**Note from the team:** {admin_notes}")
