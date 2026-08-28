import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from io import BytesIO
import urllib.parse
import streamlit as st
import pandas as pd
import requests as _requests
from utils.styles import inject_css
from utils.sheets import read_tab, append_row, get_access_token
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
_prefill_event_id      = params.get("event_id", "")
_prefill_event_name    = params.get("event_name", "")
_prefill_event_city    = params.get("event_city", "")
_prefill_event_country = params.get("event_country", "")
_prefill_event_start   = params.get("event_start", "")

# If audience feedback params present → show feedback tab by default
_audience_mode = bool(_speaker_param and _event_param and _talk_param)
_apply_mode    = bool(_prefill_event_name)

SLOTS_SHEET_ID = "1IgTYK8vV-AhDI3HuYB3KEjN8knRjY66LAOIWF0QT5II"

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Speaker Portal</div>
  <h1>Your Community Voices hub</h1>
  <p>
    Browse open speaking slots, submit your application, check your status,
    access resources, and generate talk feedback QR codes — all in one place.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Tab order — put Feedback first if audience QR mode, Apply first if applying ─
if _audience_mode:
    TAB_NAMES = ["⭐ Talk Feedback", "📅 Browse Events", "📝 Apply", "🔍 My Status", "📦 Resources", "✈️ My Travel", "🚗 Uber Request"]
elif _apply_mode:
    TAB_NAMES = ["📝 Apply", "📅 Browse Events", "🔍 My Status", "📦 Resources", "⭐ Talk Feedback", "✈️ My Travel", "🚗 Uber Request"]
else:
    TAB_NAMES = ["📅 Browse Events", "📝 Apply", "🔍 My Status", "📦 Resources", "⭐ Talk Feedback", "✈️ My Travel", "🚗 Uber Request"]

tabs = st.tabs(TAB_NAMES)

# Map names to tab objects
tab_map = dict(zip(TAB_NAMES, tabs))
tab_browse   = tab_map.get("📅 Browse Events")
tab_apply    = tab_map.get("📝 Apply")
tab_status   = tab_map.get("🔍 My Status")
tab_resources= tab_map.get("📦 Resources")
tab_feedback = tab_map.get("⭐ Talk Feedback")
tab_travel   = tab_map.get("✈️ My Travel")
tab_uber     = tab_map.get("🚗 Uber Request")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: BROWSE EVENTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_browse:
    st.markdown("### Open speaking slots")
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

        st.markdown(f"**{len(filtered)} open slot(s)**")

        for partner, group in filtered.groupby("Partner"):
            st.markdown(f"**{partner}**")
            cols = st.columns(3, gap="medium")
            for ci, (_, slot) in enumerate(group.iterrows()):
                city=slot["City"]; ev_date=slot["Date"]; region=slot["Region"]
                sheet_row=int(slot["_sheet_row"]); claimed=slot["Interested_Name"].strip()
                bg, accent = REGION_COLORS.get(region, ("#F7FAFC","#4A5568"))
                with cols[ci%3]:
                    st.markdown(f"""
                    <div style="background:{bg};border:1px solid {accent}40;border-radius:12px;
                                 padding:18px 20px;margin-bottom:8px;">
                      <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
                        <span style="font-size:0.7rem;font-weight:700;padding:2px 10px;border-radius:20px;
                               background:{accent}20;color:{accent};border:1px solid {accent}40;">{region}</span>
                        <span style="font-size:0.7rem;color:#A0AEC0;">{partner}</span>
                      </div>
                      <div style="font-size:1.1rem;font-weight:700;color:#0E2346;">{city}</div>
                      <div style="font-size:0.88rem;color:#4A5568;margin-top:2px;">📅 {ev_date}</div>
                      {"<div style='font-size:0.78rem;color:#718096;margin-top:4px;'>Interested: " + claimed + "</div>" if claimed else ""}
                    </div>
                    """, unsafe_allow_html=True)

                    key_open=f"sp_open_{sheet_row}"; key_done=f"sp_done_{sheet_row}"
                    if st.session_state.get(key_done):
                        st.success("You're on the list!", icon="✅")
                        cid_val=st.session_state.get(f"sp_cid_{sheet_row}","")
                        if cid_val:
                            st.markdown(f"<div class='id-box' style='padding:8px 12px;margin:4px 0;'><div class='label' style='font-size:0.65rem;'>Your ID</div><div class='id' style='font-size:0.9rem;'>{cid_val}</div></div>", unsafe_allow_html=True)
                    elif st.session_state.get(key_open):
                        with st.form(key=f"sp_form_{sheet_row}"):
                            n = st.text_input("Your name", key=f"sp_n_{sheet_row}")
                            e = st.text_input("Your email", key=f"sp_e_{sheet_row}")
                            sub = st.form_submit_button("Submit", type="primary", use_container_width=True)
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
                        st.button("I'm interested", key=f"sp_btn_{sheet_row}",
                                  on_click=lambda k=key_open: st.session_state.update({k:True}),
                                  use_container_width=True)
            st.markdown("<br>", unsafe_allow_html=True)
    else:
        st.info("No open slots found. Check back soon.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: APPLY
# ══════════════════════════════════════════════════════════════════════════════
with tab_apply:
    if st.session_state.get("sp_applied"):
        cid = st.session_state.get("sp_conf_id","")
        st.markdown(f"""
        <div class="success-box"><h2>Application submitted!</h2>
        <p>Save your Confirmation ID — use it on the My Status tab to track progress.</p></div>
        <div class="id-box" style="margin-top:24px;"><div class="label">Confirmation ID</div>
        <div class="id">{cid}</div></div>""", unsafe_allow_html=True)
        if st.button("Submit another", key="sp_another"):
            st.session_state.pop("sp_applied",None); st.session_state.pop("sp_conf_id",None); st.rerun()
        st.stop()

    if _prefill_event_name:
        st.success(f"Applying for **{_prefill_event_name}** in {_prefill_event_city}, {_prefill_event_country}. Event details pre-filled below.", icon="📅")

    st.markdown('<div class="step-label">Section 1 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">About You</div>', unsafe_allow_html=True)
    c1,c2=st.columns(2)
    with c1: fname=st.text_input("First name *", placeholder="Ada", key="sp_fname")
    with c2: lname=st.text_input("Last name *", placeholder="Lovelace", key="sp_lname")
    c3,c4=st.columns(2)
    with c3: email=st.text_input("Email address *", placeholder="ada@example.com", key="sp_email")
    with c4: job=st.text_input("Job title *", placeholder="Senior Data Engineer", key="sp_job")
    c5,c6=st.columns(2)
    with c5: company=st.text_input("Company", key="sp_company")
    with c6: linkedin=st.text_input("LinkedIn URL", placeholder="https://linkedin.com/in/...", key="sp_linkedin")
    c7,c8=st.columns(2)
    with c7: country=st.text_input("Country *", key="sp_country")
    with c8: city=st.text_input("City", key="sp_city")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    st.markdown('<div class="step-label">Section 2 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Community Identity</div>', unsafe_allow_html=True)
    community=st.selectbox("Community role *",["Select...","Data Superhero","Snowflake Squad Member","Streamlit Creator","Open Source Contributor","Independent Practitioner / Builder","Other"], key="sp_community")
    years=st.select_slider("Years with Snowflake",["< 1 year","1 year","2 years","3 years","4 years","5+ years"],value="2 years",key="sp_years")
    bio=st.text_area("Short bio (2–4 sentences) *", height=90, key="sp_bio")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    st.markdown('<div class="step-label">Section 3 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">The Event</div>', unsafe_allow_html=True)
    ev_name=st.text_input("Event name *", value=_prefill_event_name, placeholder="Data + AI Summit, PyData Global...", key="sp_evname")
    ev_website=st.text_input("Event website", key="sp_evweb")
    c9,c10=st.columns(2)
    with c9:
        _sv = date.today()
        if _prefill_event_start:
            try:
                from datetime import datetime as _dt
                _sv = _dt.strptime(_prefill_event_start[:10],"%Y-%m-%d").date()
                if _sv < date.today(): _sv = date.today()
            except Exception: pass
        ev_start=st.date_input("Event start date *", value=_sv, min_value=date.today(), key="sp_evstart")
    with c10: ev_end=st.date_input("Event end date", min_value=date.today(), key="sp_evend")
    c11,c12=st.columns(2)
    with c11: ev_city=st.text_input("Event city *", value=_prefill_event_city, key="sp_evcity")
    with c12: ev_country=st.text_input("Event country *", value=_prefill_event_country, key="sp_evcountry")
    ev_type=st.selectbox("Event type *",["Select...","In-person conference","Hybrid conference","Virtual conference","Community meetup (in-person)","Community meetup (virtual)","University / academic talk","Other"], key="sp_evtype")
    ev_audience=st.select_slider("Expected audience",["< 50","50–200","200–500","500–1,000","1,000–5,000","5,000+"],value="200–500",key="sp_audience")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    st.markdown('<div class="step-label">Section 4 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Your Talk</div>', unsafe_allow_html=True)
    talk_title=st.text_input("Talk title *", key="sp_talktitle")
    talk_abstract=st.text_area("Abstract (2–5 sentences) *", height=100, key="sp_abstract")
    c13,c14=st.columns(2)
    with c13: session_type=st.selectbox("Format *",["Select...","Conference talk (30–45 min)","Lightning talk (5–15 min)","Workshop","Panel","Keynote","Demo"], key="sp_format")
    with c14: aud_level=st.selectbox("Technical level",["Select...","Beginner","Intermediate","Advanced","Mixed"], key="sp_level")
    topics=st.multiselect("Snowflake topics",["Data Engineering / Pipelines","Snowpark / Python","Cortex AI / LLMs","Streamlit","Data Sharing","Cost Optimization","ML / MLOps","Iceberg","Dynamic Tables","Other"], key="sp_topics")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    st.markdown('<div class="step-label">Section 5 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Support Request</div>', unsafe_allow_html=True)
    support=st.multiselect("Support types *",["Travel grant (flights)","Hotel / accommodation","Conference registration fee","Snowflake swag kit","Speaker coaching session","Co-promotion on Snowflake channels","Speaker certification badge","No support needed"], key="sp_support")
    fly_from=st.text_input("Traveling from", placeholder="London, UK", key="sp_flyfrom")
    cost=st.number_input("Estimated travel cost (USD)", min_value=0, max_value=10000, step=50, value=0, key="sp_cost")
    notes=st.text_area("Additional notes", height=80, key="sp_notes")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    ok = all([fname,lname,email,job,country,community!="Select...",bio,ev_name,ev_city,ev_country,
              ev_type!="Select...",talk_title,talk_abstract,session_type!="Select...",support])
    if not ok: st.caption("Complete all required fields to submit.")
    if st.button("Submit Application", type="primary", use_container_width=True, disabled=not ok, key="sp_submit"):
        conf_id=generate_confirmation_id()
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row=[conf_id,now,"Pending",fname,lname,email,job,company or "",linkedin or "",country,city or "",
             community,years,bio,ev_name,ev_website or "",str(ev_start),str(ev_end),ev_city,ev_country,
             ev_type,ev_audience,talk_title,talk_abstract,session_type,
             aud_level if aud_level!="Select..." else "","", ", ".join(topics),
             ", ".join(support),fly_from or "",str(cost),notes or "","",_prefill_event_id]
        if append_row("Speaker_Applications",row):
            st.session_state["sp_applied"]=True; st.session_state["sp_conf_id"]=conf_id; st.rerun()
        else:
            st.error("Submission failed. Please try again or email community@snowflake.com.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: MY STATUS
# ══════════════════════════════════════════════════════════════════════════════
with tab_status:
    st.markdown("### Check your application status")
    st.markdown("Enter the email and Confirmation ID from your application.")
    with st.form("sp_status_form"):
        s_email=st.text_input("Email address", key="sp_s_email")
        s_cid=st.text_input("Confirmation ID", placeholder="CV-2026-XXXXXXXX", key="sp_s_cid").strip().upper()
        s_submit=st.form_submit_button("Check Status", type="primary", use_container_width=True)

    if s_submit:
        if not s_email or not s_cid:
            st.warning("Please enter both your email and Confirmation ID.")
        else:
            with st.spinner("Looking up..."):
                try:
                    df=read_tab("Speaker_Applications")
                except Exception as ex:
                    st.error(f"Could not reach database: {ex}"); st.stop()
            if df.empty or "confirmation_id" not in df.columns:
                st.info("No applications found."); st.stop()
            match=df[(df["confirmation_id"].str.strip().str.upper()==s_cid) &
                     (df["email"].str.strip().str.lower()==s_email.strip().lower())]
            if match.empty:
                st.error("No application found with that email and ID. Double-check both.")
            else:
                r=match.iloc[0]
                status=r.get("status","Pending")
                STATUS_STYLES={"Pending":("status-pending","⏳ Under Review"),
                               "Approved":("status-approved","✅ Approved"),
                               "Waitlisted":("status-waitlisted","📋 Waitlisted"),
                               "Not a Fit":("status-not-a-fit","❌ Not a Fit")}
                bcls, blbl = STATUS_STYLES.get(status,("status-pending",status))
                st.markdown(f"""
                <div class="info-card" style="border-color:#29B5E8;">
                  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
                    <span class="status-badge {bcls}">{blbl}</span>
                    <span style="font-size:0.85rem;color:#718096;">ID: <strong>{r.get('confirmation_id','')}</strong></span>
                  </div>
                  <h4>{r.get('talk_title','Your Talk')}</h4>
                  <p>{r.get('event_name','')} · {r.get('event_city','')}, {r.get('event_country','')}</p>
                  <p style="color:#718096;font-size:0.82rem;">Submitted: {r.get('submitted_at','')}</p>
                </div>""", unsafe_allow_html=True)
                if status=="Approved":
                    st.success("Your application is approved! Check your email for next steps.", icon="✅")
                elif status=="Pending":
                    st.info("Under review — we aim to respond within 5 business days.", icon="⏳")
                elif status=="Waitlisted":
                    st.warning("You're on the waitlist. We'll reach out if a spot opens.", icon="📋")
                elif status=="Not a Fit":
                    st.error("Not a match for this cycle — feel free to apply for a future event.", icon="❌")
                admin_note=r.get("admin_notes","")
                if admin_note and str(admin_note).strip():
                    st.info(f"Note from the team: {admin_note}")

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
            <p><a href="https://www.snowflake.com/wp-content/themes/snowflake/assets/img/brand-guidelines/snowflake-logo-blue.png" target="_blank" style="color:#29B5E8;">Logo (blue, PNG)</a><br>
            <a href="https://www.snowflake.com/wp-content/themes/snowflake/assets/img/brand-guidelines/snowflake-logo-white.png" target="_blank" style="color:#29B5E8;">Logo (white, PNG)</a></p></div>""", unsafe_allow_html=True)
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
        ca,cb=st.columns(2)
        with ca:
            st.markdown("""<div class="info-card"><h4>Standard Conference Template</h4>
            <p>16:9 dark theme · title, about me, agenda, content, closing.<br>
            <a href="https://docs.google.com/presentation/d/1Vc2H4tF0Ox9v7vK8Gm2K3E4rN1wqjYpLDskBH7mNUs/edit?usp=sharing" target="_blank" style="color:#29B5E8;">Open in Google Slides →</a></p></div>""", unsafe_allow_html=True)
        with cb:
            st.markdown("""<div class="info-card"><h4>Lightning Talk Template (15 min)</h4>
            <p>8 slides max for fast-paced sessions.<br>
            <a href="https://docs.google.com/presentation/d/1Vc2H4tF0Ox9v7vK8Gm2K3E4rN1wqjYpLDskBH7mNUs/edit?usp=sharing" target="_blank" style="color:#29B5E8;">Open in Google Slides →</a></p></div>""", unsafe_allow_html=True)
        st.markdown("**Bio format:** 50–100 words · role, company, speciality, community membership, LinkedIn URL")

    with r_prep:
        for phase, items in [
            ("6–8 weeks before",["Submit Community Voices application","Confirm session length and A/V with organizers","Register for event (program may cover ticket)"]),
            ("3–4 weeks before",["Draft slides using Snowflake template","Full rehearsal end-to-end","Submit bio and headshot","Generate feedback QR code (Talk Feedback tab)"]),
            ("Day of",["Arrive 30 min early — test A/V and clicker","QR code on last slide","Stay for Q&A"]),
            ("After",["Share slides publicly","Post on social — tag @Snowflake + #SnowflakeCommunity","Review feedback scores on My Status tab"]),
        ]:
            with st.expander(phase):
                for item in items: st.markdown(f"☐ {item}")
        st.info("To request a **1:1 speaker coaching session**, email community@snowflake.com with subject: *Speaker coaching — [Your Name] — [Event]*")

    with r_faq:
        for q, a in [
            ("How long does review take?","We aim to respond within 5 business days. Use My Status to track."),
            ("What support can I receive?","Travel grant, hotel, event registration, swag kit, speaker coaching, co-promotion on Snowflake social."),
            ("Can I apply for an event that already happened?","No — applications must be submitted before the event date."),
            ("Can I apply for multiple events?","Yes — submit a separate application for each. Each gets its own Confirmation ID."),
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
# TAB: MY TRAVEL — upload flight/hotel details
# ══════════════════════════════════════════════════════════════════════════════
with tab_travel:
    st.markdown("### Submit your travel details")
    st.markdown(
        "Once your travel is booked (by you or Navan), submit your flight and hotel details here. "
        "This helps the program team track logistics and appears in the Navan portal for confirmation."
    )

    if st.session_state.get("sp_travel_done"):
        st.markdown('<div class="success-box"><h2>Travel details saved!</h2><p>The program team can now see your itinerary in the Navan portal.</p></div>', unsafe_allow_html=True)
        if st.button("Update my travel details", key="sp_travel_reset"):
            st.session_state.pop("sp_travel_done", None); st.rerun()
        st.stop()

    st.markdown("**Verify your identity first**")
    tv1, tv2 = st.columns(2)
    with tv1: tv_email = st.text_input("Your email", key="tv_email")
    with tv2: tv_cid   = st.text_input("Confirmation ID", placeholder="CV-2026-XXXXXXXX", key="tv_cid")

    if tv_email and tv_cid:
        # Verify speaker exists and is approved
        try:
            df_verify = read_tab("Speaker_Applications")
        except Exception:
            df_verify = pd.DataFrame()

        match = pd.DataFrame()
        if not df_verify.empty and "confirmation_id" in df_verify.columns:
            match = df_verify[
                (df_verify["confirmation_id"].str.strip().str.upper() == tv_cid.strip().upper()) &
                (df_verify["email"].str.strip().str.lower() == tv_email.strip().lower())
            ]

        if match.empty:
            st.warning("No matching application found. Double-check your email and Confirmation ID.")
        else:
            spk_row = match.iloc[0]
            ev_name  = spk_row.get("event_name", "")
            ev_city  = spk_row.get("event_city", "")
            ev_date  = spk_row.get("event_date_start", "")
            spk_name = f"{spk_row.get('first_name','')} {spk_row.get('last_name','')}".strip()

            st.success(f"Verified: **{spk_name}** — {ev_name} in {ev_city}")
            st.markdown("<hr class='divider'>", unsafe_allow_html=True)

            st.markdown("#### Outbound flight")
            tf1, tf2 = st.columns(2)
            with tf1: airline   = st.text_input("Airline", placeholder="Delta, British Airways...", key="tv_airline")
            with tf2: flight_no = st.text_input("Flight number", placeholder="DL1234", key="tv_fno")
            tf3, tf4 = st.columns(2)
            with tf3: dep_city  = st.text_input("Departing from", placeholder="London LHR", key="tv_dep")
            with tf4: dep_dt    = st.text_input("Departure date & time", placeholder="2026-09-10 08:30", key="tv_depdt")
            tf5, tf6 = st.columns(2)
            with tf5: arr_city  = st.text_input("Arriving at", placeholder="Berlin TXL", key="tv_arr")
            with tf6: arr_dt    = st.text_input("Arrival date & time", placeholder="2026-09-10 11:45", key="tv_arrdt")

            st.markdown("#### Return flight")
            tr1, tr2 = st.columns(2)
            with tr1: ret_fno   = st.text_input("Return flight number", placeholder="DL5678", key="tv_rfno")
            with tr2: ret_dep   = st.text_input("Return departure date & time", placeholder="2026-09-11 14:00", key="tv_rdep")
            ret_arr = st.text_input("Return arrival date & time", placeholder="2026-09-11 16:30", key="tv_rarr")

            st.markdown("#### Hotel")
            th1, th2 = st.columns(2)
            with th1: hotel_name    = st.text_input("Hotel name", key="tv_hotel")
            with th2: hotel_address = st.text_input("Hotel address", key="tv_hadd")
            th3, th4 = st.columns(2)
            with th3: hotel_in  = st.text_input("Check-in date", placeholder="2026-09-09", key="tv_cin")
            with th4: hotel_out = st.text_input("Check-out date", placeholder="2026-09-12", key="tv_cout")

            total_cost = st.number_input("Total travel cost (USD)", min_value=0, max_value=20000, step=50, key="tv_cost")
            tv_notes   = st.text_area("Anything else for the travel team?", height=70, key="tv_notes")

            if st.button("Submit Travel Details", type="primary", use_container_width=True, key="tv_submit"):
                import uuid
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row = [
                    str(uuid.uuid4())[:8].upper(), now,
                    tv_cid.strip().upper(), spk_name, tv_email.strip(),
                    ev_name, ev_city, ev_date,
                    airline, flight_no, dep_city, dep_dt, arr_city, arr_dt,
                    ret_fno, ret_dep, ret_arr,
                    hotel_name, hotel_address, hotel_in, hotel_out,
                    str(total_cost), "Pending Booking", tv_notes or "",
                ]
                if append_row("Travel_Details", row):
                    st.session_state["sp_travel_done"] = True; st.rerun()
                else:
                    st.error("Could not save. Please try again or email community@snowflake.com.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: UBER REQUEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_uber:
    st.markdown("### Request an Uber gift card")
    st.markdown(
        "Approved speakers can request an Uber gift card for local transport to and from the event venue. "
        "Requests are reviewed within 2 business days and the gift card is sent to your email."
    )

    if st.session_state.get("sp_uber_done"):
        st.markdown('<div class="success-box"><h2>Uber request submitted!</h2><p>You\'ll receive the gift card link at your email within 2 business days.</p></div>', unsafe_allow_html=True)
        if st.button("Submit another request", key="sp_uber_reset"):
            st.session_state.pop("sp_uber_done", None); st.rerun()
        st.stop()

    st.markdown("**Verify your identity first**")
    ub1, ub2 = st.columns(2)
    with ub1: ub_email = st.text_input("Your email", key="ub_email")
    with ub2: ub_cid   = st.text_input("Confirmation ID", placeholder="CV-2026-XXXXXXXX", key="ub_cid")

    if ub_email and ub_cid:
        try: df_verify_u = read_tab("Speaker_Applications")
        except Exception: df_verify_u = pd.DataFrame()

        match_u = pd.DataFrame()
        if not df_verify_u.empty and "confirmation_id" in df_verify_u.columns:
            match_u = df_verify_u[
                (df_verify_u["confirmation_id"].str.strip().str.upper() == ub_cid.strip().upper()) &
                (df_verify_u["email"].str.strip().str.lower() == ub_email.strip().lower())
            ]

        if match_u.empty:
            st.warning("No matching application found.")
        elif match_u.iloc[0].get("status","") != "Approved":
            st.warning("Uber requests are available to **Approved** speakers only. Check your status on the My Status tab.")
        else:
            spk_u = match_u.iloc[0]
            spk_name_u = f"{spk_u.get('first_name','')} {spk_u.get('last_name','')}".strip()
            ev_name_u  = spk_u.get("event_name","")
            ev_city_u  = spk_u.get("event_city","")
            ev_date_u  = spk_u.get("event_date_start","")

            st.success(f"Verified: **{spk_name_u}** — {ev_name_u} in {ev_city_u}")
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
                height=80, placeholder="Pickup: hotel downtown → drop-off: venue address...",
                key="ub_notes")

            st.info(
                "Standard Uber gift card allowance is **$40 per event** (round trip). "
                "Requests above $40 require a brief note explaining the need.",
                icon="💳",
            )

            if st.button("Submit Uber Request", type="primary", use_container_width=True, key="ub_submit"):
                import uuid
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row = [
                    str(uuid.uuid4())[:8].upper(), now,
                    ub_cid.strip().upper(), spk_name_u, ub_email.strip(),
                    ev_name_u, ev_city_u, ev_date_u,
                    rides, str(amount), ub_notes or "", "Pending",
                ]
                if append_row("Uber_Requests", row):
                    st.session_state["sp_uber_done"] = True; st.rerun()
                else:
                    st.error("Could not submit. Please try again.")
