import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime
import streamlit as st
import pandas as pd
from utils.styles import inject_css
from utils.sheets import read_tab

st.set_page_config(
    page_title="Homepage — Community Voices",
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
col_spk, col_vnd, col_admin, col_navan = st.columns(4, gap="medium")

with col_spk:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#EBF8FF,#BEE3F8);border:2px solid #29B5E8;
                border-radius:16px;padding:28px 22px;text-align:center;min-height:260px;">
      <div style="font-size:2rem;margin-bottom:10px;">🎤</div>
      <h3 style="color:#1A365D;font-size:1.2rem;margin-bottom:8px;">Speaker Portal</h3>
      <p style="color:#2D4A6B;font-size:0.88rem;">Browse speaking slots, book travel, explore upcoming events, access resources, and generate feedback QR codes.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Speaker_Portal.py", label="Speaker Portal →", icon="🎤")

with col_vnd:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#FAF5FF,#E9D8FD);border:2px solid #805AD5;
                border-radius:16px;padding:28px 22px;text-align:center;min-height:260px;">
      <div style="font-size:2rem;margin-bottom:10px;">🏟️</div>
      <h3 style="color:#44337A;font-size:1.2rem;margin-bottom:8px;">Vendor Portal</h3>
      <p style="color:#553C9A;font-size:0.88rem;">Register events, request speakers, bulk upload, track submissions.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_Vendor_Portal.py", label="Vendor Portal →", icon="🏟️")

with col_admin:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#EBF8FF,#E2F0FB);border:2px solid #0E2346;
                border-radius:16px;padding:28px 22px;text-align:center;min-height:260px;">
      <div style="font-size:2rem;margin-bottom:10px;">🔐</div>
      <h3 style="color:#0E2346;font-size:1.2rem;margin-bottom:8px;">Admin Portal</h3>
      <p style="color:#2D3748;font-size:0.88rem;">Manage applications, Q3 goals, speaker matching, comms, and bulk operations.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_Admin.py", label="Admin Portal →", icon="🔐")

with col_navan:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#F7FAFC,#EDF2F7);border:2px solid #4A5568;
                border-radius:16px;padding:28px 22px;text-align:center;min-height:260px;">
      <div style="font-size:2rem;margin-bottom:10px;">✈️</div>
      <h3 style="color:#1A202C;font-size:1.2rem;margin-bottom:8px;">Navan Travel Portal</h3>
      <p style="color:#4A5568;font-size:0.88rem;">Travel booking queue, speaker itineraries, Uber requests, batch export.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/4_Navan_Portal.py", label="Navan Portal →", icon="✈️")

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

# ── Past Events ────────────────────────────────────────────────────────────────
st.markdown("### Past events")
st.caption("Events that have already taken place under the Community Voices programme.")

@st.cache_data(ttl=600)
def load_home_past_events():
    try:
        return read_tab("Events")
    except Exception:
        return pd.DataFrame()

def _parse_home_date(d):
    d = str(d).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"):
        try:
            x = datetime.strptime(d, fmt)
            if x.year < 2000: x = x.replace(year=2026)
            return x
        except Exception:
            pass
    return None

df_home_all = load_home_past_events()
if df_home_all.empty:
    st.info("No past events on record yet.")
else:
    today_h = datetime.today()
    date_col_h = next((c for c in df_home_all.columns if "start" in c.lower() or "date" in c.lower()), None)
    if date_col_h:
        df_home_all["_parsed"] = df_home_all[date_col_h].apply(_parse_home_date)
        past_home = df_home_all[df_home_all["_parsed"].apply(lambda x: x is not None and x < today_h)].copy()
        past_home = past_home.sort_values("_parsed", ascending=False).reset_index(drop=True)
    else:
        past_home = df_home_all.copy()

    if past_home.empty:
        st.info("No past events on record yet.")
    else:
        disp_cols = [c for c in ["event_name","event_city","event_country","event_date_start","event_type","expected_audience"] if c in past_home.columns]
        if disp_cols:
            disp = past_home[disp_cols].copy()
            disp.columns = [c.replace("event_","").replace("_"," ").title() for c in disp_cols]
            st.dataframe(disp, use_container_width=True, hide_index=True)
        else:
            st.dataframe(past_home.drop(columns=["_parsed"], errors="ignore"), use_container_width=True, hide_index=True)
        st.caption(f"{len(past_home)} past event(s)")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── FAQ ───────────────────────────────────────────────────────────────────────
st.markdown("### Quick FAQ")
faqs = [
    ("Who can apply as a speaker?",
     "Snowflake Data Superheroes, Squad members, Streamlit Creators, and independent practitioners with a genuine Snowflake or data story to tell."),
    ("How long does the review take?",
     "We aim to respond within 5 business days. Speakers can track status using their Confirmation ID in the Speaker Portal."),
    ("What support does Snowflake provide?",
     "Travel grants (economy flights + hotel), Snowflake swag kit, speaker coaching session, and co-promotion on Snowflake social channels."),
    ("I'm organizing an event. What do I get?",
     "Access to our pool of vetted Snowflake community speakers. Once your event is approved, we handle speaker introductions and logistics support."),
    ("Can I upload events in bulk?",
     "Yes — the Vendor Portal supports bulk upload via CSV, Excel (.xlsx), or a Google Sheets URL."),
    ("How does the Navan travel booking work?",
     "Approved speakers with travel grants appear automatically in the Navan Travel Portal with pre-written trip request emails and a batch CSV export for your travel coordinator."),
]
for q, a in faqs:
    with st.expander(q):
        st.markdown(a)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)
st.markdown("""
<p style="text-align:center;font-size:0.82rem;color:#A0AEC0;">
  Snowflake Community Voices Program &nbsp;·&nbsp;
  Questions? <a href="mailto:community@snowflake.com" style="color:#29B5E8;">community@snowflake.com</a>
</p>
""", unsafe_allow_html=True)
