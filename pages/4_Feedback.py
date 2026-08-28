import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from io import BytesIO
import streamlit as st
from utils.styles import inject_css
from utils.sheets import append_row
import uuid

st.set_page_config(
    page_title="Talk Feedback — Community Voices",
    page_icon="⭐",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Read URL parameters ────────────────────────────────────────────────────────
params      = st.query_params
speaker     = params.get("speaker", "")
event_param = params.get("event", "")
talk        = params.get("talk", "")

AUDIENCE_MODE = bool(speaker and event_param and talk)

# ══════════════════════════════════════════════════════════════════════════════
# AUDIENCE MODE — rate this talk
# ══════════════════════════════════════════════════════════════════════════════
if AUDIENCE_MODE:
    st.markdown(f"""
    <div class="page-hero">
      <div class="eyebrow">Rate this Talk</div>
      <h1>{talk}</h1>
      <p class="talk-meta">
        <strong style="color:#fff;">{speaker}</strong> &nbsp;·&nbsp; {event_param}
      </p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.get("feedback_submitted"):
        st.markdown("""
        <div class="success-box">
          <h2>Thank you!</h2>
          <p>Your feedback helps our community speakers improve and grow. It means a lot.</p>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    st.markdown('<div class="step-label">Talk Rating</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">How was the talk?</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-hint">Your feedback is anonymous and goes directly to the speaker.</div>', unsafe_allow_html=True)

    rating_overall   = st.slider("Overall rating", 1, 5, 4, format="%d ⭐")
    rating_content   = st.slider("Content quality (depth, accuracy, relevance)", 1, 5, 4, format="%d ⭐")
    rating_delivery  = st.slider("Delivery (clarity, pacing, engagement)", 1, 5, 4, format="%d ⭐")
    rating_relevance = st.slider("Relevance to your work / projects", 1, 5, 4, format="%d ⭐")

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    most_valuable = st.text_area(
        "What was the most valuable thing you took away?",
        placeholder="The demo showing how to chain Cortex functions with dynamic tables was eye-opening...",
        height=90,
    )

    would_attend = st.radio(
        "Would you attend another talk by this speaker?",
        ["Definitely yes", "Probably yes", "Not sure", "Probably not"],
        horizontal=True,
    )

    community_interest = st.selectbox(
        "Are you interested in getting more involved in the Snowflake community?",
        ["Select...", "Yes — tell me about Data Superheroes", "Yes — I'd like to speak at events too",
         "Maybe — I want to learn more first", "No thanks"],
    )

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    st.markdown('<div class="section-title">About you (optional)</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        respondent_name  = st.text_input("Your name (optional)")
    with c2:
        respondent_email = st.text_input("Your email (optional)")

    other_feedback = st.text_area("Any other feedback for the speaker?", height=80)

    if st.button("Submit Feedback", type="primary", use_container_width=True):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            str(uuid.uuid4())[:8].upper(),  # submission_id
            now,                             # submitted_at
            speaker,                         # speaker_name
            event_param,                     # event_name
            talk,                            # talk_title
            "",                              # talk_date
            str(rating_overall),
            str(rating_content),
            str(rating_delivery),
            str(rating_relevance),
            most_valuable or "",
            would_attend,
            community_interest if community_interest != "Select..." else "",
            "",                              # interested_areas
            respondent_name or "",
            respondent_email or "",
            other_feedback or "",
        ]
        ok = append_row("Talk_Feedback", row)
        if ok:
            st.session_state["feedback_submitted"] = True
            st.rerun()
        else:
            st.error("There was a problem submitting your feedback. Please try again.")

    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SPEAKER MODE — generate QR code
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Speaker Tool</div>
  <h1>Generate your feedback QR code</h1>
  <p>
    Fill in your name, event, and talk title below.
    We'll generate a QR code your audience can scan to rate your talk.
    Display it on your last slide or share the link in the chat.
  </p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="step-label">Your Talk Details</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Who are you and what are you presenting?</div>', unsafe_allow_html=True)

spk_name  = st.text_input("Your full name *", placeholder="Ada Lovelace")
spk_event = st.text_input("Event name *", placeholder="PyData Global 2026")
spk_talk  = st.text_input("Talk title *", placeholder="Building Real-Time Pipelines with Snowflake")

generate_btn = st.button(
    "Generate QR Code",
    type="primary",
    disabled=not (spk_name and spk_event and spk_talk),
)

if generate_btn:
    try:
        import qrcode
        from PIL import Image

        app_base = ""
        try:
            app_base = st.secrets.get("APP_BASE_URL", "")
        except Exception:
            app_base = os.environ.get("APP_BASE_URL", "")

        if not app_base:
            app_base = "https://your-app-name.streamlit.app"

        import urllib.parse
        feedback_url = (
            f"{app_base.rstrip('/')}/Feedback"
            f"?speaker={urllib.parse.quote(spk_name)}"
            f"&event={urllib.parse.quote(spk_event)}"
            f"&talk={urllib.parse.quote(spk_talk)}"
        )

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(feedback_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0E2346", back_color="white")

        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        c_img, c_info = st.columns([1, 1], gap="large")

        with c_img:
            st.image(buf, caption="Audience scans this to rate your talk", use_container_width=True)
            st.download_button(
                "Download QR Code PNG",
                data=buf.getvalue(),
                file_name=f"feedback-qr-{spk_name.replace(' ','-').lower()}.png",
                mime="image/png",
                use_container_width=True,
            )

        with c_info:
            st.markdown(f"""
            <div class="info-card">
              <h4>Shareable link</h4>
              <p style="word-break:break-all; font-size:0.82rem; font-family:monospace;">{feedback_url}</p>
            </div>
            <div class="info-card">
              <h4>How to use</h4>
              <p>
                1. Download the QR code PNG above.<br>
                2. Add it to your last slide ("Rate my talk!").<br>
                3. Or paste the link in the event chat.<br>
                4. Audience scans and submits a 30-second rating.<br>
                5. You can review your feedback in the Admin portal.
              </p>
            </div>
            """, unsafe_allow_html=True)

    except ImportError:
        st.error("QR code library not installed. Run: `pip install qrcode[pil] Pillow`")
    except Exception as e:
        st.error(f"Error generating QR code: {e}")
