import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
import streamlit as st
from utils.styles import inject_css
from utils.sheets import append_row
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Register Your Event — Community Voices",
    page_icon="🏟️",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Guard: already submitted ──────────────────────────────────────────────────
if st.session_state.get("event_submitted"):
    eid = st.session_state.get("event_id", "")
    st.markdown(f"""
    <div class="success-box">
      <h2>Event registered!</h2>
      <p>
        Your event and speaker request are under review.
        The Community Voices team will be in touch within 5 business days.
      </p>
    </div>
    <div class="id-box" style="margin-top: 24px;">
      <div class="label">Your Event Reference ID</div>
      <div class="id">{eid}</div>
    </div>
    """, unsafe_allow_html=True)
    st.info("Save this ID — you may be asked to reference it in follow-up communications.", icon="📋")
    if st.button("Register another event"):
        del st.session_state["event_submitted"]
        del st.session_state["event_id"]
        st.rerun()
    st.stop()

# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-hero" style="background: linear-gradient(135deg, #44337A 0%, #6B46C1 100%);">
  <div class="eyebrow">Event & Vendor Portal</div>
  <h1>Register your event</h1>
  <p>
    Organizing a conference, summit, meetup, or community day?
    Register your event and request a Snowflake community speaker.
    We'll review your event and suggest qualified speakers from our program.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Section 1: About You (Organizer) ──────────────────────────────────────────
st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">About You (Event Organizer)</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Tell us who you are and how to reach you.</div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    organizer_name  = st.text_input("Your full name *", placeholder="Jordan Smith")
with c2:
    organizer_email = st.text_input("Email address *", placeholder="jordan@event.org")

c3, c4 = st.columns(2)
with c3:
    organizer_org   = st.text_input("Organization / company *", placeholder="PyCon Foundation")
with c4:
    organizer_role  = st.text_input("Your role in the event", placeholder="Program Chair")

org_website = st.text_input("Organization website", placeholder="https://...")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 2: Event Details ───────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 2 of 4</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Event Details</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Tell us about your event.</div>', unsafe_allow_html=True)

event_name    = st.text_input("Event name *", placeholder="Data + AI Summit EMEA 2026")
event_website = st.text_input("Event website *", placeholder="https://...")

c5, c6 = st.columns(2)
with c5:
    event_start = st.date_input("Event start date *", min_value=date.today())
with c6:
    event_end   = st.date_input("Event end date", min_value=date.today())

c7, c8 = st.columns(2)
with c7:
    event_city    = st.text_input("City *", placeholder="Amsterdam")
with c8:
    event_country = st.text_input("Country *", placeholder="Netherlands")

event_format = st.selectbox(
    "Event format *",
    ["Select...", "In-person conference", "Hybrid conference", "Virtual conference",
     "Community meetup (in-person)", "Community meetup (virtual)", "University / academic",
     "Corporate / industry event", "Other"],
)

expected_audience = st.select_slider(
    "Expected total attendance",
    options=["< 50", "50–200", "200–500", "500–1,000", "1,000–5,000", "5,000+"],
    value="200–500",
)

community_alignment = st.multiselect(
    "Primary audience profile (select all that apply)",
    ["Data Engineers", "Analytics Engineers", "Data Scientists / ML Engineers",
     "Software / App Developers", "Data Analysts", "Data Leaders / Executives",
     "AI / GenAI Builders", "Open Source Community", "Academic / Student"],
)

event_description = st.text_area(
    "Describe your event in 2–4 sentences *",
    placeholder="PyData Amsterdam is a community conference for data practitioners and Python users...",
    height=100,
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 3: Speaker Request ────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 3 of 4</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Speaker Request</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">What kind of speaker are you looking for?</div>', unsafe_allow_html=True)

speaker_topic = st.text_area(
    "Describe the topic or talk you'd like a speaker for *",
    placeholder="We're looking for a speaker to talk about AI / LLM applications built on Snowflake — practical, real-world use cases rather than product demos...",
    height=100,
)

topic_tags = st.multiselect(
    "Topic tags",
    ["Data Engineering", "Snowpark / Python", "Cortex AI / LLMs", "Streamlit",
     "Data Sharing", "Cost Optimization", "ML / MLOps", "Iceberg", "Dynamic Tables",
     "Data Governance", "Real-Time / Streaming", "Other"],
)

c9, c10 = st.columns(2)
with c9:
    session_format = st.selectbox(
        "Session format",
        ["Select...", "Conference talk (30–45 min)", "Lightning talk (< 15 min)",
         "Workshop / hands-on lab", "Panel", "Keynote", "Demo / product showcase"],
    )
with c10:
    audience_level = st.selectbox(
        "Preferred technical level",
        ["No preference", "Beginner-friendly", "Intermediate", "Advanced"],
    )

cfp_link = st.text_input("CFP / speaker submission link (if applicable)", placeholder="https://...")
cfp_deadline = st.date_input("CFP deadline (if applicable)", min_value=date.today(), value=None)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 4: Additional Info ────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 4 of 4</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Anything else?</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Optional — any additional context for the Community Voices team.</div>', unsafe_allow_html=True)

how_heard = st.selectbox(
    "How did you hear about Community Voices?",
    ["Select...", "Snowflake website", "Social media", "Word of mouth / referral",
     "Previous Snowflake speaker at our event", "Snowflake team member", "Other"],
)

additional_notes = st.text_area(
    "Additional notes or requests",
    placeholder="We already have a confirmed speaker from Snowflake staff, but we're looking for a community practitioner to complement them...",
    height=90,
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Validation & Submit ────────────────────────────────────────────────────────
required_ok = all([
    organizer_name, organizer_email, organizer_org,
    event_name, event_website,
    event_city, event_country,
    event_format not in ("", "Select..."),
    event_description,
    speaker_topic,
])

if not required_ok:
    st.caption("Complete all required fields (marked *) to submit.")

submitted = st.button(
    "Register Event & Request Speaker",
    type="primary",
    use_container_width=True,
    disabled=not required_ok,
)

if submitted:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    eid = generate_confirmation_id().replace("CV-", "EV-")
    rid = generate_confirmation_id().replace("CV-", "SR-")

    # Write event row
    event_row = [
        eid, now, "Pending",
        organizer_name, organizer_email, organizer_org,
        organizer_role or "", org_website or "",
        event_name, event_website,
        str(event_start), str(event_end),
        event_city, event_country,
        event_format, expected_audience,
        ", ".join(community_alignment),
        event_description,
        how_heard if how_heard != "Select..." else "",
        additional_notes or "",
        "",   # admin_notes
    ]

    # Write speaker request row
    request_row = [
        rid, now, "Pending",
        eid,                        # linked event_id
        event_name,
        speaker_topic,
        ", ".join(topic_tags),
        session_format if session_format != "Select..." else "",
        audience_level,
        cfp_link or "",
        str(cfp_deadline) if cfp_deadline else "",
        "",   # matched_speaker
        "",   # admin_notes
    ]

    ok1 = append_row("Events", event_row)
    ok2 = append_row("Speaker_Requests", request_row)

    if ok1 and ok2:
        st.session_state["event_submitted"] = True
        st.session_state["event_id"] = eid
        st.rerun()
    else:
        st.error("There was an issue registering your event. Please try again or email community@snowflake.com.")
