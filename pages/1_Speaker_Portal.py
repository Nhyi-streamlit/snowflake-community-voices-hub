"""Speaker Portal: get started, find events, resources, travel & expenses, and after-talk tools.

Public: everything except personal submissions. Personal sections (reimbursement, headcount) ask for the
speaker's email once per session (format-checked, no code is sent). The audience feedback link
(?speaker=&event=&talk=) opens the rating form directly, with no sign-in.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from contextlib import contextmanager
from datetime import datetime, date, timezone
from io import BytesIO
import urllib.parse
import streamlit as st
import pandas as pd
import requests as _requests
from utils import public_events
from utils import ui_components as ui
from utils.styles import inject_css
from utils.sections import SectionDone
from utils.sheets import read_tab, append_row, get_access_token, claim_uber_code, upload_file_to_drive, get_or_create_receipts_folder
from utils.confirmation import generate_confirmation_id

CONFERENCE_FORM_URL = "https://app-superhero-creator-form-5rkbvp9kjmrkjjkqfbslqj.streamlit.app/"
from workflow.runtime import get_actor
from workflow.ui import md

st.set_page_config(page_title="Speaker Portal — Community Voices", page_icon="🎤", layout="wide")
inject_css()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# Speaker's email for this session: typed in once (format-checked, not verified), or a Google sign-in.
from types import SimpleNamespace
from utils.email_otp import valid_email
speaker_identity = get_actor()
if speaker_identity is not None and not speaker_identity.email:
    speaker_identity = None          # password-only admin session: no personal identity
if speaker_identity is None and st.session_state.get("spk_email"):
    speaker_identity = SimpleNamespace(email=st.session_state["spk_email"])

params = st.query_params
_speaker_param = params.get("speaker", "")
_event_param   = params.get("event", "")
_talk_param    = params.get("talk", "")
_audience_mode = bool(_speaker_param and _event_param and _talk_param)

SLOTS_SHEET_ID = "1IgTYK8vV-AhDI3HuYB3KEjN8knRjY66LAOIWF0QT5II"

SECTIONS = {
    "start": ":material/waving_hand: Get started",
    "speak": ":material/event: Speak at an event",
    "resources": ":material/inventory_2: Resources",
    "travel": ":material/flight: Travel & expenses",
    "after": ":material/star: After your talk",
}


def _sync_section():
    st.query_params["section"] = st.session_state["spk_section"]


if _audience_mode:
    active = "feedback"              # audience QR link: only the rating form
else:
    if "spk_section" not in st.session_state:
        q = params.get("section", "start")
        st.session_state["spk_section"] = q if q in SECTIONS else "start"
    ui.hero("Speaker Portal", "Your Community Voices home",
            "Find an event, get your talk ready, and hear what your audience thought — all in one place.",
            theme="sky")
    # Horizontal radio (as in the Vendor Portal): testable with AppTest and always has a selection.
    active = st.radio("Section", list(SECTIONS), format_func=SECTIONS.get, key="spk_section", horizontal=True,
                      on_change=_sync_section, label_visibility="collapsed")


@contextmanager
def show(*names):
    """Section block. Its first statement is gate(...), which exits the block unless the section is active;
    SectionDone anywhere inside ends just this block (st.stop() would blank the rest of the page)."""
    try:
        yield
    except SectionDone:
        pass


def gate(*names):
    if active not in names:
        raise SectionDone


_sign_in_shown = False      # one sign-in box per run; a section can have several blocks that need it


def require_sign_in(what: str):
    """Ask for the speaker's email (no code, no account) and stop this section until it's entered."""
    global _sign_in_shown
    if speaker_identity is None:
        if _sign_in_shown:
            st.info(f"Enter your email above to {what}.", icon=":material/mail:")
            raise SectionDone
        _sign_in_shown = True
        with st.form("spk_email_form", border=True):
            st.markdown(f"Enter your email to {what}. We use it to match your submissions and reply to you.")
            entered = st.text_input("Your email", key="spk_email_input", placeholder="you@company.com")
            go = st.form_submit_button("Continue", type="primary")
        if go:
            if valid_email(entered):
                st.session_state["spk_email"] = entered.strip().lower()
                st.rerun()
            st.error("Enter a valid email address.")
        raise SectionDone


# ══════════════════════════════════════════════════════════════════════════════
# GET STARTED
# ══════════════════════════════════════════════════════════════════════════════
with show("start"):
    gate("start")
    st.subheader("How it works")
    ui.step_cards([("Pick an event", "See approved events looking for community speakers under **Speak at an event**."),
                   ("Get ready", "Use the brand kit, talk templates, and prep checklist under **Resources**."),
                   ("Speak & share", "Show your feedback QR code, then log attendance under **After your talk**.")])
    with st.container(border=True):
        st.markdown("#### :material/lightbulb: New here?")
        st.markdown("Community Voices supports Snowflake Data Superheroes, Squad members, Streamlit Creators, and "
                    "practitioners with a real story to tell. Browsing and resources are open to everyone — you "
                    "only enter your email for things tied to you, like reimbursements.")
        ui.help_link("speakers", "Read the speaker guide")
        ui.help_link("travel", "How travel and reimbursement work")
        st.link_button("Request conference support (Data Superheroes & Streamlit Creators)", CONFERENCE_FORM_URL,
                       icon=":material/flight_takeoff:")
    if speaker_identity is not None:
        st.caption(f"Using {md(speaker_identity.email)}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: AVAILABLE SPEAKING SLOTS
# ══════════════════════════════════════════════════════════════════════════════
with show("speak"):
    gate("speak")
    ui.coming_soon("Signing up for a speaking slot",
                   "Soon you'll be able to raise your hand for an event right here.")
    raise SectionDone       # legacy slot signup below is kept but paused
    st.markdown("### Available speaking slots")
    st.markdown("Events confirmed and actively seeking Snowflake community speakers. Sign up directly below.")

    REGION_COLORS = {
        "US Central":("#EBF8FF","#2B6CB0"),"US East":("#EBF8FF","#2B6CB0"),
        "US West":("#EBF8FF","#2B6CB0"),"APAC":("#F0FFF4","#276749"),
        "EMEA":("#FAF5FF","#553C9A"),"LATAM":("#FFFBEB","#B7791F"),
        "Canada":("#E6FFFA","#234E52"),
    }

    @st.cache_data(ttl=120)
    def load_slots():
        try:
            token = get_access_token()
            resp = _requests.get(
                f"https://sheets.googleapis.com/v4/spreadsheets/{SLOTS_SHEET_ID}/values/A1:G200",
                headers={"Authorization": f"Bearer {token}"}, timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("values", [])
        except Exception:
            return []

    @st.cache_data(ttl=300)
    def load_platform_events():
        try:
            events = read_tab("Events")
            if not events.empty and "status" in events:
                safe_cols = [col for col in ["event_id", "event_name", "event_city", "event_country", "event_start", "event_end", "event_format"] if col in events]
                events = events.loc[events["status"].eq("Approved"), safe_cols].copy()
            else:
                events = pd.DataFrame()
            return events, pd.DataFrame()
        except Exception:
            return pd.DataFrame(), pd.DataFrame()

    def write_signup_to_slots(sheet_row, name, email):
        try:
            token = get_access_token()
            resp = _requests.put(
                f"https://sheets.googleapis.com/v4/spreadsheets/{SLOTS_SHEET_ID}/values/Sheet1!F{sheet_row}:G{sheet_row}",
                params={"valueInputOption": "RAW"},
                json={"values": [[name, email]]},
                headers={"Authorization": f"Bearer {token}"}, timeout=15,
            )
            return resp.status_code == 200
        except Exception:
            return False

    if st.button("Refresh slots", key="refresh_slots"):
        st.cache_data.clear(); st.rerun()

    raw_rows = load_slots()
    df_platform, df_req = load_platform_events()

    if raw_rows and len(raw_rows) >= 4:
        header_idx = next((i for i,r in enumerate(raw_rows) if r and str(r[0]).strip().lower()=="city"), 2)
        data_rows = raw_rows[header_idx+1:]
        data_rows = [r+[""]*(7-len(r)) for r in data_rows if r and str(r[0]).strip()]
        df_slots = pd.DataFrame(data_rows, columns=["City","Date","Region","Partner","Status","Interested_Name","Email"])
        df_slots["_sheet_row"] = range(header_idx+2, header_idx+2+len(df_slots))
        open_slots = df_slots[df_slots["Status"].str.upper().str.strip()=="OPEN"].copy()

        # Sidebar filters
        with st.sidebar:
            st.markdown("### Filter")
            regions = sorted(open_slots["Region"].dropna().unique().tolist())
            sel_r = st.multiselect("Region", regions, key="sp_filter_r")
            partners = sorted(open_slots["Partner"].dropna().unique().tolist())
            sel_p = st.multiselect("Partner / series", partners, key="sp_filter_p")
            unclaimed = st.checkbox("Unclaimed only", key="sp_unclaimed")

        filtered = open_slots.copy()
        if sel_r: filtered = filtered[filtered["Region"].isin(sel_r)]
        if sel_p: filtered = filtered[filtered["Partner"].isin(sel_p)]
        if unclaimed: filtered = filtered[filtered["Interested_Name"].str.strip()==""]

        # Sort by date ──────────────────────────────────────────────────────────
        def _sort_key(d):
            """Convert 'Sep 2, 2026' / '9/2' / '9/10/2026' to a comparable string."""
            from datetime import datetime as _dt
            d = str(d).strip()
            for fmt in ("%m/%d/%Y","%m/%d","%b %d, %Y","%B %d, %Y","%b %d %Y"):
                try:
                    x = _dt.strptime(d.split()[0] if len(d.split()) == 1 else d, fmt)
                    if x.year < 2000: x = x.replace(year=2026)
                    return x.strftime("%Y-%m-%d")
                except Exception:
                    pass
            return d  # fallback — keeps original string order

        filtered = filtered.copy()
        filtered["_sort_date"] = filtered["Date"].apply(_sort_key)
        filtered = filtered.sort_values("_sort_date").reset_index(drop=True)

        st.markdown(f"**{len(filtered)} open slot(s) — sorted by date**")

        # ── Summary table ────────────────────────────────────────────────────
        display_df = filtered[["Date","City","Region","Partner","Interested_Name"]].copy()
        display_df.columns = ["Date","City","Region","Partner / Series","Interest Received From"]
        display_df["Interest Received From"] = display_df["Interest Received From"].replace("", "—")
        st.dataframe(
            display_df,
            width="stretch",
            hide_index=True,
        )

        st.markdown("---")
        st.markdown("#### Sign up for a slot")
        st.caption("Expand a row to register your interest.")

        for _, slot in filtered.iterrows():
            city=slot["City"]; ev_date=slot["Date"]; region=slot["Region"]
            partner=slot["Partner"]; sheet_row=int(slot["_sheet_row"])
            claimed=slot["Interested_Name"].strip()
            key_open=f"sp_open_{sheet_row}"; key_done=f"sp_done_{sheet_row}"

            label = f"📅 {ev_date}  ·  **{city}**  ·  {partner}  ·  {region}"
            if claimed:
                label += f"  ·  ✋ {claimed}"

            with st.expander(label):
                if st.session_state.get(key_done):
                    st.success("You're on the list!", icon="✅")
                    cid_val=st.session_state.get(f"sp_cid_{sheet_row}","")
                    if cid_val:
                        st.markdown(f"<div class='id-box' style='padding:8px 12px;'><div class='label' style='font-size:0.65rem;'>Confirmation ID</div><div class='id' style='font-size:0.9rem;'>{cid_val}</div></div>", unsafe_allow_html=True)
                elif st.session_state.get(key_open):
                    with st.form(key=f"sp_form_{sheet_row}"):
                        c_n, c_e = st.columns(2)
                        with c_n: n = st.text_input("Your name", key=f"sp_n_{sheet_row}")
                        with c_e: st.text_input("Your email", value=speaker_identity.email, disabled=True, key=f"sp_e_{sheet_row}")
                        e = speaker_identity.email
                        sub = st.form_submit_button("Submit interest", type="primary", width="stretch")
                    if sub and n and e:
                        write_signup_to_slots(sheet_row, n, e)
                        conf_id = generate_confirmation_id()
                        now = _now()
                        parts = n.split()
                        append_row("Speaker_Applications", [
                            conf_id, now, "Pending",
                            parts[0], " ".join(parts[1:]) if len(parts)>1 else "", e,
                            "","","","","",
                            "Community Member","","",
                            f"{partner} — {city}","",
                            ev_date,"",city,"",
                            "In-person conference","","","","","","",
                            "Travel grant (flights), Snowflake swag kit","","0",
                            f"Signed up from Events Board — {partner} {city} {ev_date}","","",
                        ])
                        st.session_state[key_done]=True; st.session_state[key_open]=False
                        st.session_state[f"sp_cid_{sheet_row}"]=conf_id
                        st.cache_data.clear(); st.rerun()
                    elif sub:
                        st.warning("Please enter both name and email.")
                else:
                    st.button("I'm interested in this slot", key=f"sp_btn_{sheet_row}",
                              on_click=lambda k=key_open: st.session_state.update({k:True}),
                              type="primary", width="stretch")
    else:
        st.info("No open slots found. Check back soon.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: UPCOMING EVENTS
# ══════════════════════════════════════════════════════════════════════════════
with show("speak"):
    gate("speak")
    st.markdown("### Upcoming events")
    st.caption("Approved Community Voices events from today onwards.")
    upcoming_df = public_events.upcoming()
    if upcoming_df is None:
        st.info("We couldn't load events right now. Please try again in a few minutes.", icon=":material/cloud_off:")
    elif upcoming_df.empty:
        st.info("No upcoming events yet — check back soon.", icon=":material/event_upcoming:")
    else:
        view = upcoming_df.rename(columns={"event_name": "Event", "event_city": "City", "event_country": "Country",
                                           "start": "Starts", "event_format": "Format"})
        st.dataframe(view[[c for c in ["Starts", "Event", "City", "Country", "Format"] if c in view]],
                     hide_index=True, width="stretch",
                     column_config={"Starts": st.column_config.DateColumn(format="MMM D, YYYY")})
        st.caption(f"{len(upcoming_df)} upcoming event(s)")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: RESOURCES
# ══════════════════════════════════════════════════════════════════════════════
with show("resources"):
    gate("resources")
    st.markdown("### Speaker resources")
    r_brand, r_talk, r_prep = st.tabs([":material/palette: Brand Kit", ":material/slideshow: Talk Templates",
                                       ":material/checklist: Speaker Prep"])

    with r_brand:
        st.markdown("#### Snowflake Brand Assets")
        c1,c2,c3=st.columns(3,gap="large")
        with c1:
            st.markdown("""<div class="info-card"><h4>Logo Files</h4>
            <p><a href="https://www.snowflake.com/en/company/newsroom/" target="_blank" style="color:#29B5E8;">Snowflake Press & Media Kit →</a><br>
            <small style="color:#718096;">Official logos, brand assets, and approved imagery are in the Snowflake press kit.</small></p></div>""", unsafe_allow_html=True)
        with c2:
            st.markdown("""<div class="info-card"><h4>Brand Colors</h4>
            <p><strong>Snowflake Blue:</strong> <code>#29B5E8</code><br>
            <strong>Dark Navy:</strong> <code>#0E2346</code><br>
            <strong>Light Blue:</strong> <code>#A8D8F0</code></p></div>""", unsafe_allow_html=True)
        with c3:
            st.markdown("""<div class="info-card"><h4>Fonts</h4>
            <p><strong>Primary:</strong> Inter<br>
            <a href="https://fonts.google.com/specimen/Inter" target="_blank" style="color:#29B5E8;">Download Inter →</a></p></div>""", unsafe_allow_html=True)
        st.markdown("**Social tags:** `#SnowflakeCommunity` `#DataSuperhero` `#StreamlitCreator`")

    with r_talk:
        st.markdown("#### Slide Templates")
        st.info(
            "Slide templates are shared with approved speakers via email. "
            "Request yours by emailing **aba.micah@snowflake.com** with subject: "
            "*Slide template request — [Your Name]*",
            icon="📊",
        )
        ca,cb=st.columns(2)
        with ca:
            st.markdown("""<div class="info-card"><h4>Standard Conference Template</h4>
            <p>16:9 dark theme · title slide, about me, agenda, content slides, closing with QR code placeholder.<br>
            <strong>Contact aba.micah@snowflake.com to request access.</strong></p></div>""", unsafe_allow_html=True)
        with cb:
            st.markdown("""<div class="info-card"><h4>Lightning Talk Template (15 min)</h4>
            <p>8 slides max · optimised for fast-paced conference sessions and meetup lightning rounds.<br>
            <strong>Contact aba.micah@snowflake.com to request access.</strong></p></div>""", unsafe_allow_html=True)
        st.markdown("**Bio format:** 50–100 words · role, company, speciality, community membership, LinkedIn URL")

    with r_prep:
        for phase, items in [
            ("6–8 weeks before",["Find an event under Speak at an event","Confirm session length and A/V with organizers"]),
            ("3–4 weeks before",["Draft slides using Snowflake template","Full rehearsal end-to-end","Submit bio and headshot","Generate your feedback QR code (After your talk)"]),
            ("Day of",["Arrive 30 min early — test A/V and clicker","QR code on last slide","Stay for Q&A"]),
            ("After",["Share slides publicly","Post on social — tag @Snowflake + #SnowflakeCommunity","Log attendance under After your talk"]),
        ]:
            with st.expander(phase):
                for item in items: st.markdown(f"☐ {item}")

    ui.help_link("speakers", "More questions? See the speaker FAQ")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: TALK FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════
with show("feedback", "after"):
    gate("feedback", "after")
    if _audience_mode:
        # ── Audience rating mode ──────────────────────────────────────────────
        ui.hero("Rate this Talk", _talk_param, f"{_speaker_param} · {_event_param}")   # hero() escapes

        if st.session_state.get("sp_fb_done"):
            st.success("**Thank you!** Your feedback helps our community speakers grow.", icon=":material/favorite:")
        else:
            r_overall  = st.slider("Overall rating", 1, 5, 4, format="%d ⭐", key="fb_overall")
            r_content  = st.slider("Content quality", 1, 5, 4, format="%d ⭐", key="fb_content")
            r_delivery = st.slider("Delivery", 1, 5, 4, format="%d ⭐", key="fb_delivery")
            r_relevance= st.slider("Relevance to your work", 1, 5, 4, format="%d ⭐", key="fb_relevance")
            st.divider()
            valuable   = st.text_area("Most valuable takeaway?", height=80, key="fb_valuable")
            would_attend = st.radio("Would you attend another talk by this speaker?",["Definitely yes","Probably yes","Not sure","Probably not"], horizontal=True, key="fb_attend")
            c1f,c2f=st.columns(2)
            with c1f: resp_name=st.text_input("Your name (optional)", key="fb_resp_name")
            with c2f: resp_email=st.text_input("Your email (optional)", key="fb_resp_email")
            if st.button("Submit Feedback", type="primary", width="stretch", key="fb_submit"):
                import uuid
                row=[str(uuid.uuid4())[:8].upper(),_now(),
                     _speaker_param,_event_param,_talk_param,"",
                     str(r_overall),str(r_content),str(r_delivery),str(r_relevance),
                     valuable or "",would_attend,"","",resp_name or "",resp_email or "",""]
                if append_row("Talk_Feedback",row):
                    st.session_state["sp_fb_done"]=True; st.rerun()
                else:
                    st.error("We couldn't save your rating just now. Please try again in a moment.")
    else:
        # ── Speaker: generate QR code ─────────────────────────────────────────
        st.markdown("### :material/qr_code_2: Talk feedback QR code")
        st.markdown("After your talk, display this QR code so the audience can rate you in 30 seconds.")
        spk_name = st.text_input("Your full name *", key="qr_name")
        spk_event= st.text_input("Event name *", key="qr_event")
        spk_talk = st.text_input("Talk title *", key="qr_talk")
        if st.button("Generate QR Code", type="primary", disabled=not(spk_name and spk_event and spk_talk), key="qr_gen"):
            try:
                import qrcode
                app_base=""
                try: app_base=st.secrets.get("APP_BASE_URL","")
                except Exception: pass
                if not app_base: app_base="https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app"
                fb_url=(f"{app_base.rstrip('/')}/Speaker_Portal"
                        f"?speaker={urllib.parse.quote(spk_name)}"
                        f"&event={urllib.parse.quote(spk_event)}"
                        f"&talk={urllib.parse.quote(spk_talk)}")
                qr=qrcode.QRCode(version=1,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=10,border=4)
                qr.add_data(fb_url); qr.make(fit=True)
                img=qr.make_image(fill_color="#0E2346",back_color="white")
                buf=BytesIO(); img.save(buf,format="PNG"); buf.seek(0)
                ci1,ci2=st.columns([1,1])
                with ci1:
                    st.image(buf,width="stretch")
                    st.download_button("Download QR PNG",data=buf.getvalue(),
                        file_name=f"feedback-{spk_name.replace(' ','-').lower()}.png",
                        mime="image/png",width="stretch")
                with ci2:
                    with st.container(border=True):
                        st.markdown("**Shareable link**")
                        st.code(fb_url, language=None, wrap_lines=True)
                    with st.container(border=True):
                        st.markdown("**How to use**")
                        st.markdown("1. Download the QR PNG\n2. Add it to your last slide\n"
                                    "3. Or paste the link in the event chat\n4. Audience scans → 30-second rating form")
            except ImportError:
                st.error("Run: pip install qrcode[pil] Pillow")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: BOOK YOUR TRAVEL
# ══════════════════════════════════════════════════════════════════════════════
with show("travel"):
    gate("travel")

    with st.container(border=True):
        st.markdown("#### :material/flight_takeoff: Speaking at a conference?")
        st.markdown("Data Superheroes and Streamlit Creators can request travel and event support. "
                    "Once the program team approves your request, we arrange booking with our travel partner.")
        st.link_button("Request conference support (Data Superheroes & Streamlit Creators)", CONFERENCE_FORM_URL,
                       icon=":material/open_in_new:", type="primary")

    # ── Expense form template download + upload ────────────────────────────
    st.markdown("### :material/receipt_long: Expense reimbursement")
    st.markdown(
        "Download the expense form template, fill it in offline, and upload it here. "
        "Your completed form is saved to Google Drive where the program team can review and share it with finance."
    )

    _TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "expense_form_template.xlsx")

    try:
        with open(_TEMPLATE_PATH, "rb") as _tf:
            _template_bytes = _tf.read()
        st.download_button(
            ":material/download: Download expense form template",
            data=_template_bytes,
            file_name="Expense_Form_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_expense_template",
        )
    except FileNotFoundError:
        st.warning("Expense form template not found. Contact aba.micah@snowflake.com to get one.")

    st.divider()
    st.markdown("#### Upload your completed expense form")
    require_sign_in("submit an expense form")

    if st.session_state.get("sp_expense_upload_done"):
        st.success("Expense form uploaded. The program team will review it and forward to finance.")
        _exp_link = st.session_state.get("sp_expense_drive_link", "")
        if _exp_link:
            st.markdown(f"[View your uploaded form in Google Drive]({_exp_link})")
        if st.button("Upload another form", key="sp_expense_reset"):
            st.session_state.pop("sp_expense_upload_done", None)
            st.session_state.pop("sp_expense_drive_link", None)
            st.rerun()
        raise SectionDone

    _exp_name = st.text_input("Your full name *", key="exp_name")
    _exp_event = st.text_input("Event name *", placeholder="Data Summit NYC", key="exp_event")
    _exp_file = st.file_uploader(
        "Upload completed expense form",
        type=["xlsx", "xls", "pdf", "csv"],
        accept_multiple_files=False,
        key="exp_file_upload",
    )
    _exp_notes = st.text_area("Notes for the reviewer (optional)", height=80, key="exp_notes")

    st.info(
        "Accepted formats: `.xlsx`, `.xls`, `.pdf`, `.csv`. "
        "Reimbursements are processed within **10 business days** of approval.",
        icon=":material/info:",
    )

    _exp_can_submit = all([_exp_name, _exp_event, _exp_file])
    if not _exp_can_submit:
        st.caption("Fill in your name, event, and attach the form to submit.")

    if st.button("Submit expense form", type="primary", disabled=not _exp_can_submit, key="exp_submit"):
        import uuid as _uuid_exp
        import mimetypes as _mt_exp

        _exp_id = "EXP-2026-" + _uuid_exp.uuid4().hex[:8].upper()
        _exp_now = _now()
        _exp_data = _exp_file.getvalue()
        _exp_mime = _exp_file.type or _mt_exp.guess_type(_exp_file.name)[0] or "application/octet-stream"

        # Upload to Google Drive
        _drive_link = ""
        try:
            folder_id = get_or_create_receipts_folder(_exp_id)
            if folder_id:
                _drive_link = upload_file_to_drive(_exp_data, _exp_file.name, _exp_mime, folder_id) or ""
        except Exception:
            pass

        _status = "Uploaded to Drive" if _drive_link else "Upload failed — email form to aba.micah@snowflake.com"

        _row = [
            _exp_id, _exp_now,
            _exp_name.strip(), speaker_identity.email,
            _exp_event.strip(), _exp_file.name,
            _drive_link, _exp_notes or "", _status,
        ]
        if append_row("Expense_Forms", _row):
            st.session_state["sp_expense_upload_done"] = True
            st.session_state["sp_expense_drive_link"] = _drive_link
            st.rerun()
        else:
            st.error("Could not save. Please try again or email aba.micah@snowflake.com.")

    ui.help_link("travel", "How travel support works")
    raise SectionDone       # legacy booking form below is kept but paused

    st.markdown("### Book your travel")
    st.markdown(
        "Fill in this form and our travel partner **Navan** will book your flights and hotel. "
        "You'll receive your confirmed itinerary by email within **2 business days**."
    )

    if st.session_state.get("sp_travel_done"):
        st.success("Travel request recorded. Automated notification is not enabled; contact the program team to confirm processing.")
        raise SectionDone

    if False:
        uber_code_tv = st.session_state.get("sp_travel_uber_code", "")
        if uber_code_tv:
            st.markdown(f"""<div class="success-box">
                <h2>Travel request received!</h2>
                <p>Navan will arrange your flights and hotel and send your itinerary within 2 business days.</p>
                <div style="margin-top:16px;padding:16px;background:#F0FFF4;border:2px solid #38A169;border-radius:8px;text-align:center;">
                    <div style="font-size:0.75rem;color:#276749;text-transform:uppercase;letter-spacing:0.05em;">Your Uber Code</div>
                    <div style="font-size:1.5rem;font-weight:700;color:#276749;font-family:monospace;margin-top:4px;">{uber_code_tv}</div>
                    <div style="font-size:0.8rem;color:#718096;margin-top:4px;">Use this for local transport to/from the event venue.</div>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="success-box"><h2>Travel request received!</h2><p>Navan will arrange your flights and hotel and send your itinerary within 2 business days.</p><p style="color:#E53E3E;"><strong>No Uber codes available right now.</strong> Contact aba.micah@snowflake.com to receive one.</p></div>', unsafe_allow_html=True)
        if st.button("Submit another travel request", key="sp_travel_reset"):
            st.session_state.pop("sp_travel_done", None)
            st.session_state.pop("sp_travel_uber_code", None)
            st.rerun()
        raise SectionDone

    # ── Section 1: Personal details ───────────────────────────────────
    st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Personal details</div>', unsafe_allow_html=True)
    pd1, pd2 = st.columns(2)
    with pd1:
        tv_email = st.text_input("Your email", value=speaker_identity.email, disabled=True, key="tv_email")
        tv_email = speaker_identity.email
    with pd2:
        passport_name = st.text_input(
            "Full name as on passport *",
            placeholder="Ada Lovelace",
            key="tv_passport_name",
        )
    pd3, pd4 = st.columns(2)
    with pd3:
        dob = st.text_input(
            "Date of birth (DD/MM/YYYY) *",
            placeholder="15/03/1990",
            key="tv_dob",
        )
    with pd4:
        phone = st.text_input(
            "Mobile number (with country code)",
            placeholder="+1 415 000 0000",
            key="tv_phone",
        )
    pd5, pd6 = st.columns(2)
    with pd5:
        passport_no = st.text_input(
            "Passport number",
            placeholder="AB1234567",
            key="tv_passport_no",
        )
    with pd6:
        passport_exp = st.text_input(
            "Passport expiry date",
            placeholder="2029-06-30",
            key="tv_passport_exp",
        )
    nationality = st.text_input("Nationality / citizenship", key="tv_nationality")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 2: Event & Flights ────────────────────────────────────
    st.markdown('<div class="step-label">Section 2 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Event & flight preferences</div>', unsafe_allow_html=True)
    ev1, ev2 = st.columns(2)
    with ev1:
        tv_event_name = st.text_input("Event name *", placeholder="Data Summit NYC", key="tv_event_name")
    with ev2:
        tv_event_city = st.text_input("Event city *", placeholder="New York", key="tv_event_city")
    tv_event_date = st.text_input("Event date(s) *", placeholder="2026-10-15", key="tv_event_date")

    fl1, fl2 = st.columns(2)
    with fl1:
        fly_from = st.text_input(
            "Departing from (city / airport) *",
            placeholder="London Heathrow (LHR)",
            key="tv_fly_from",
        )
    with fl2:
        fly_to = st.text_input(
            "Flying to (city / airport) *",
            key="tv_fly_to",
        )
    fl3, fl4 = st.columns(2)
    with fl3:
        outbound_date = st.text_input(
            "Outbound travel date *",
            placeholder="2026-09-09",
            key="tv_outbound",
        )
    with fl4:
        return_date = st.text_input(
            "Return travel date *",
            placeholder="2026-09-12",
            key="tv_return",
        )
    fl5, fl6 = st.columns(2)
    with fl5:
        seat_class = st.selectbox(
            "Preferred seat class",
            ["Economy", "Premium Economy", "Business"],
            key="tv_class",
        )
    with fl6:
        airline_pref = st.text_input(
            "Preferred airline (if any)",
            placeholder="Delta, United, BA...",
            key="tv_airline_pref",
        )
    ff_number = st.text_input(
        "Frequent flyer number(s)",
        placeholder="DL 123456789, UA 987654321",
        key="tv_ff",
    )
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 3: Hotel ──────────────────────────────────────────────
    st.markdown('<div class="step-label">Section 3 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Hotel preferences</div>', unsafe_allow_html=True)
    ht1, ht2 = st.columns(2)
    with ht1:
        hotel_checkin = st.text_input(
            "Check-in date *",
            placeholder="2026-09-09",
            key="tv_hotel_in",
        )
    with ht2:
        hotel_checkout = st.text_input(
            "Check-out date *",
            placeholder="2026-09-12",
            key="tv_hotel_out",
        )
    hotel_pref = st.selectbox(
        "Hotel preference",
        ["Near the event venue", "Near the city centre / downtown", "No preference"],
        key="tv_hotel_pref",
    )
    hotel_loyalty = st.text_input(
        "Hotel loyalty number(s)",
        placeholder="Marriott Bonvoy 123456, Hilton Honors 654321",
        key="tv_hotel_loyalty",
    )
    hotel_notes = st.text_input(
        "Any specific hotel requirements?",
        placeholder="Non-smoking, high floor, accessible room...",
        key="tv_hotel_notes",
    )
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 4: Additional info ─────────────────────────────────────
    st.markdown('<div class="step-label">Section 4 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Additional information</div>', unsafe_allow_html=True)
    dietary = st.text_input(
        "Dietary requirements",
        placeholder="Vegetarian, gluten-free, nut allergy...",
        key="tv_dietary",
    )
    emergency_name = st.text_input(
        "Emergency contact name",
        placeholder="Jane Lovelace",
        key="tv_emerg_name",
    )
    emergency_phone = st.text_input(
        "Emergency contact phone",
        placeholder="+1 415 000 0001",
        key="tv_emerg_phone",
    )
    tv_notes = st.text_area(
        "Anything else Navan should know?",
        height=80,
        placeholder="Visa required, connecting through a hub city, arriving a day early...",
        key="tv_notes",
    )

    st.info(
        "Navan will book economy class by default unless business class is requested and approved. "
        "Requests are processed within 2 business days — you'll receive your itinerary directly by email.",
        icon="✈️",
    )

    required_ok = all([tv_email, passport_name, dob, tv_event_name, tv_event_city, tv_event_date, fly_from, fly_to, outbound_date, return_date, hotel_checkin, hotel_checkout])
    if not required_ok:
        st.caption("Complete all required fields (*) to submit.")

    tv_submit_clicked = st.button("Submit Travel Request", type="primary",
                                   width="stretch", key="tv_submit")

    if tv_submit_clicked and not required_ok:
        st.error("Please click into another field to confirm your last entry, then complete all required fields (*).", icon="⚠️")

    if tv_submit_clicked and required_ok:
        import uuid
        now = _now()
        uber_code = claim_uber_code(tv_email.strip(), "Travel")
        row = [
            str(uuid.uuid4())[:8].upper(), now,
            passport_name, tv_email.strip(),
            tv_event_name, tv_event_city, tv_event_date,
            # Personal details
            passport_name, dob, passport_no, passport_exp, nationality, phone,
            # Flights
            fly_from, fly_to, outbound_date, return_date, seat_class,
            airline_pref or "", ff_number or "",
            # Hotel
            hotel_checkin, hotel_checkout, hotel_pref,
            hotel_loyalty or "", hotel_notes or "",
            # Additional
            dietary or "", emergency_name or "", emergency_phone or "",
            tv_notes or "", uber_code or "", "Pending Booking",
        ]
        if append_row("Travel_Details", row):
            # Legacy direct-email path is disabled until routed outbox delivery is configured.
            st.session_state["sp_travel_done"] = True
            st.session_state["sp_travel_uber_code"] = uber_code or ""
            st.rerun()
        else:
            st.error("Could not save. Please try again or email aba.micah@snowflake.com.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: UBER REQUEST
# ══════════════════════════════════════════════════════════════════════════════
with show("travel"):
    gate("travel")
    raise SectionDone       # paused; covered by the coming-soon card above
    st.markdown("### Request an Uber gift card")
    st.markdown(
        "Approved speakers can request an Uber gift card for local transport to and from the event venue."
    )

    if st.session_state.get("sp_uber_done"):
        uber_code_ub = st.session_state.get("sp_uber_code", "")
        if uber_code_ub:
            st.markdown(f"""<div class="success-box">
                <h2>Uber request submitted!</h2>
                <div style="margin-top:16px;padding:16px;background:#F0FFF4;border:2px solid #38A169;border-radius:8px;text-align:center;">
                    <div style="font-size:0.75rem;color:#276749;text-transform:uppercase;letter-spacing:0.05em;">Your Uber Code</div>
                    <div style="font-size:1.5rem;font-weight:700;color:#276749;font-family:monospace;margin-top:4px;">{uber_code_ub}</div>
                    <div style="font-size:0.8rem;color:#718096;margin-top:4px;">Use this for rides to/from the event venue.</div>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="success-box"><h2>Uber request submitted!</h2><p style="color:#E53E3E;"><strong>No Uber codes available right now.</strong> Contact aba.micah@snowflake.com to receive one.</p></div>', unsafe_allow_html=True)
        if st.button("Submit another request", key="sp_uber_reset"):
            st.session_state.pop("sp_uber_done", None)
            st.session_state.pop("sp_uber_code", None)
            st.rerun()
        raise SectionDone

    st.markdown("**Your details**")
    ub1, ub2 = st.columns(2)
    with ub1: st.text_input("Your email", value=speaker_identity.email, disabled=True, key="ub_email")
    ub_email = speaker_identity.email
    with ub2: ub_name  = st.text_input("Your full name *", key="ub_name")

    ub3, ub4 = st.columns(2)
    with ub3: ub_event = st.text_input("Event name *", placeholder="Data Summit NYC", key="ub_event")
    with ub4: ub_city  = st.text_input("Event city *", placeholder="New York", key="ub_city")
    ub_event_date = st.text_input("Event date(s) *", placeholder="2026-10-15", key="ub_event_date")

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)
    st.markdown("**Uber request details**")
    uc1, uc2 = st.columns(2)
    with uc1:
        rides = st.selectbox("Rides needed",
            ["1 (one-way)", "2 (round trip — to venue + back)", "4 (both days)", "Other"],
            key="ub_rides")
    with uc2:
        amount = st.number_input("Estimated amount (USD)",
            min_value=5, max_value=500, step=5, value=100, key="ub_amount")
    ub_notes = st.text_area(
        "Notes (pickup/dropoff locations, special requirements)",
        height=80, placeholder="Pickup: hotel downtown -> drop-off: venue address...",
        key="ub_notes")

    st.info(
        "Standard Uber gift card allowance is **$100 per event** (round trip). "
        "Requests above $100 require a brief note explaining the need.",
        icon="💳",
    )

    ub_required = all([ub_email, ub_name, ub_event, ub_city, ub_event_date])
    if not ub_required:
        st.caption("Complete all required fields (*) to submit.")

    ub_submit_clicked = st.button("Submit Uber Request", type="primary",
                                   width="stretch", key="ub_submit")

    if ub_submit_clicked and not ub_required:
        st.error("Please click into another field to confirm your last entry, then complete all required fields (*).", icon="⚠️")

    if ub_submit_clicked and ub_required:
        import uuid
        now = _now()
        uber_code = claim_uber_code(ub_email.strip(), "Uber")
        row = [
            str(uuid.uuid4())[:8].upper(), now,
            ub_name.strip(), ub_email.strip(),
            ub_event, ub_city, ub_event_date,
            rides, str(amount), ub_notes or "", uber_code or "", "Fulfilled" if uber_code else "Pending — No codes",
        ]
        if append_row("Uber_Requests", row):
            st.session_state["sp_uber_done"] = True
            st.session_state["sp_uber_code"] = uber_code or ""
            st.rerun()
        else:
            st.error("Could not submit. Please try again.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: REIMBURSEMENT
# ══════════════════════════════════════════════════════════════════════════════
with show("travel"):
    gate("travel")
    st.divider()
    if speaker_identity is None:
        st.markdown("### Expense reimbursement")
    require_sign_in("submit a reimbursement")
    import uuid as _uuid

    st.markdown("### Expense reimbursement")
    st.markdown(
        "Submit out-of-pocket expenses for your Community Voices speaking engagement. "
        "You'll receive a confirmation ID — use it as the subject when emailing your receipts."
    )

    if st.session_state.get("sp_reimb_done"):
        st.success("Reimbursement request recorded. Check your confirmation ID below.")
        raise SectionDone

    # ── Success state ─────────────────────────────────────────────────────────
    if st.session_state.get("sp_reimb_done"):
        conf_id_done = st.session_state.get("sp_reimb_conf_id", "")
        st.markdown(f"""<div class="success-box">
            <h2>Reimbursement request submitted!</h2>
            <p>We'll review your claim and process it within <strong>10 business days</strong>.</p>
            {'<div style="margin-top:16px;padding:16px;background:#EBF8FF;border:2px solid #3182CE;border-radius:8px;text-align:center;"><div style="font-size:0.75rem;color:#2B6CB0;text-transform:uppercase;letter-spacing:0.05em;">Your Confirmation ID</div><div style="font-size:1.4rem;font-weight:700;color:#2B6CB0;font-family:monospace;margin-top:4px;">' + conf_id_done + '</div></div>' if conf_id_done else ''}
            <p style="margin-top:16px;">
                <strong>Next step:</strong> Email your receipts to
                <a href="mailto:aba.micah@snowflake.com" style="color:#29B5E8;">aba.micah@snowflake.com</a>
                with subject: <em>Receipts — {conf_id_done}</em>
            </p>
        </div>""", unsafe_allow_html=True)
        if st.button("Submit another reimbursement", key="sp_reimb_reset"):
            st.session_state.pop("sp_reimb_done", None)
            st.session_state.pop("sp_reimb_conf_id", None)
            st.rerun()
        raise SectionDone

    EXPENSE_CATEGORIES = ["Meals", "Ground transport", "Accommodation", "Registration fee", "Other"]
    CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "SGD", "Other"]
    _NUM_ROWS = 5

    # All fields inside st.form so values commit atomically on submit click
    with st.form("reimb_form"):

        # ── Section 1: Your details ───────────────────────────────────────────
        st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Your details</div>', unsafe_allow_html=True)
        rb1, rb2 = st.columns(2)
        with rb1:
            rf_name  = st.text_input("Full name *", key="rf_name")
        with rb2:
            st.text_input("Your email", value=speaker_identity.email, disabled=True, key="rf_email")
            rf_email = speaker_identity.email
        rb3, rb4, rb5 = st.columns(3)
        with rb3:
            rf_event = st.text_input("Event name *", placeholder="Data Summit NYC", key="rf_event")
        with rb4:
            rf_city  = st.text_input("Event city *", placeholder="New York", key="rf_city")
        with rb5:
            rf_date  = st.text_input("Event date(s) *", placeholder="2026-10-15", key="rf_date")
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # ── Section 2: Expenses (5 fixed rows) ───────────────────────────────
        st.markdown('<div class="step-label">Section 2 of 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Expense items</div>', unsafe_allow_html=True)
        st.caption("Fill in up to 5 expenses. Leave Amount at $0.00 for unused rows.")

        hc1, hc2, hc3, hc4, hc5 = st.columns([2, 3, 2, 1.5, 1.5])
        with hc1: st.markdown("**Category**")
        with hc2: st.markdown("**Description**")
        with hc3: st.markdown("**Date**")
        with hc4: st.markdown("**Amount**")
        with hc5: st.markdown("**Currency**")

        for _i in range(_NUM_ROWS):
            ec1, ec2, ec3, ec4, ec5 = st.columns([2, 3, 2, 1.5, 1.5])
            with ec1:
                st.selectbox(" ", EXPENSE_CATEGORIES, key=f"rf_cat_{_i}", label_visibility="collapsed")
            with ec2:
                st.text_input(" ", placeholder="e.g. Airport taxi", key=f"rf_desc_{_i}", label_visibility="collapsed")
            with ec3:
                st.text_input(" ", placeholder="2026-10-15", key=f"rf_edate_{_i}", label_visibility="collapsed")
            with ec4:
                st.number_input(" ", min_value=0.0, step=0.01, value=0.0, key=f"rf_amt_{_i}", label_visibility="collapsed")
            with ec5:
                st.selectbox(" ", CURRENCIES, key=f"rf_cur_{_i}", label_visibility="collapsed")
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # ── Section 3: Payment details ────────────────────────────────────────
        st.markdown('<div class="step-label">Section 3 of 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Payment details</div>', unsafe_allow_html=True)

        rf_pay_method = st.radio(
            "How would you like to be paid? *",
            ["PayPal", "Bank transfer"],
            horizontal=True,
            key="rf_pay_method",
        )

        if rf_pay_method == "PayPal":
            rf_paypal = st.text_input("PayPal email *", placeholder="your@paypal.com", key="rf_paypal")
            rf_bank_name = rf_account = rf_routing = ""
        else:
            st.markdown("**Bank transfer details**")
            bk1, bk2 = st.columns(2)
            with bk1:
                rf_bank_name = st.text_input("Bank name *", placeholder="Chase, HSBC, Barclays...", key="rf_bank_name")
            with bk2:
                st.text_input("Account holder name *", key="rf_account_holder")
            bk3, bk4 = st.columns(2)
            with bk3:
                rf_account = st.text_input("Account number *", key="rf_account")
            with bk4:
                rf_routing = st.text_input(
                    "Routing / SWIFT / IBAN *",
                    placeholder="For US: routing number. International: SWIFT or IBAN",
                    key="rf_routing",
                )
            rf_paypal = ""

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # ── Section 4: Notes & receipts ───────────────────────────────────────
        st.markdown('<div class="step-label">Section 4 of 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Notes & receipts</div>', unsafe_allow_html=True)

        rf_notes = st.text_area(
            "Any notes for the reviewer?",
            height=80,
            placeholder="E.g. Flight was delayed so I had to book a separate taxi; hotel receipt is included...",
            key="rf_notes",
        )

        rf_receipts = st.file_uploader(
            "Upload receipts (images or PDFs)",
            type=["png", "jpg", "jpeg", "pdf", "heic"],
            accept_multiple_files=True,
            key="rf_receipts",
        )

        st.info(
            "Upload receipts above **or** email them separately to **aba.micah@snowflake.com** "
            "with subject: **Receipts — [Your Confirmation ID]**. "
            "Reimbursements are processed within **10 business days** of receipt approval.",
            icon="🧾",
        )

        submitted = st.form_submit_button(
            "Submit Reimbursement Request", type="primary", width="stretch"
        )

    # ── Handle submission (outside form — values are now fully committed) ──────
    if submitted:
        expense_lines = []
        total_usd = 0.0
        for _i in range(_NUM_ROWS):
            amt = st.session_state.get(f"rf_amt_{_i}", 0.0) or 0.0
            if amt > 0:
                cat   = st.session_state.get(f"rf_cat_{_i}", "")
                desc  = st.session_state.get(f"rf_desc_{_i}", "")
                edate = st.session_state.get(f"rf_edate_{_i}", "")
                cur   = st.session_state.get(f"rf_cur_{_i}", "USD")
                expense_lines.append(f"{cat} · {desc} · {edate} · {amt:.2f} {cur}")
                if cur == "USD":
                    total_usd += amt

        missing = []
        if not all([rf_name, rf_email, rf_event, rf_city, rf_date]):
            missing.append("complete all required fields in Section 1")
        if not expense_lines:
            missing.append("add at least one expense with an amount greater than $0")
        if rf_pay_method == "PayPal" and not rf_paypal.strip():
            missing.append("enter your PayPal email in Section 3")
        elif rf_pay_method == "Bank transfer" and not all([
            st.session_state.get("rf_bank_name", ""),
            st.session_state.get("rf_account_holder", ""),
            st.session_state.get("rf_account", ""),
            st.session_state.get("rf_routing", ""),
        ]):
            missing.append("complete all bank transfer details in Section 3")

        if missing:
            st.error("Please fix: " + "; ".join(missing) + ".", icon="⚠️")
        else:
            reimb_id = "REIMB-2026-" + _uuid.uuid4().hex[:8].upper()
            now = _now()
            expenses_summary = "\n".join(expense_lines)
            total_str = f"${total_usd:,.2f} USD"

            if rf_pay_method == "PayPal":
                paypal_val = rf_paypal.strip()
                bank_name_val = bank_account_val = bank_routing_val = ""
            else:
                paypal_val = ""
                bank_name_val    = st.session_state.get("rf_bank_name", "")
                bank_account_val = st.session_state.get("rf_account", "")
                bank_routing_val = st.session_state.get("rf_routing", "")

            # Prepare receipt file dicts for Drive upload and email
            import mimetypes as _mimetypes
            attachments = []
            for f in (rf_receipts or []):
                mime_type = f.type or _mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                attachments.append({"filename": f.name, "data": f.read(), "mime_type": mime_type})

            # Upload receipts to Google Drive
            drive_links = []
            if attachments:
                try:
                    drive_links = upload_receipts_to_drive(reimb_id, attachments)
                except Exception:
                    pass  # fall back to email-only

            if drive_links:
                receipt_links_str = "\n".join(drive_links)
                receipt_status = f"Uploaded — {len(drive_links)} file(s) in Drive"
            elif attachments:
                receipt_links_str = "Email only"
                receipt_status = "Uploaded — email only"
            else:
                receipt_links_str = ""
                receipt_status = "Pending — awaiting email"

            sheet_row = [
                reimb_id, now,
                rf_name.strip(), rf_email.strip(),
                rf_event, rf_city, rf_date,
                expenses_summary,
                total_str,
                rf_pay_method, paypal_val,
                bank_name_val, bank_account_val, bank_routing_val,
                rf_notes or "",
                receipt_status,
                "Pending Review",
                receipt_links_str,
            ]

            if append_row("Reimbursements", sheet_row):
                from html import escape as _e      # every speaker-typed value below is escaped
                expense_rows_html = "".join(
                    f"<tr><td style='padding:6px 8px;border:1px solid #E2E8F0;'>{_e(str(line))}</td></tr>"
                    for line in expense_lines
                )
                payment_detail = _e(
                    f"PayPal: {paypal_val}" if rf_pay_method == "PayPal"
                    else f"Bank transfer — {bank_name_val} / {bank_account_val} / {bank_routing_val}"
                )

                drive_links_html = ""
                if drive_links:
                    links_list = "".join(f'<li><a href="{_e(lnk)}">{_e(lnk)}</a></li>' for lnk in drive_links)
                    drive_links_html = f"<h4 style='color:#0E2346;margin-top:16px;'>Receipt files (Google Drive)</h4><ul>{links_list}</ul>"

                receipt_note = (
                    f"{len(attachments)} receipt(s) attached.{' Also saved to Drive.' if drive_links else ''}"
                    if attachments
                    else f"No receipts uploaded — speaker may email with subject: Receipts — {reimb_id}"
                )

                send_gmail_with_attachments(
                    ["aba.micah@snowflake.com"],
                    f"Reimbursement Request — {rf_name.strip()} — {rf_event} ({rf_city})",
                    f"""<div style="font-family:Inter,Arial,sans-serif;max-width:640px;">
                    <h2 style="color:#0E2346;">New Expense Reimbursement Request</h2>
                    <table style="border-collapse:collapse;width:100%;margin:12px 0;">
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;width:30%;">Confirmation ID</td><td style="padding:8px;border:1px solid #E2E8F0;font-family:monospace;font-weight:700;">{reimb_id}</td></tr>
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Speaker</td><td style="padding:8px;border:1px solid #E2E8F0;">{_e(rf_name.strip())} ({_e(rf_email.strip())})</td></tr>
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Event</td><td style="padding:8px;border:1px solid #E2E8F0;">{_e(str(rf_event))} — {_e(str(rf_city))} ({_e(str(rf_date))})</td></tr>
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Total (USD)</td><td style="padding:8px;border:1px solid #E2E8F0;font-weight:700;">{_e(str(total_str))}</td></tr>
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Payment</td><td style="padding:8px;border:1px solid #E2E8F0;">{payment_detail}</td></tr>
                    <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Receipts</td><td style="padding:8px;border:1px solid #E2E8F0;">{receipt_note}</td></tr>
                    </table>
                    <h4 style="color:#0E2346;margin-top:16px;">Expense items</h4>
                    <table style="border-collapse:collapse;width:100%;margin-bottom:12px;">
                    {expense_rows_html}
                    </table>
                    {drive_links_html}
                    {f'<p><strong>Notes:</strong> {_e(rf_notes)}</p>' if rf_notes else ''}
                    <p style="color:#718096;font-size:0.85rem;margin-top:16px;">
                        This is an automated notification from the Community Voices platform.
                    </p>
                    </div>""",
                    attachments=attachments or None,
                )
                st.session_state["sp_reimb_done"] = True
                st.session_state["sp_reimb_conf_id"] = reimb_id
                st.rerun()
            else:
                st.error("Could not save your request. Please try again or email aba.micah@snowflake.com.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: EVENT HEADCOUNT — on-device person detection, results saved to Google Sheets
# ═══════════════════════════════════════════════════════════════════════════════
HEADCOUNT_TAB = "Event_Headcount"


@st.cache_resource(show_spinner="Loading the people detector (first use only)…")
def _hc_detector():
    from utils import person_detector
    return person_detector.load_session()


def _hc_preview(data: bytes, boxes: list) -> bytes:
    from PIL import Image, ImageDraw, ImageOps
    img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    img.thumbnail((2560, 2560))
    draw = ImageDraw.Draw(img)
    width = max(2, img.width // 400)
    for b in boxes:
        draw.rectangle(b, outline=(41, 181, 232), width=width)
    img.thumbnail((1200, 1200))
    out = BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


with show("after"):
    gate("after")
    from utils import program_feedback
    program_feedback.render()

with show("after"):
    gate("after")
    from utils import person_detector

    st.divider()
    st.markdown("### :material/groups: Event headcount")
    st.caption(
        "Upload photos from your event and we'll count the people in each one. Photos are analyzed "
        "inside this app and are not stored — only the counts are saved. Wide room shots work best."
    )
    require_sign_in("count attendance from your event photos")

    if st.session_state.get("hc_done"):
        st.success(f"Attendance saved: **{st.session_state['hc_done']}** people. Thank you!")
        if st.button("Count another event", key="hc_again"):
            for k in [k for k in st.session_state if k.startswith("hc_")]:
                del st.session_state[k]
            st.rerun()
        raise SectionDone

    _a, _b, _c = st.columns([2, 1, 1])
    hc_event = _a.text_input("Event name *", max_chars=200, key="hc_event")
    hc_date = _b.date_input("Event date", value=None, key="hc_date")
    hc_city = _c.text_input("City", max_chars=100, key="hc_city")

    hc_files = st.file_uploader(
        "Event photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
        key=f"hc_files_{st.session_state.get('hc_upload_n', 0)}",
    )
    if hc_files and st.button(f"Count people in {len(hc_files)} photo(s)", type="primary", key="hc_run"):
        try:
            session = _hc_detector()
        except Exception as e:
            print(f"[headcount] model load failed: {e}")
            st.error("The people detector couldn't load. Please try again in a minute.")
            raise SectionDone
        results = []
        bar = st.progress(0.0, text="Counting people…")
        for i, f in enumerate(hc_files[:20], 1):
            data = f.getvalue()
            if len(data) > 25 * 1024 * 1024:
                st.warning(f"{f.name}: larger than 25 MB, skipped.")
                continue
            try:
                r = person_detector.count_people(session, data)
                results.append({"name": f.name, "count": r["count"], "confidence": r["confidence"],
                                "preview": _hc_preview(data, r["boxes"])})
            except Exception as e:
                print(f"[headcount] {f.name}: {e}")
                st.warning(f"{f.name}: couldn't read this image.")
            bar.progress(i / min(len(hc_files), 20), text=f"Counting people… {i}/{min(len(hc_files), 20)}")
        if len(hc_files) > 20:
            st.info("Only the first 20 photos were counted.")
        st.session_state["hc_results"] = results
        st.rerun()

    results = st.session_state.get("hc_results") or []
    if results:
        st.markdown("#### Review the counts")
        st.caption("Blue boxes show who was detected. Correct any count that's off "
                   "(e.g. faces on a slide, or people too far away to detect).")
        cols = st.columns(3)
        for i, r in enumerate(results):
            with cols[i % 3]:
                st.image(r["preview"], width="stretch")
                r["final"] = st.number_input(
                    f"{r['name'][:40]} — detected {r['count']}", min_value=0, step=1,
                    value=r["count"], key=f"hc_final_{i}",
                )
        finals = [r["final"] for r in results]
        peak, total = max(finals), sum(finals)
        m1, m2 = st.columns(2)
        m1.metric("Peak photo", peak, help="Highest single-photo count — best headcount estimate")
        m2.metric("Sum of photos", total, help="May double-count people who appear in several photos")
        reported = st.number_input("Attendance to report *", min_value=0, step=1, value=peak, key="hc_reported")

        if st.button("Save attendance", type="primary", key="hc_save"):
            if not hc_event.strip():
                st.error("Please enter the event name above.")
                raise SectionDone
            row = [
                _now(),
                speaker_identity.email,
                hc_event.strip(),
                hc_date.isoformat() if hc_date else "",
                hc_city.strip(),
                len(results),
                sum(r["count"] for r in results),
                peak,
                total,
                int(reported),
                "; ".join(f"{r['name'][:60]}={r['count']}->{r['final']}" for r in results),
            ]
            if append_row(HEADCOUNT_TAB, row):
                st.session_state["hc_done"] = int(reported)
                st.session_state.pop("hc_results", None)
                st.session_state["hc_upload_n"] = st.session_state.get("hc_upload_n", 0) + 1
                st.rerun()
            else:
                st.error("Could not save. Please try again or email aba.micah@snowflake.com.")
