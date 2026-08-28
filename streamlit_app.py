import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
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
    Whether you want to share your expertise on stage or bring Snowflake expertise to your event,
    you're in the right place.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Primary CTAs ───────────────────────────────────────────────────────────────
col_spk, col_vnd, col_board = st.columns(3, gap="large")

with col_spk:
    st.markdown("""
    <div class="info-card" style="border: 2px solid #29B5E8; background: linear-gradient(135deg, #EBF8FF, #F0F9FF);">
      <h4 style="font-size: 1.25rem; color: #1A365D;">🎤 I want to speak</h4>
      <p style="font-size: 0.95rem; color: #2D3748; margin-bottom: 0;">
        Are you speaking at a third-party conference, meetup, or community event and want
        Snowflake's backing? Apply for a travel grant, swag, and program support.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Apply.py", label="Apply as a Speaker", icon="➡️")

with col_vnd:
    st.markdown("""
    <div class="info-card" style="border: 2px solid #805AD5; background: linear-gradient(135deg, #FAF5FF, #F0EFF8);">
      <h4 style="font-size: 1.25rem; color: #44337A;">🏟️ I'm hosting an event</h4>
      <p style="font-size: 0.95rem; color: #2D3748; margin-bottom: 0;">
        Organising a conference, summit, or community day? Register your event and request
        a Snowflake community speaker through the program.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_Events.py", label="Register Your Event", icon="➡️")

with col_board:
    st.markdown("""
    <div class="info-card" style="border: 2px solid #38A169; background: linear-gradient(135deg, #F0FFF4, #E6FFFA);">
      <h4 style="font-size: 1.25rem; color: #276749;">📅 Browse open events</h4>
      <p style="font-size: 0.95rem; color: #2D3748; margin-bottom: 0;">
        See all events actively looking for Snowflake community speakers —
        browse, filter, and apply directly from the board.
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/7_Browse_Events.py", label="Browse Open Events", icon="➡️")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── How it works ──────────────────────────────────────────────────────────────
st.markdown("### How it works")
c1, c2, c3 = st.columns(3, gap="large")

with c1:
    st.markdown("""
    <div class="info-card">
      <div class="step-label">Step 1</div>
      <h4>Apply or Register</h4>
      <p>
        Speakers submit a short application. Event organizers register their event and
        describe the speaker they need. Takes about 5 minutes.
      </p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="info-card">
      <div class="step-label">Step 2</div>
      <h4>Review & Match</h4>
      <p>
        The Community Voices team reviews every submission within 5 business days.
        Approved speakers are matched with relevant events, and vendors are matched
        with qualified speakers.
      </p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="info-card">
      <div class="step-label">Step 3</div>
      <h4>Show Up & Shine</h4>
      <p>
        Approved speakers get Snowflake swag, travel support, and coaching. After your
        talk, collect audience feedback with a QR code we generate for you.
      </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Program stats ─────────────────────────────────────────────────────────────
st.markdown("### Program impact")
s1, s2, s3, s4 = st.columns(4, gap="medium")

with s1:
    st.markdown("""
    <div class="stat-card">
      <div class="num">25+</div>
      <div class="label">Speakers Supported</div>
    </div>
    """, unsafe_allow_html=True)
with s2:
    st.markdown("""
    <div class="stat-card">
      <div class="num">20+</div>
      <div class="label">Events Globally</div>
    </div>
    """, unsafe_allow_html=True)
with s3:
    st.markdown("""
    <div class="stat-card">
      <div class="num">4.2/5</div>
      <div class="label">Avg Talk Rating</div>
    </div>
    """, unsafe_allow_html=True)
with s4:
    st.markdown("""
    <div class="stat-card">
      <div class="num">15+</div>
      <div class="label">Countries Reached</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Who qualifies ─────────────────────────────────────────────────────────────
st.markdown("### Who can apply?")
q1, q2 = st.columns(2, gap="large")

with q1:
    st.markdown("""
    <div class="info-card">
      <h4>Community Members</h4>
      <p>
        ✅ Snowflake Data Superheroes<br>
        ✅ Snowflake Squads members<br>
        ✅ Streamlit Creators<br>
        ✅ Independent builders & practitioners<br>
        ✅ Open source contributors working with Snowflake
      </p>
    </div>
    """, unsafe_allow_html=True)

with q2:
    st.markdown("""
    <div class="info-card">
      <h4>What we support</h4>
      <p>
        ✅ Third-party conferences (not Snowflake-run events)<br>
        ✅ Community meetups & local user groups<br>
        ✅ University / academic talks<br>
        ✅ Online summits with significant audience<br>
        ✅ Events with a clear data / AI / developer angle
      </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── FAQ ───────────────────────────────────────────────────────────────────────
st.markdown("### Frequently asked questions")

faqs = [
    ("How long does the review take?",
     "We aim to respond within 5 business days of your submission. You'll receive your "
     "Confirmation ID immediately — use it on the Status page to check your application."),
    ("What support can I receive?",
     "Approved speakers may receive: travel grant (economy flights + hotel), Snowflake swag kit, "
     "1:1 speaker coaching session, co-promotion on Snowflake social channels, and a Snowflake "
     "speaker certification badge."),
    ("Can I apply for an event that already happened?",
     "No — applications must be submitted before the event date. We can't retroactively fund travel."),
    ("I'm an event organizer. What do I get?",
     "Registering your event gives you access to our pool of vetted Snowflake community speakers. "
     "Once approved, the Community Voices team will suggest matches and handle introductions."),
    ("How do I check my application status?",
     "Visit the Status page and enter your email address plus the Confirmation ID you received "
     "when you submitted your application."),
    ("Can I apply for multiple events?",
     "Yes — submit a separate application for each event. Each gets its own Confirmation ID."),
]

for q, a in faqs:
    with st.expander(q):
        st.markdown(a)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("<hr class='divider'>", unsafe_allow_html=True)
st.markdown("""
<p style="text-align:center; font-size: 0.82rem; color: #A0AEC0;">
  Snowflake Community Voices Program &nbsp;·&nbsp; Questions? Contact
  <a href="mailto:community@snowflake.com" style="color: #29B5E8;">community@snowflake.com</a>
</p>
""", unsafe_allow_html=True)
