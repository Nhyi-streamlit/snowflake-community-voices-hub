import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.styles import inject_css

st.set_page_config(
    page_title="Speaker Resources — Community Voices",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Speaker Resource Hub</div>
  <h1>Everything you need to present with confidence</h1>
  <p>
    Brand assets, templates, and guides to help approved Community Voices speakers
    represent Snowflake authentically on stage.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Sections ───────────────────────────────────────────────────────────────────
tab_brand, tab_talk, tab_prep, tab_faq = st.tabs([
    "Brand Kit", "Talk Templates", "Speaker Prep", "Program FAQ"
])

# ── Brand Kit ─────────────────────────────────────────────────────────────────
with tab_brand:
    st.markdown("### Snowflake Brand Assets")
    st.markdown(
        "Use official Snowflake assets on your slides. "
        "Do not modify the logo or use unapproved color combinations."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="info-card">
          <h4>Logo Files</h4>
          <p>
            <a href="https://www.snowflake.com/wp-content/themes/snowflake/assets/img/brand-guidelines/snowflake-logo-blue.png"
               target="_blank" style="color:#29B5E8;">Snowflake logo (blue, PNG)</a><br>
            <a href="https://www.snowflake.com/wp-content/themes/snowflake/assets/img/brand-guidelines/snowflake-logo-white.png"
               target="_blank" style="color:#29B5E8;">Snowflake logo (white, PNG)</a><br>
            <small style="color:#718096;">For social media use the square logo format.</small>
          </p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="info-card">
          <h4>Brand Colors</h4>
          <p>
            <strong>Snowflake Blue:</strong> <code>#29B5E8</code><br>
            <strong>Snowflake Dark Navy:</strong> <code>#0E2346</code><br>
            <strong>White:</strong> <code>#FFFFFF</code><br>
            <strong>Light Blue:</strong> <code>#A8D8F0</code><br>
            <small style="color:#718096;">Avoid off-brand gradients and color edits.</small>
          </p>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown("""
        <div class="info-card">
          <h4>Fonts</h4>
          <p>
            <strong>Primary:</strong> Inter (Google Fonts)<br>
            <strong>Fallback:</strong> Helvetica Neue, Arial<br>
            <a href="https://fonts.google.com/specimen/Inter" target="_blank"
               style="color:#29B5E8;">Download Inter →</a><br>
            <small style="color:#718096;">Use medium/semibold weights for headings.</small>
          </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Social Media")
    st.markdown("""
    When you post about your talk, tag **@Snowflake** and use:
    - `#SnowflakeCommunity` — for all community talks
    - `#DataSuperhero` — if you're a Superhero
    - `#StreamlitCreator` — if you're a Streamlit Creator
    - The event's official hashtag

    If your talk is approved, the Community Voices team may amplify your post on
    Snowflake's official social channels.
    """)

# ── Talk Templates ────────────────────────────────────────────────────────────
with tab_talk:
    st.markdown("### Slide Templates")
    st.markdown(
        "Start with our approved slide template. Add your content — don't change the first "
        "and last slides (Snowflake branding requirements)."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
        <div class="info-card">
          <h4>Standard Conference Template</h4>
          <p>
            16:9 dark theme. Includes title slide, about me, agenda, content slides,
            key takeaways, and closing slide with QR code placeholder.<br><br>
            <a href="https://docs.google.com/presentation/d/1Vc2H4tF0Ox9v7vK8Gm2K3E4rN1wqjYpLDskBH7mNUs/edit?usp=sharing"
               target="_blank" style="color:#29B5E8;">Open template in Google Slides →</a>
          </p>
        </div>
        """, unsafe_allow_html=True)

    with col_b:
        st.markdown("""
        <div class="info-card">
          <h4>Lightning Talk Template (15 min)</h4>
          <p>
            Condensed version — 8 slides max. Designed for fast-paced conference sessions
            and meetup lightning rounds.<br><br>
            <a href="https://docs.google.com/presentation/d/1Vc2H4tF0Ox9v7vK8Gm2K3E4rN1wqjYpLDskBH7mNUs/edit?usp=sharing"
               target="_blank" style="color:#29B5E8;">Open template in Google Slides →</a>
          </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Bio & Headshot Guidelines")
    st.info(
        "When event organizers request a bio and photo, use these guidelines to maintain "
        "consistency across Snowflake community speakers.",
        icon="📝",
    )

    st.markdown("""
    **Bio format (50–100 words recommended):**

    > *[Name] is a [title] at [company] with [X] years of experience in [area].
    > They specialize in [skill 1, skill 2], and have built [notable project/outcome].
    > [Name] is a Snowflake [Data Superhero / Streamlit Creator / Squad member]
    > and has spoken at [event examples if applicable].
    > Find them on LinkedIn at [URL].*

    **Headshot requirements:**
    - High resolution (minimum 800×800 px)
    - Square format preferred
    - Clear background (white, light gray, or professional setting)
    - Professional but approachable — this is a tech community, not a corporate directory
    """)

# ── Speaker Prep ──────────────────────────────────────────────────────────────
with tab_prep:
    st.markdown("### Pre-talk checklist")

    checks = [
        ("6–8 weeks before", [
            "Submit your Community Voices application (if not yet approved)",
            "Confirm with event organizers: session length, A/V setup, slide deadline",
            "Register for the event (the program may cover your ticket)",
        ]),
        ("3–4 weeks before", [
            "Draft your slide deck using the Snowflake template",
            "Run a practice run — aim for a full rehearsal end-to-end",
            "Submit bio and headshot to event organizers",
            "Generate your feedback QR code (Feedback page)",
        ]),
        ("1 week before", [
            "Final slide review — proofread, check all links and demos",
            "Test your demos on the same machine you'll use on stage",
            "Prepare a backup plan if demos fail (screenshots, pre-recorded video)",
            "Set up travel if in-person (confirm hotel, flights, arrival time)",
        ]),
        ("Day of the talk", [
            "Arrive 30 min early — test A/V, clicker, display resolution",
            "Have your QR code on the last slide",
            "Stay for Q&A — community conversations start there",
        ]),
        ("After the talk", [
            "Share your slides publicly (SlideShare, GitHub, or LinkedIn post)",
            "Post on social media — tag @Snowflake and use #SnowflakeCommunity",
            "Review your feedback scores on the Admin/Status page",
        ]),
    ]

    for phase, items in checks:
        with st.expander(phase):
            for item in items:
                st.markdown(f"☐ {item}")

    st.markdown("### Speaker coaching")
    st.markdown("""
    Approved Community Voices speakers can request a **1:1 speaker coaching session** with
    the Community Voices team. Sessions cover:

    - Talk structure and storytelling
    - Demo best practices
    - Handling Q&A
    - Stage presence and pacing

    Email **community@snowflake.com** with subject line:
    *"Speaker coaching request — [Your Name] — [Event Name]"*
    """)

# ── FAQ ───────────────────────────────────────────────────────────────────────
with tab_faq:
    st.markdown("### Program FAQ")

    faqs = [
        ("When will I hear back after applying?",
         "We review applications on a rolling basis and aim to respond within **5 business days**. "
         "Check your status on the Status page using your Confirmation ID."),
        ("My application was approved. What happens next?",
         "You'll receive an email from the Community Voices team with next steps: "
         "travel booking instructions (if applicable), swag shipping info, and optional "
         "coaching scheduling."),
        ("Can I reuse Snowflake logos in my slides?",
         "Yes — use the logos from the Brand Kit tab. Don't modify the logo (no color changes, "
         "distortion, or adding effects). Include a small 'Snowflake Data Superhero / "
         "Community Speaker' credit on your first or last slide."),
        ("Who pays for travel?",
         "If your application is approved for a travel grant, Snowflake covers economy flights "
         "and hotel up to the approved amount. You submit receipts after the event. "
         "Speak to the Community Voices team for specifics."),
        ("Can I demo proprietary Snowflake features that are in private preview?",
         "Only if you've been explicitly cleared to do so by your Snowflake contact. "
         "When in doubt, demo GA features only."),
        ("Do I need Snowflake's approval for my slide content?",
         "We don't pre-approve slide content, but we ask you to follow brand guidelines "
         "and not make claims about roadmap or pricing. If you're unsure about something, "
         "email us before the event."),
        ("I'm not a Data Superhero or Streamlit Creator. Can I still apply?",
         "Yes. We accept applications from any community practitioner with a genuine "
         "Snowflake or data story to tell. Being a named program member helps, "
         "but it's not a hard requirement."),
    ]

    for q, a in faqs:
        with st.expander(q):
            st.markdown(a)

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    st.markdown("""
    **Still have questions?** Email [community@snowflake.com](mailto:community@snowflake.com)
    with the subject line *"Community Voices — [question topic]"*.
    """)
