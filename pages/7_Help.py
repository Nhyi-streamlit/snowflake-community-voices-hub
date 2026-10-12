"""Help & instructions: the single place for how-to and FAQ text (public, no sign-in)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import streamlit as st

from utils import ui_components as ui
from utils import vendor_validation as vv
from utils.styles import inject_css
from utils.email_otp import CODE_TTL

st.set_page_config(page_title="Help & instructions — Community Voices", page_icon="❄️", layout="centered")
inject_css()

ui.hero("Help & instructions", "How can we help?",
        "Everything speakers and event organizers need: signing in, registering events, travel, and contacts.")

TOPICS = ui.HELP_TOPICS


def _sync():
    st.query_params["topic"] = st.session_state["help_topic"]


if "help_topic" not in st.session_state:
    q = st.query_params.get("topic", "speakers")
    st.session_state["help_topic"] = q if q in TOPICS else "speakers"
topic = st.radio("Topic", list(TOPICS), format_func=TOPICS.get, key="help_topic", on_change=_sync,
                 horizontal=True, label_visibility="collapsed")
st.divider()

if topic == "speakers":
    st.header(":material/mic: Speakers")
    st.markdown("1. **Find an event.** Open the Speaker Portal → *Speak at an event* to see approved upcoming events.\n"
                "2. **Get ready.** *Resources* has the brand kit, talk templates, and a prep checklist.\n"
                "3. **After your talk.** Generate a feedback QR code for your last slide, then log attendance "
                "from your event photos.")
    ui.page_link("pages/1_Speaker_Portal.py", "Open the Speaker Portal", ":material/arrow_forward:")
    ui.faq([
        ("Who can speak?", "Snowflake Data Superheroes, Squad members, Streamlit Creators, and independent "
                           "practitioners with a real Snowflake or data story to tell."),
        ("Do I need to sign in?", "Only for things tied to you, like reimbursements and attendance counts. Browsing "
                                  "events and resources is open to everyone."),
        ("How does the feedback QR code work?", "Enter your name, the event, and your talk title under *After your "
                                                "talk*. Put the QR code on your last slide. Attendees scan it and "
                                                "rate your talk in about 30 seconds, with no sign-in."),
        ("Do I need approval for slide content?", "No pre-approval is needed. Follow the brand guidelines and don't "
                                                  "discuss roadmap or pricing."),
        ("How do I get slide templates?", "Email the program team with the subject *Slide template request — "
                                          "your name* and we'll share them."),
        ("How does the headcount tool work?", "Upload wide shots of the room. People are counted inside the app, "
                                              "photos are not stored, and you can correct any count before saving."),
    ])

elif topic == "organizers":
    st.header(":material/storefront: Event organizers")
    st.markdown("1. **Sign in** with your email in the Vendor Portal (see *Signing in*).\n"
                "2. **Register an event**: four short steps; your answers are kept if you go back. Review, then "
                "**Submit** to get a reference ID.\n"
                "3. **Track it** under **My events**. You can edit while it's *Pending*.\n"
                "4. **Many events?** Use **Bulk upload** with the template (see *Bulk upload template*).")
    ui.page_link("pages/2_Vendor_Portal.py", "Open the Vendor Portal", ":material/arrow_forward:")
    ui.faq([
        ("Who can register an event?", "Conference organizers, meetup hosts, universities, and partners running "
                                       "events where a Snowflake community speaker would be a good fit."),
        ("What happens after I submit?", "You get a reference ID right away. We review every event within 5 business "
                                         "days. Approved events are listed for qualified community speakers, and "
                                         "we'll email you when a speaker is matched."),
        ("Can I change my submission?", "Yes. While it's *Pending*, open **My events** and choose **Edit**. After "
                                        "review, email us with your reference ID."),
        ("Does it cost anything?", "No. Community Voices connects you with vetted speakers at no charge."),
    ])

elif topic == "signin":
    st.header(":material/mark_email_read: Signing in")
    st.markdown(f"Enter your email and choose **Email me a code**. We send a 6-digit code from the Community "
                f"Voices mailbox. Type it in and you're signed in. No password or account is needed, and any "
                f"email address works.")
    ui.faq([
        ("I didn't get my code.", "Codes usually arrive within a minute. Check your **spam**, **promotions**, or "
                                  "**updates** folders, and search for *Community Voices sign-in code*. Then use "
                                  "**Resend code**. Company filters sometimes hold external mail for a few minutes."),
        ("How long does a code last?", f"{CODE_TTL // 60} minutes, for one use, with 5 attempts. Requesting a new "
                                       "code replaces the old one."),
        ("Why was I signed out after refreshing?", "Your sign-in lives in this browser tab. Refreshing the page or "
                                                    "opening a new tab means requesting a new code. Otherwise you "
                                                    "stay signed in for up to 12 hours."),
        ("It says too many code requests.", "To protect your inbox we limit codes to 3 per 15 minutes. Wait a few "
                                            "minutes, then try again."),
        ("I still can't sign in.", f"Email {ui.CONTACT_EMAIL} and tell us the address you used."),
    ])

elif topic == "bulk":
    st.header(":material/upload_file: Bulk upload template")
    st.markdown("1. Download the template. It includes one example row; replace it.\n"
                "2. Add one row per event. Dates use `YYYY-MM-DD`.\n"
                "3. In the Vendor Portal, open **Bulk upload** and choose your CSV or Excel file. We check every row "
                "before anything is submitted, and skip duplicates.")
    tpl = pd.DataFrame([vv.EXAMPLE_ROW], columns=vv.BULK_COLUMNS)
    st.download_button("Download template (CSV)", tpl.to_csv(index=False), file_name="cv_events_template.csv",
                       mime="text/csv", icon=":material/download:", key="help_tpl")
    st.markdown("**Column guide**")
    st.dataframe(pd.DataFrame([{"column": c, "required": "Yes" if c in vv.REQUIRED else "",
                                "notes": ", ".join(vv.FORMATS) if c == "event_format" else ""}
                               for c in vv.BULK_COLUMNS]), hide_index=True, width="stretch")

elif topic == "travel":
    st.header(":material/flight: Travel & reimbursement")
    st.markdown("Approved speakers can get help with travel to their event.")
    ui.faq([
        ("Can I book travel in the portal?", "Online booking for flights, hotels, and Uber codes is coming soon. "
                                             f"Until then, email {ui.CONTACT_EMAIL} with your event and dates and "
                                             "we'll arrange it."),
        ("How do I get reimbursed?", "Sign in on the Speaker Portal → *Travel & expenses* and submit your "
                                     "expenses. Attach receipts there if uploads are available. Otherwise email them "
                                     "with your confirmation ID as the subject. Reimbursements are processed within "
                                     "10 business days."),
        ("What's covered?", "Typically economy flights, hotel, and local transport for approved events. We'll confirm "
                            "what's covered for your trip before you book."),
    ])

else:
    st.header(":material/contact_support: Contact")
    st.markdown(f"Email **[{ui.CONTACT_EMAIL}](mailto:{ui.CONTACT_EMAIL})**. Include your reference or "
                "confirmation ID if you have one.")
