import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import streamlit as st
from utils.styles import inject_css

st.set_page_config(
    page_title="Snowflake Community Voices",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Snowflake Community Program</div>
  <h1>Community Voices</h1>
  <p>
    We amplify the voices of real practitioners — Data Superheroes, Streamlit Creators,
    Squad members, and independent builders — at events around the world.
    Choose your portal below to get started.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Three portals ──────────────────────────────────────────────────────────────
col_spk, col_vnd, col_admin = st.columns(3, gap="large")

with col_spk:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#EBF8FF,#BEE3F8);border:2px solid #29B5E8;
                border-radius:16px;padding:32px 28px;text-align:center;min-height:280px;">
      <div style="font-size:2.5rem;margin-bottom:12px;">🎤</div>
      <h3 style="color:#1A365D;font-size:1.4rem;margin-bottom:10px;">Speaker Portal</h3>
      <p style="color:#2D4A6B;font-size:0.92rem;margin-bottom:20px;">
        Browse open speaking slots, submit an application, check your status,
        access the speaker resource kit, and generate talk feedback QR codes.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Speaker_Portal.py", label="Enter Speaker Portal →", icon="🎤")

with col_vnd:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#FAF5FF,#E9D8FD);border:2px solid #805AD5;
                border-radius:16px;padding:32px 28px;text-align:center;min-height:280px;">
      <div style="font-size:2.5rem;margin-bottom:12px;">🏟️</div>
      <h3 style="color:#44337A;font-size:1.4rem;margin-bottom:10px;">Vendor Portal</h3>
      <p style="color:#553C9A;font-size:0.92rem;margin-bottom:20px;">
        Register your event and request a Snowflake community speaker.
        Upload multiple events at once via CSV, Excel, or Google Sheets.
        Track the status of your submissions.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_Vendor_Portal.py", label="Enter Vendor Portal →", icon="🏟️")

with col_admin:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#EBF8FF,#E2F0FB);border:2px solid #0E2346;
                border-radius:16px;padding:32px 28px;text-align:center;min-height:280px;">
      <div style="font-size:2.5rem;margin-bottom:12px;">🔐</div>
      <h3 style="color:#0E2346;font-size:1.4rem;margin-bottom:10px;">Admin Portal</h3>
      <p style="color:#2D3748;font-size:0.92rem;margin-bottom:20px;">
        Manage applications, approve speakers, handle Navan travel requests,
        track Q3 goals, match speakers to events, and generate email communications.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_Admin.py", label="Enter Admin Portal →", icon="🔐")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Program stats ─────────────────────────────────────────────────────────────
st.markdown("### Program impact")
s1,s2,s3,s4=st.columns(4, gap="medium")
with s1:
    st.markdown('<div class="stat-card"><div class="num">25+</div><div class="label">Speakers Supported</div></div>', unsafe_allow_html=True)
with s2:
    st.markdown('<div class="stat-card"><div class="num">20+</div><div class="label">Events Globally</div></div>', unsafe_allow_html=True)
with s3:
    st.markdown('<div class="stat-card"><div class="num">4.2/5</div><div class="label">Avg Talk Rating</div></div>', unsafe_allow_html=True)
with s4:
    st.markdown('<div class="stat-card"><div class="num">15+</div><div class="label">Countries Reached</div></div>', unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── FAQ ───────────────────────────────────────────────────────────────────────
st.markdown("### Quick FAQ")
c_l, c_r = st.columns(2, gap="large")
with c_l:
    with st.expander("Who can apply as a speaker?"):
        st.markdown("Snowflake Data Superheroes, Squad members, Streamlit Creators, and independent practitioners with a genuine Snowflake or data story to tell.")
    with st.expander("How long does the review take?"):
        st.markdown("We aim to respond within 5 business days. Speakers can track status using their Confirmation ID in the Speaker Portal.")
    with st.expander("What support does Snowflake provide?"):
        st.markdown("Travel grants (economy flights + hotel), Snowflake swag kit, speaker coaching session, and co-promotion on Snowflake social channels.")
with c_r:
    with st.expander("I'm organizing an event. What do I get?"):
        st.markdown("Access to our pool of vetted Snowflake community speakers. Once your event is approved, we handle speaker introductions and logistics support.")
    with st.expander("Can I upload events in bulk?"):
        st.markdown("Yes — the Vendor Portal supports bulk upload via CSV, Excel (.xlsx), or a Google Sheets URL.")
    with st.expander("How does the Navan travel booking work?"):
        st.markdown("Approved speakers with travel grants appear automatically in the Admin Portal's Navan tab with pre-written trip request emails for your travel coordinator.")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)
st.markdown("""
<p style="text-align:center;font-size:0.82rem;color:#A0AEC0;">
  Snowflake Community Voices Program &nbsp;·&nbsp;
  Questions? <a href="mailto:community@snowflake.com" style="color:#29B5E8;">community@snowflake.com</a>
</p>
""", unsafe_allow_html=True)
