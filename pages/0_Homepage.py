"""Public homepage: who Community Voices is for, two clear starting points, and what's coming up."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from utils import public_events
from utils import ui_components as ui
from utils.styles import inject_css
from workflow.ui import md

st.set_page_config(page_title="Community Voices — Snowflake", page_icon="❄️", layout="wide")
inject_css()

ui.hero("Snowflake Community Program",
        "Share what you've built. Bring great speakers to your event.",
        "Community Voices connects Snowflake practitioners (Data Superheroes, Streamlit Creators, "
        "and independent builders) with conferences, meetups, and universities around the world.")

ui.cta_row([
    {"page": "pages/1_Speaker_Portal.py", "icon": ":material/mic:", "label": "I'm a speaker",
     "caption": "Find events, get your talk ready with our brand kit and templates, and collect audience feedback.",
     "button": "Go to the Speaker Portal"},
    {"page": "pages/2_Vendor_Portal.py", "icon": ":material/storefront:", "label": "I'm organizing an event",
     "caption": "Register your conference or meetup and we'll match you with a Snowflake community speaker.",
     "button": "Go to the Vendor Portal"},
])

st.header("How it works", divider="blue")
left, right = st.columns(2, gap="large")
with left:
    st.subheader(":material/mic: For speakers")
    ui.step_cards([("Pick an event", "Browse approved events looking for community speakers."),
                   ("Prepare", "Use the brand kit, talk templates, and prep checklist."),
                   ("Speak & share", "Show your feedback QR code and hear what landed.")])
with right:
    st.subheader(":material/storefront: For organizers")
    ui.step_cards([("Sign in", "Enter your email and we'll send you a code. No account needed."),
                   ("Register", "Tell us about your event in about 5 minutes."),
                   ("Get matched", "We review within 5 business days and introduce a speaker.")])

st.header("Coming up in the community", divider="blue")
events = public_events.upcoming(limit=6)
if events is None:
    st.info("We couldn't load upcoming events right now. Please check back soon.", icon=":material/cloud_off:")
elif events.empty:
    st.info("New events are on the way. Check back soon, or register yours in the Vendor Portal.",
            icon=":material/event_upcoming:")
else:
    with st.container(horizontal=True, gap="medium"):
        for _, ev in events.iterrows():
            with st.container(border=True, width=300):
                st.markdown(f"**{md(ev.get('event_name'))}**")
                where = ", ".join(str(x) for x in (ev.get("event_city"), ev.get("event_country")) if x)
                st.caption(f":material/calendar_today: {ev['start']:%b %d, %Y}"
                           + (f"  ·  :material/location_on: {md(where)}" if where else ""))
                if ev.get("event_format"):
                    st.badge(str(ev["event_format"]), color="blue")

st.header("Questions", divider="blue")
ui.faq([
    ("Who can speak?", "Snowflake Data Superheroes, Squad members, Streamlit Creators, and practitioners with a "
                       "real Snowflake or data story to tell."),
    ("What does it cost organizers?", "Nothing. We connect you with vetted community speakers at no charge."),
    ("How long does review take?", "We review new events within 5 business days."),
    ("Do I need an account?", "No. Organizers sign in with a code sent to their email."),
])
ui.help_link("speakers", "Full instructions for speakers")
ui.help_link("organizers", "Full instructions for event organizers")
st.caption(f"Questions? Email [{ui.CONTACT_EMAIL}](mailto:{ui.CONTACT_EMAIL}).")
