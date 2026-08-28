import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
import streamlit as st
from utils.styles import inject_css
from utils.sheets import append_row
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Apply as a Speaker — Community Voices",
    page_icon="🎤",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Guard: already submitted ──────────────────────────────────────────────────
if st.session_state.get("applied"):
    cid = st.session_state.get("confirmation_id", "")
    st.markdown(f"""
    <div class="success-box">
      <h2>Application submitted!</h2>
      <p>Your application is under review. Save your Confirmation ID below — you'll need it to check your status.</p>
    </div>
    <div class="id-box" style="margin-top: 24px;">
      <div class="label">Your Confirmation ID</div>
      <div class="id">{cid}</div>
    </div>
    """, unsafe_allow_html=True)
    st.info("Bookmark the **Check My Status** page and use your email + this ID to track your application.", icon="📋")
    if st.button("Submit another application"):
        del st.session_state["applied"]
        del st.session_state["confirmation_id"]
        st.rerun()
    st.stop()

# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Speaker Application</div>
  <h1>Apply to speak at your event</h1>
  <p>
    Tell us about yourself, your community identity, and the event you're speaking at.
    Applications take about 5 minutes. You'll get a Confirmation ID on submission.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Pre-fill from Events Board URL params ──────────────────────────────────────
_params = st.query_params
_prefill_event_id      = _params.get("event_id", "")
_prefill_event_name    = _params.get("event_name", "")
_prefill_event_city    = _params.get("event_city", "")
_prefill_event_country = _params.get("event_country", "")
_prefill_event_start   = _params.get("event_start", "")

if _prefill_event_name:
    st.success(
        f"Applying to speak at **{_prefill_event_name}** in {_prefill_event_city}, "
        f"{_prefill_event_country}. The event details are pre-filled below.",
        icon="📅",
    )

# ── Section 1: About You ───────────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 1 of 5</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">About You</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Basic contact information so we can reach you.</div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    first_name = st.text_input("First name *", placeholder="Ada")
with c2:
    last_name  = st.text_input("Last name *", placeholder="Lovelace")

c3, c4 = st.columns(2)
with c3:
    email      = st.text_input("Email address *", placeholder="ada@example.com")
with c4:
    job_title  = st.text_input("Job title *", placeholder="Senior Data Engineer")

c5, c6 = st.columns(2)
with c5:
    company    = st.text_input("Company / organization", placeholder="Acme Corp")
with c6:
    linkedin   = st.text_input("LinkedIn profile URL", placeholder="https://linkedin.com/in/...")

c7, c8 = st.columns(2)
with c7:
    country    = st.text_input("Country *", placeholder="United States")
with c8:
    city       = st.text_input("City", placeholder="San Francisco")

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 2: Community Identity ────────────────────────────────────────────
st.markdown('<div class="step-label">Section 2 of 5</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Your Snowflake Community Identity</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Tell us about your relationship with the Snowflake community.</div>', unsafe_allow_html=True)

community_identity = st.selectbox(
    "Community role *",
    ["Select...", "Data Superhero", "Snowflake Squad Member", "Streamlit Creator",
     "Open Source Contributor", "Independent Practitioner / Builder", "Other"],
)

years_snowflake = st.select_slider(
    "Years working with Snowflake",
    options=["< 1 year", "1 year", "2 years", "3 years", "4 years", "5+ years"],
    value="2 years",
)

bio = st.text_area(
    "Short bio (2–4 sentences) *",
    placeholder="I'm a data engineer at Acme with 4 years of Snowflake experience. I specialize in streaming pipelines and cost optimization...",
    height=100,
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 3: The Event ───────────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 3 of 5</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">The Event</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">Tell us about the event you\'re speaking at.</div>', unsafe_allow_html=True)

event_name    = st.text_input("Event name *", value=_prefill_event_name, placeholder="Data + AI Summit, PyData Global, ...")
event_website = st.text_input("Event website", placeholder="https://...")

c9, c10 = st.columns(2)
with c9:
    _start_val = date.today()
    if _prefill_event_start:
        try:
            from datetime import datetime as _dt
            _start_val = _dt.strptime(_prefill_event_start[:10], "%Y-%m-%d").date()
            if _start_val < date.today():
                _start_val = date.today()
        except Exception:
            pass
    event_date_start = st.date_input("Event start date *", value=_start_val, min_value=date.today())
with c10:
    event_date_end   = st.date_input("Event end date", min_value=date.today())

c11, c12 = st.columns(2)
with c11:
    event_city    = st.text_input("Event city *", value=_prefill_event_city, placeholder="Berlin")
with c12:
    event_country = st.text_input("Event country *", value=_prefill_event_country, placeholder="Germany")

event_type = st.selectbox(
    "Event type *",
    ["Select...", "In-person conference", "Hybrid conference", "Virtual conference",
     "Community meetup (in-person)", "Community meetup (virtual)", "University / academic talk",
     "Corporate / industry event", "Other"],
)

audience_size = st.select_slider(
    "Expected audience size",
    options=["< 50", "50–200", "200–500", "500–1,000", "1,000–5,000", "5,000+"],
    value="200–500",
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 4: Your Talk ───────────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 4 of 5</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Your Talk</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">What are you presenting? Be specific — this helps us match you with event organizers.</div>', unsafe_allow_html=True)

talk_title = st.text_input("Talk title *", placeholder="Building Real-Time Pipelines with Snowflake + Kafka")
talk_abstract = st.text_area(
    "Talk abstract (2–5 sentences) *",
    placeholder="In this talk, I'll walk through how we built a sub-second streaming pipeline using Snowpipe Streaming + Kafka...",
    height=120,
)

c13, c14 = st.columns(2)
with c13:
    session_type = st.selectbox(
        "Session format *",
        ["Select...", "Conference talk (30–45 min)", "Lightning talk (5–15 min)",
         "Workshop / hands-on lab", "Panel discussion", "Keynote", "Demo", "Podcast / interview"],
    )
with c14:
    audience_level = st.selectbox(
        "Technical level",
        ["Select...", "Beginner", "Intermediate", "Advanced", "Mixed audience"],
    )

snowflake_topics = st.multiselect(
    "Snowflake topics covered (select all that apply)",
    ["Data Engineering / Pipelines", "Snowpark / Python", "Cortex AI / LLMs",
     "Streamlit", "Data Sharing / Marketplace", "Cost Optimization", "Security & Governance",
     "ML / MLOps", "Iceberg / Open Formats", "Dynamic Tables", "Other"],
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Section 5: Support Request ────────────────────────────────────────────────
st.markdown('<div class="step-label">Section 5 of 5</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Support Request</div>', unsafe_allow_html=True)
st.markdown('<div class="section-hint">What kind of support are you requesting from Snowflake? Select everything that applies.</div>', unsafe_allow_html=True)

support_types = st.multiselect(
    "Support types *",
    ["Travel grant (flights)", "Hotel / accommodation", "Conference registration fee",
     "Snowflake swag kit", "Speaker coaching session", "Co-promotion on Snowflake channels",
     "Speaker certification badge", "No support needed — I just want to be listed in the program"],
)

traveling_from = st.text_input("Traveling from (city, country)", placeholder="London, UK")

est_cost = st.number_input(
    "Estimated travel cost (USD) — leave 0 if not requesting travel support",
    min_value=0,
    max_value=10000,
    step=50,
    value=0,
)

additional_notes = st.text_area(
    "Anything else you'd like us to know?",
    placeholder="I've spoken at 3 previous conferences, slides are at...",
    height=90,
)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ── Validation & Submit ────────────────────────────────────────────────────────
required_ok = all([
    first_name, last_name, email, job_title, country,
    community_identity not in ("", "Select..."),
    bio,
    event_name,
    event_city, event_country,
    event_type not in ("", "Select..."),
    talk_title, talk_abstract,
    session_type not in ("", "Select..."),
    support_types,
])

if not required_ok:
    st.caption("Complete all required fields (marked *) to submit.")

submitted = st.button(
    "Submit Application",
    type="primary",
    use_container_width=True,
    disabled=not required_ok,
)

if submitted:
    cid = generate_confirmation_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        cid,                                          # confirmation_id
        now,                                          # submitted_at
        "Pending",                                    # status
        first_name, last_name, email,
        job_title, company or "", linkedin or "",
        country, city or "",
        community_identity, years_snowflake, bio,
        event_name, event_website or "",
        str(event_date_start), str(event_date_end),
        event_city, event_country,
        event_type, audience_size,
        talk_title, talk_abstract,
        session_type, audience_level if audience_level != "Select..." else "",
        ", ".join(snowflake_topics),
        ", ".join(support_types),
        traveling_from or "",
        str(est_cost),
        additional_notes or "",
        "",   # admin_notes (blank on submit)
        _prefill_event_id,   # matched_event — pre-linked if coming from Events Board
    ]
    ok = append_row("Speaker_Applications", row)
    if ok:
        st.session_state["applied"] = True
        st.session_state["confirmation_id"] = cid
        st.rerun()
    else:
        st.error("There was an issue submitting your application. Please try again or email community@snowflake.com.")
