import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from io import StringIO
import streamlit as st
import pandas as pd
import requests as _requests
from utils.styles import inject_css
from utils.sheets import append_row, read_tab, get_access_token
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Vendor Portal — Community Voices",
    page_icon="🏟️",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

st.markdown("""
<div class="page-hero" style="background:linear-gradient(135deg,#44337A 0%,#6B46C1 100%);">
  <div class="eyebrow">Vendor &amp; Event Organizer Portal</div>
  <h1>Register your event</h1>
  <p>
    Register a single event or upload multiple events at once.
    Once approved, your event will appear on the public Events Board and
    qualified community speakers can apply directly.
  </p>
</div>
""", unsafe_allow_html=True)

tab_single, tab_bulk, tab_mine = st.tabs([
    "Register Single Event",
    "Bulk Upload (CSV / Excel / Google Sheets)",
    "My Submissions",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: SINGLE EVENT FORM
# ══════════════════════════════════════════════════════════════════════════════
with tab_single:
    if st.session_state.get("vnd_submitted"):
        eid=st.session_state.get("vnd_eid","")
        st.markdown(f"""<div class="success-box"><h2>Event registered!</h2>
        <p>The Community Voices team will review and be in touch within 5 business days.</p></div>
        <div class="id-box" style="margin-top:24px;"><div class="label">Event Reference ID</div>
        <div class="id">{eid}</div></div>""", unsafe_allow_html=True)
        st.info("Save this ID — reference it in any follow-up emails.", icon="📋")
        if st.button("Register another event", key="vnd_another"):
            st.session_state.pop("vnd_submitted",None); st.session_state.pop("vnd_eid",None); st.rerun()
        st.stop()

    # Section 1
    st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">About You (Organizer)</div>', unsafe_allow_html=True)
    c1,c2=st.columns(2)
    with c1: org_name=st.text_input("Your full name *", key="vnd_name")
    with c2: org_email=st.text_input("Email address *", key="vnd_email")
    c3,c4=st.columns(2)
    with c3: org_org=st.text_input("Organization *", key="vnd_org")
    with c4: org_role=st.text_input("Your role", key="vnd_role")
    org_web=st.text_input("Organization website", key="vnd_web")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # Section 2
    st.markdown('<div class="step-label">Section 2 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Event Details</div>', unsafe_allow_html=True)
    ev_name=st.text_input("Event name *", key="vnd_evname")
    ev_web=st.text_input("Event website *", key="vnd_evweb")
    c5,c6=st.columns(2)
    with c5: ev_start=st.date_input("Start date *", min_value=date.today(), key="vnd_start")
    with c6: ev_end=st.date_input("End date", min_value=date.today(), key="vnd_end")
    c7,c8=st.columns(2)
    with c7: ev_city=st.text_input("City *", key="vnd_city")
    with c8: ev_country=st.text_input("Country *", key="vnd_country")
    ev_fmt=st.selectbox("Format *",["Select...","In-person conference","Hybrid conference","Virtual conference","Community meetup (in-person)","Community meetup (virtual)","University / academic","Other"], key="vnd_fmt")
    ev_audience=st.select_slider("Expected attendance",["< 50","50–200","200–500","500–1,000","1,000–5,000","5,000+"],value="200–500",key="vnd_audience")
    ev_align=st.multiselect("Primary audience",["Data Engineers","Analytics Engineers","Data Scientists / ML","Software Developers","Data Analysts","Data Leaders","AI / GenAI Builders","Open Source Community","Academic / Student"], key="vnd_align")
    ev_desc=st.text_area("Describe your event *", height=100, key="vnd_desc")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # Section 3
    st.markdown('<div class="step-label">Section 3 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Speaker Request</div>', unsafe_allow_html=True)
    spk_topic=st.text_area("Topic you'd like a speaker on *", height=90, key="vnd_topic")
    topic_tags=st.multiselect("Topic tags",["Data Engineering","Snowpark / Python","Cortex AI / LLMs","Streamlit","Data Sharing","Cost Optimization","ML / MLOps","Iceberg","Dynamic Tables","Other"], key="vnd_tags")
    c9,c10=st.columns(2)
    with c9: spk_fmt=st.selectbox("Session format",["Select...","Conference talk (30–45 min)","Lightning talk","Workshop","Panel","Keynote"], key="vnd_spkfmt")
    with c10: spk_level=st.selectbox("Technical level",["No preference","Beginner","Intermediate","Advanced"], key="vnd_level")
    cfp_link=st.text_input("CFP link (if applicable)", key="vnd_cfp")
    cfp_deadline=st.date_input("CFP deadline", min_value=date.today(), value=None, key="vnd_deadline")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # Section 4
    st.markdown('<div class="step-label">Section 4 of 4</div>', unsafe_allow_html=True)
    how_heard=st.selectbox("How did you hear about Community Voices?",["Select...","Snowflake website","Social media","Word of mouth","Previous Snowflake speaker","Snowflake team member","Other"], key="vnd_heard")
    add_notes=st.text_area("Additional notes", height=80, key="vnd_notes")
    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    ok=all([org_name,org_email,org_org,ev_name,ev_web,ev_city,ev_country,
            ev_fmt!="Select...",ev_desc,spk_topic])
    if not ok: st.caption("Complete all required fields to submit.")
    if st.button("Register Event & Request Speaker", type="primary", use_container_width=True, disabled=not ok, key="vnd_submit"):
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eid=generate_confirmation_id().replace("CV-","EV-")
        rid=generate_confirmation_id().replace("CV-","SR-")
        ev_row=[eid,now,"Pending",org_name,org_email,org_org,org_role or "",org_web or "",
                ev_name,ev_web,str(ev_start),str(ev_end),ev_city,ev_country,ev_fmt,ev_audience,
                ", ".join(ev_align),ev_desc,how_heard if how_heard!="Select..." else "",
                add_notes or "",""]
        req_row=[rid,now,"Pending",eid,ev_name,spk_topic,", ".join(topic_tags),
                 spk_fmt if spk_fmt!="Select..." else "",spk_level,cfp_link or "",
                 str(cfp_deadline) if cfp_deadline else "","",""]
        ok1=append_row("Events",ev_row); ok2=append_row("Speaker_Requests",req_row)
        if ok1 and ok2:
            st.session_state["vnd_submitted"]=True; st.session_state["vnd_eid"]=eid; st.rerun()
        else:
            st.error("Submission failed. Please try again or email community@snowflake.com.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: BULK UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_bulk:
    if st.session_state.get("vnd_bulk_done"):
        n=st.session_state.get("vnd_bulk_n",0)
        st.markdown(f'<div class="success-box"><h2>{n} event(s) submitted!</h2><p>The team will review within 5 business days.</p></div>', unsafe_allow_html=True)
        if st.button("Upload another batch", key="vnd_bulk_reset"):
            st.session_state.pop("vnd_bulk_done",None); st.session_state.pop("vnd_bulk_n",None); st.rerun()
        st.stop()

    st.markdown("### Upload multiple events at once")
    TEMPLATE_COLS=["organizer_name","organizer_email","organizer_org","event_name","event_website",
                   "event_start","event_end","event_city","event_country","event_format","expected_audience",
                   "event_description","speaker_topic","topic_tags","session_format","cfp_link","cfp_deadline","notes"]
    st.download_button("Download CSV template",
        data=pd.DataFrame(columns=TEMPLATE_COLS).to_csv(index=False),
        file_name="cv_events_template.csv", mime="text/csv", key="vnd_tpl")

    st.markdown("---")
    method=st.radio("Upload method",["Upload CSV or Excel file","Paste Google Sheets URL"], horizontal=True, key="vnd_method")
    df_up=None

    if method=="Upload CSV or Excel file":
        f=st.file_uploader("Choose file",type=["csv","xlsx","xls"],key="vnd_upload")
        if f:
            try:
                df_up=pd.read_csv(f,dtype=str).fillna("") if f.name.endswith(".csv") else pd.read_excel(f,dtype=str).fillna("")
                st.success(f"Loaded {len(df_up)} row(s) from **{f.name}**")
            except Exception as e:
                st.error(f"Could not parse: {e}")
    else:
        gs_url=st.text_input("Google Sheets URL",key="vnd_gs_url")
        if gs_url and st.button("Load Sheet",key="vnd_load_gs"):
            import re
            m=re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)",gs_url)
            if not m: st.error("Could not extract Sheet ID.")
            else:
                gs_id=m.group(1)
                try:
                    token=get_access_token()
                    resp=_requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{gs_id}/values/A1:ZZ10000",
                        headers={"Authorization":f"Bearer {token}"},timeout=15)
                    resp.raise_for_status()
                    rows=resp.json().get("values",[])
                    if rows and len(rows)>=2:
                        h=rows[0]; d=[r+[""]*(len(h)-len(r)) for r in rows[1:]]
                        df_up=pd.DataFrame(d,columns=h).fillna("")
                        st.success(f"Loaded {len(df_up)} row(s)")
                    else:
                        st.warning("Sheet is empty.")
                except Exception as e:
                    try:
                        r2=_requests.get(f"https://docs.google.com/spreadsheets/d/{gs_id}/export?format=csv",timeout=15)
                        r2.raise_for_status()
                        df_up=pd.read_csv(StringIO(r2.text),dtype=str).fillna("")
                        st.success(f"Loaded {len(df_up)} row(s) via public export")
                    except Exception as e2:
                        st.error(f"Could not read sheet: {e2}")

    if df_up is not None and not df_up.empty:
        df_up.columns=[c.strip().lower().replace(" ","_") for c in df_up.columns]
        st.markdown("---")
        st.markdown(f"**Preview — {len(df_up)} row(s)**")
        st.dataframe(df_up,use_container_width=True,hide_index=True)
        req_cols={"event_name","event_city","event_country","organizer_name","organizer_email"}
        missing=req_cols-set(df_up.columns)
        if missing:
            st.warning(f"Missing required columns: **{', '.join(sorted(missing))}**")
        else:
            if st.button("Submit All Events",type="primary",use_container_width=True,key="vnd_bulk_sub"):
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); ok_count=0
                prog=st.progress(0)
                for i,row in df_up.iterrows():
                    eid=generate_confirmation_id().replace("CV-","EV-")
                    rid=generate_confirmation_id().replace("CV-","SR-")
                    ev_row=[eid,now,"Pending",
                            row.get("organizer_name",""),row.get("organizer_email",""),
                            row.get("organizer_org",""),row.get("organizer_role",""),row.get("org_website",""),
                            row.get("event_name",""),row.get("event_website",""),
                            row.get("event_start",row.get("event_date","")),row.get("event_end",""),
                            row.get("event_city",""),row.get("event_country",""),
                            row.get("event_format",""),row.get("expected_audience",""),
                            row.get("community_alignment",""),row.get("event_description",row.get("description","")),
                            row.get("how_heard",""),row.get("notes",row.get("additional_notes","")),""]
                    req_row=[rid,now,"Pending",eid,row.get("event_name",""),
                             row.get("speaker_topic",row.get("topic","")),row.get("topic_tags",""),
                             row.get("session_format",""),row.get("audience_level",""),
                             row.get("cfp_link",""),row.get("cfp_deadline",""),"",""]
                    if append_row("Events",ev_row) and append_row("Speaker_Requests",req_row):
                        ok_count+=1
                    prog.progress((i+1)/len(df_up))
                st.session_state["vnd_bulk_done"]=True; st.session_state["vnd_bulk_n"]=ok_count; st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: MY SUBMISSIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab_mine:
    st.markdown("### Check the status of your submitted events")
    with st.form("vnd_check_form"):
        check_email=st.text_input("Your organizer email address")
        check_sub=st.form_submit_button("Look up my events",type="primary",use_container_width=True)

    if check_sub:
        if not check_email:
            st.warning("Please enter your email.")
        else:
            with st.spinner("Looking up..."):
                try: df_ev=read_tab("Events")
                except Exception as ex: st.error(f"Database error: {ex}"); st.stop()
            if df_ev.empty or "organizer_email" not in df_ev.columns:
                st.info("No events found.")
            else:
                mine=df_ev[df_ev["organizer_email"].str.strip().str.lower()==check_email.strip().lower()]
                if mine.empty:
                    st.info(f"No events found for **{check_email}**. Double-check the email you registered with.")
                else:
                    st.markdown(f"**{len(mine)} event(s) found**")
                    STATUS_COLORS={"Pending":"🟡","Approved":"🟢","Waitlisted":"🔵","Not a Fit":"🔴"}
                    for _,ev in mine.iterrows():
                        icon=STATUS_COLORS.get(ev.get("status",""),("⚪"))
                        st.markdown(f"""
                        <div class="info-card">
                          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                            <span>{icon}</span>
                            <strong>{ev.get('event_name','')}</strong>
                            <span style="font-size:0.8rem;color:#718096;">· {ev.get('status','')}</span>
                          </div>
                          <p style="margin:0;font-size:0.88rem;color:#4A5568;">
                            📍 {ev.get('event_city','')}, {ev.get('event_country','')} &nbsp;·&nbsp;
                            📅 {ev.get('event_start','')}
                            &nbsp;·&nbsp; Ref: <code>{ev.get('event_id','')}</code>
                          </p>
                          {"<p style='font-size:0.85rem;color:#718096;margin-top:4px;'>Note: " + ev.get('admin_notes','') + "</p>" if ev.get('admin_notes','').strip() else ""}
                        </div>""", unsafe_allow_html=True)
