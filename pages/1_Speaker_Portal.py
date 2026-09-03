import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from io import BytesIO
import urllib.parse
import streamlit as st
import pandas as pd
import requests as _requests
from utils.styles import inject_css
from utils.sheets import read_tab, append_row, get_access_token, claim_uber_code, send_gmail
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Speaker Portal — Community Voices",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Detect URL params to auto-select right tab ─────────────────────────────────
params = st.query_params
_speaker_param = params.get("speaker", "")
_event_param   = params.get("event", "")
_talk_param    = params.get("talk", "")

# If audience feedback params present → show feedback tab by default
_audience_mode = bool(_speaker_param and _event_param and _talk_param)

SLOTS_SHEET_ID = "1IgTYK8vV-AhDI3HuYB3KEjN8knRjY66LAOIWF0QT5II"

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Speaker Portal</div>
  <h1>Your Community Voices hub</h1>
  <p>
    Browse available speaking slots, book your travel, explore upcoming events,
    access speaker resources, and generate talk feedback QR codes — all in one place.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Tab order — put Feedback first if audience QR mode ─────────────────────────
if _audience_mode:
    TAB_NAMES = ["⭐ Talk Feedback", "🎤 Available Speaking Slots", "✈️ Book Your Travel", "🚗 Uber Request", "📅 Upcoming Events", "📦 Resources"]
else:
    TAB_NAMES = ["🎤 Available Speaking Slots", "✈️ Book Your Travel", "🚗 Uber Request", "📅 Upcoming Events", "📦 Resources", "⭐ Talk Feedback"]

tabs = st.tabs(TAB_NAMES)

# Map names to tab objects
tab_map       = dict(zip(TAB_NAMES, tabs))
tab_browse    = tab_map.get("🎤 Available Speaking Slots")
tab_travel    = tab_map.get("✈️ Book Your Travel")
tab_uber      = tab_map.get("🚗 Uber Request")
tab_upcoming  = tab_map.get("📅 Upcoming Events")
tab_resources = tab_map.get("📦 Resources")
tab_feedback  = tab_map.get("⭐ Talk Feedback")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: AVAILABLE SPEAKING SLOTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_browse:
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
            return read_tab("Events"), read_tab("Speaker_Requests")
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
            use_container_width=True,
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
                        with c_e: e = st.text_input("Your email", key=f"sp_e_{sheet_row}")
                        sub = st.form_submit_button("Submit interest", type="primary", use_container_width=True)
                    if sub and n and e:
                        write_signup_to_slots(sheet_row, n, e)
                        conf_id = generate_confirmation_id()
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                              type="primary", use_container_width=True)
    else:
        st.info("No open slots found. Check back soon.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: UPCOMING EVENTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_upcoming:
    st.markdown("### Upcoming events")
    st.markdown("All events in the Community Voices programme scheduled from today onwards.")

    @st.cache_data(ttl=300)
    def load_all_events():
        try:
            return read_tab("Events")
        except Exception:
            return pd.DataFrame()

    if st.button("Refresh events", key="refresh_upcoming"):
        st.cache_data.clear(); st.rerun()

    df_all = load_all_events()

    def _parse_event_date(d):
        from datetime import datetime as _dt
        d = str(d).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"):
            try:
                x = _dt.strptime(d, fmt)
                if x.year < 2000: x = x.replace(year=2026)
                return x
            except Exception:
                pass
        return None

    if df_all.empty:
        st.info("No events found. Check back soon.")
    else:
        today = datetime.today()
        # Try common column names for start date
        date_col = next((c for c in df_all.columns if "start" in c.lower() or "date" in c.lower()), None)
        if date_col:
            df_all["_parsed_date"] = df_all[date_col].apply(_parse_event_date)
            upcoming_df = df_all[df_all["_parsed_date"].apply(lambda x: x is not None and x >= today)].copy()
            upcoming_df = upcoming_df.sort_values("_parsed_date").reset_index(drop=True)
        else:
            upcoming_df = df_all.copy()

        if upcoming_df.empty:
            st.info("No upcoming events scheduled yet. Check back soon.")
        else:
            # Build a clean display table from whatever columns exist
            display_cols = [c for c in ["event_name","event_city","event_country","event_date_start","event_date_end","event_type","expected_audience"] if c in upcoming_df.columns]
            if display_cols:
                display_up = upcoming_df[display_cols].copy()
                display_up.columns = [c.replace("event_","").replace("_"," ").title() for c in display_cols]
                st.dataframe(display_up, use_container_width=True, hide_index=True)
            else:
                st.dataframe(upcoming_df.drop(columns=["_parsed_date"], errors="ignore"), use_container_width=True, hide_index=True)

            st.caption(f"{len(upcoming_df)} upcoming event(s)")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: PAST EVENTS
# ══════════════════════════════════════════════════════════════════════════════
# TAB: RESOURCES
# ══════════════════════════════════════════════════════════════════════════════
with tab_resources:
    st.markdown("### Speaker resource hub")
    r_brand, r_talk, r_prep, r_faq = st.tabs(["Brand Kit","Talk Templates","Speaker Prep","FAQ"])

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
            "Request yours by emailing **community@snowflake.com** with subject: "
            "*Slide template request — [Your Name]*",
            icon="📊",
        )
        ca,cb=st.columns(2)
        with ca:
            st.markdown("""<div class="info-card"><h4>Standard Conference Template</h4>
            <p>16:9 dark theme · title slide, about me, agenda, content slides, closing with QR code placeholder.<br>
            <strong>Contact community@snowflake.com to request access.</strong></p></div>""", unsafe_allow_html=True)
        with cb:
            st.markdown("""<div class="info-card"><h4>Lightning Talk Template (15 min)</h4>
            <p>8 slides max · optimised for fast-paced conference sessions and meetup lightning rounds.<br>
            <strong>Contact community@snowflake.com to request access.</strong></p></div>""", unsafe_allow_html=True)
        st.markdown("**Bio format:** 50–100 words · role, company, speciality, community membership, LinkedIn URL")

    with r_prep:
        for phase, items in [
            ("6–8 weeks before",["Submit interest from the Browse Events tab","Confirm session length and A/V with organizers","Register for event (program may cover ticket)"]),
            ("3–4 weeks before",["Draft slides using Snowflake template","Full rehearsal end-to-end","Submit bio and headshot","Generate feedback QR code (Talk Feedback tab)"]),
            ("Day of",["Arrive 30 min early — test A/V and clicker","QR code on last slide","Stay for Q&A"]),
            ("After",["Share slides publicly","Post on social — tag @Snowflake + #SnowflakeCommunity","Review feedback scores from Talk Feedback tab"]),
        ]:
            with st.expander(phase):
                for item in items: st.markdown(f"☐ {item}")
        st.info("To request a **1:1 speaker coaching session**, email community@snowflake.com with subject: *Speaker coaching — [Your Name] — [Event]*")

    with r_faq:
        for q, a in [
            ("How do I sign up to speak?","Browse open slots on the Browse Events tab and click 'I'm interested in this slot'."),
            ("What support can I receive?","Travel booking via Navan, hotel, event registration, swag kit, speaker coaching, and co-promotion on Snowflake social channels."),
            ("How do I book my travel?","Use the Book Your Travel tab and fill in the booking request form. Navan will arrange flights and hotel within 2 business days. You'll also receive an Uber code for local transport."),
            ("Can I sign up for multiple events?","Yes — submit a separate sign-up for each event."),
            ("Do I need approval for slide content?","No pre-approval needed, but follow brand guidelines and don't discuss roadmap or pricing."),
        ]:
            with st.expander(q): st.markdown(a)

# ══════════════════════════════════════════════════════════════════════════════
# TAB: TALK FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════
with tab_feedback:
    if _audience_mode:
        # ── Audience rating mode ──────────────────────────────────────────────
        st.markdown(f"""
        <div class="page-hero" style="background:linear-gradient(135deg,#0E2346,#1B3A6B);">
          <div class="eyebrow">Rate this Talk</div>
          <h1>{_talk_param}</h1>
          <p><strong style="color:#fff;">{_speaker_param}</strong> · {_event_param}</p>
        </div>""", unsafe_allow_html=True)

        if st.session_state.get("sp_fb_done"):
            st.markdown('<div class="success-box"><h2>Thank you!</h2><p>Your feedback helps our community speakers grow.</p></div>', unsafe_allow_html=True)
        else:
            r_overall  = st.slider("Overall rating", 1, 5, 4, format="%d ⭐", key="fb_overall")
            r_content  = st.slider("Content quality", 1, 5, 4, format="%d ⭐", key="fb_content")
            r_delivery = st.slider("Delivery", 1, 5, 4, format="%d ⭐", key="fb_delivery")
            r_relevance= st.slider("Relevance to your work", 1, 5, 4, format="%d ⭐", key="fb_relevance")
            st.markdown("<hr class='divider'>", unsafe_allow_html=True)
            valuable   = st.text_area("Most valuable takeaway?", height=80, key="fb_valuable")
            would_attend = st.radio("Would you attend another talk by this speaker?",["Definitely yes","Probably yes","Not sure","Probably not"], horizontal=True, key="fb_attend")
            c1f,c2f=st.columns(2)
            with c1f: resp_name=st.text_input("Your name (optional)", key="fb_resp_name")
            with c2f: resp_email=st.text_input("Your email (optional)", key="fb_resp_email")
            if st.button("Submit Feedback", type="primary", use_container_width=True, key="fb_submit"):
                import uuid
                row=[str(uuid.uuid4())[:8].upper(),datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     _speaker_param,_event_param,_talk_param,"",
                     str(r_overall),str(r_content),str(r_delivery),str(r_relevance),
                     valuable or "",would_attend,"","",resp_name or "",resp_email or "",""]
                append_row("Talk_Feedback",row)
                st.session_state["sp_fb_done"]=True; st.rerun()
    else:
        # ── Speaker: generate QR code ─────────────────────────────────────────
        st.markdown("### Generate your talk feedback QR code")
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
                    st.image(buf,use_container_width=True)
                    st.download_button("Download QR PNG",data=buf.getvalue(),
                        file_name=f"feedback-{spk_name.replace(' ','-').lower()}.png",
                        mime="image/png",use_container_width=True)
                with ci2:
                    st.markdown(f"""
                    <div class="info-card"><h4>Shareable link</h4>
                    <p style="word-break:break-all;font-size:0.82rem;font-family:monospace;">{fb_url}</p></div>
                    <div class="info-card"><h4>How to use</h4>
                    <p>1. Download the QR PNG<br>2. Add to your last slide<br>
                    3. Or paste link in event chat<br>4. Audience scans → 30-sec rating form</p></div>""", unsafe_allow_html=True)
            except ImportError:
                st.error("Run: pip install qrcode[pil] Pillow")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: BOOK YOUR TRAVEL
# ══════════════════════════════════════════════════════════════════════════════
with tab_travel:
    st.markdown("### Book your travel")
    st.markdown(
        "Fill in this form and our travel partner **Navan** will book your flights and hotel. "
        "You'll receive your confirmed itinerary by email within **2 business days**."
    )

    if st.session_state.get("sp_travel_done"):
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
            st.markdown('<div class="success-box"><h2>Travel request received!</h2><p>Navan will arrange your flights and hotel and send your itinerary within 2 business days.</p><p style="color:#E53E3E;"><strong>No Uber codes available right now.</strong> Contact community@snowflake.com to receive one.</p></div>', unsafe_allow_html=True)
        if st.button("Submit another travel request", key="sp_travel_reset"):
            st.session_state.pop("sp_travel_done", None)
            st.session_state.pop("sp_travel_uber_code", None)
            st.rerun()
        st.stop()

    # ── Section 1: Personal details ───────────────────────────────────
    st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Personal details</div>', unsafe_allow_html=True)
    pd1, pd2 = st.columns(2)
    with pd1:
        tv_email = st.text_input("Your email *", key="tv_email")
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

    if st.button("Submit Travel Request", type="primary", use_container_width=True,
                 disabled=not required_ok, key="tv_submit"):
        import uuid
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            # Notify Navan team + Aba
            send_gmail(
                ["navan-team@snowflake.com", "aba.micah@snowflake.com"],
                f"New Travel Request — {passport_name} — {tv_event_name} ({tv_event_city})",
                f"""<div style="font-family:Inter,Arial,sans-serif;max-width:600px;">
                <h2 style="color:#0E2346;">New Speaker Travel Request</h2>
                <p>A Community Voices speaker has submitted a travel booking request.</p>
                <table style="border-collapse:collapse;width:100%;margin:16px 0;">
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Traveler</td><td style="padding:8px;border:1px solid #E2E8F0;">{passport_name}</td></tr>
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Email</td><td style="padding:8px;border:1px solid #E2E8F0;">{tv_email.strip()}</td></tr>
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Event</td><td style="padding:8px;border:1px solid #E2E8F0;">{tv_event_name} — {tv_event_city}</td></tr>
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Event date</td><td style="padding:8px;border:1px solid #E2E8F0;">{tv_event_date}</td></tr>
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Flights</td><td style="padding:8px;border:1px solid #E2E8F0;">{fly_from} → {fly_to}<br>{outbound_date} — {return_date} ({seat_class})</td></tr>
                <tr><td style="padding:8px;border:1px solid #E2E8F0;font-weight:600;background:#F7FAFC;">Hotel</td><td style="padding:8px;border:1px solid #E2E8F0;">{hotel_checkin} → {hotel_checkout} ({hotel_pref})</td></tr>
                </table>
                <p><a href="https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/Navan_Portal" style="display:inline-block;padding:10px 24px;background:#29B5E8;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">Open Navan Portal →</a></p>
                <p style="color:#718096;font-size:0.85rem;">This is an automated notification from the Community Voices platform.</p>
                </div>""",
            )
            st.session_state["sp_travel_done"] = True
            st.session_state["sp_travel_uber_code"] = uber_code or ""
            st.rerun()
        else:
            st.error("Could not save. Please try again or email community@snowflake.com.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: UBER REQUEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_uber:
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
            st.markdown('<div class="success-box"><h2>Uber request submitted!</h2><p style="color:#E53E3E;"><strong>No Uber codes available right now.</strong> Contact community@snowflake.com to receive one.</p></div>', unsafe_allow_html=True)
        if st.button("Submit another request", key="sp_uber_reset"):
            st.session_state.pop("sp_uber_done", None)
            st.session_state.pop("sp_uber_code", None)
            st.rerun()
        st.stop()

    st.markdown("**Your details**")
    ub1, ub2 = st.columns(2)
    with ub1: ub_email = st.text_input("Your email *", key="ub_email")
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
            min_value=5, max_value=500, step=5, value=40, key="ub_amount")
    ub_notes = st.text_area(
        "Notes (pickup/dropoff locations, special requirements)",
        height=80, placeholder="Pickup: hotel downtown -> drop-off: venue address...",
        key="ub_notes")

    st.info(
        "Standard Uber gift card allowance is **$40 per event** (round trip). "
        "Requests above $40 require a brief note explaining the need.",
        icon="💳",
    )

    ub_required = all([ub_email, ub_name, ub_event, ub_city, ub_event_date])
    if not ub_required:
        st.caption("Complete all required fields (*) to submit.")

    if st.button("Submit Uber Request", type="primary", use_container_width=True,
                 disabled=not ub_required, key="ub_submit"):
        import uuid
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
