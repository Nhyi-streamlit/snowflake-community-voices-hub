import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.styles import inject_css
from utils.sheets import read_tab

st.set_page_config(
    page_title="Open Events — Community Voices",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Events Seeking Speakers</div>
  <h1>Open events — apply to speak</h1>
  <p>
    These events are actively looking for Snowflake community speakers.
    Find one that fits your expertise and apply — the organizer will be notified when you submit.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Load events ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_open_events():
    try:
        events = read_tab("Events")
        requests_df = read_tab("Speaker_Requests")
        return events, requests_df
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

with st.spinner("Loading open events..."):
    df_events, df_requests = load_open_events()

if st.button("Refresh", key="refresh_board"):
    st.cache_data.clear()
    st.rerun()

# ── Filter to events that are approved and need speakers ──────────────────────
if df_events.empty or "status" not in df_events.columns:
    st.info("No events are currently listed. Check back soon — new events are added regularly.")
    st.stop()

open_events = df_events[df_events["status"].str.strip() == "Approved"].copy()

# Exclude events that already have a matched speaker
if not df_requests.empty and "event_id" in df_requests.columns and "matched_speaker" in df_requests.columns:
    matched_ids = set(
        df_requests[df_requests["matched_speaker"].str.strip().ne("")]["event_id"].tolist()
    )
    open_events = open_events[~open_events.get("event_id", pd.Series(dtype=str)).isin(matched_ids)]

if open_events.empty:
    st.info("All current events have been matched with speakers. Check back soon for new listings.")
    st.stop()

# ── Filter sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filter events")

    all_formats = sorted(open_events["event_format"].dropna().unique().tolist()) if "event_format" in open_events.columns else []
    sel_format = st.multiselect("Event format", all_formats, key="filter_format")

    all_countries = sorted(open_events["event_country"].dropna().unique().tolist()) if "event_country" in open_events.columns else []
    sel_country = st.multiselect("Country", all_countries, key="filter_country")

    if "event_start" in open_events.columns:
        st.markdown("**Date range**")
        upcoming_only = st.checkbox("Upcoming events only", value=True, key="upcoming_only")
    else:
        upcoming_only = False

filtered = open_events.copy()
if sel_format:
    filtered = filtered[filtered["event_format"].isin(sel_format)]
if sel_country:
    filtered = filtered[filtered["event_country"].isin(sel_country)]
if upcoming_only and "event_start" in filtered.columns:
    from datetime import date
    today_str = date.today().strftime("%Y-%m-%d")
    filtered = filtered[filtered["event_start"].str[:10] >= today_str]

st.markdown(f"**{len(filtered)} open event(s)**")
st.markdown("---")

# ── Event cards ────────────────────────────────────────────────────────────────
if filtered.empty:
    st.info("No events match your filters.")
    st.stop()

# Get speaker request details for each event
def get_request(event_id):
    if df_requests.empty or "event_id" not in df_requests.columns:
        return {}
    match = df_requests[df_requests["event_id"] == event_id]
    return match.iloc[0].to_dict() if not match.empty else {}

# Show 2 cards per row
rows = [filtered.iloc[i:i+2] for i in range(0, len(filtered), 2)]

for row_df in rows:
    cols = st.columns(len(row_df), gap="large")
    for col, (_, ev) in zip(cols, row_df.iterrows()):
        event_id   = ev.get("event_id", "")
        event_name = ev.get("event_name", "Unnamed Event")
        city       = ev.get("event_city", "")
        country    = ev.get("event_country", "")
        fmt        = ev.get("event_format", "")
        start      = ev.get("event_start", "")
        end        = ev.get("event_end", "")
        audience   = ev.get("expected_audience", "")
        description= ev.get("event_description", "")
        website    = ev.get("event_website", "")

        req = get_request(event_id)
        speaker_topic  = req.get("speaker_topic", "")
        topic_tags     = req.get("topic_tags", "")
        session_format = req.get("session_format", "")
        cfp_link       = req.get("cfp_link", "")
        cfp_deadline   = req.get("cfp_deadline", "")

        # Format date
        date_str = f"{start}" + (f" → {end}" if end and end != start else "")

        with col:
            st.markdown(f"""
            <div class="info-card" style="border-color: #29B5E8; min-height: 280px;">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                <span class="step-label">{fmt or 'Event'}</span>
                <span style="font-size:0.75rem; color:#718096;">{event_id}</span>
              </div>
              <h4 style="font-size:1.1rem; margin-bottom:4px;">{event_name}</h4>
              <p style="color:#4A5568; margin:0 0 8px 0;">
                📍 {city}{', ' + country if country else ''} &nbsp;·&nbsp; 📅 {date_str}
                {f"&nbsp;·&nbsp; 👥 {audience}" if audience else ""}
              </p>
              {"<p style='font-size:0.85rem; color:#718096; margin:0 0 8px 0;'>" + description[:200] + ("..." if len(description) > 200 else "") + "</p>" if description else ""}
              {"<p style='font-size:0.85rem; margin:4px 0;'><strong>Topic wanted:</strong> " + speaker_topic[:150] + ("..." if len(speaker_topic) > 150 else "") + "</p>" if speaker_topic else ""}
              {"<p style='font-size:0.82rem; color:#718096; margin:4px 0;'>Tags: " + topic_tags + "</p>" if topic_tags else ""}
              {"<p style='font-size:0.82rem; color:#718096; margin:4px 0;'>Format: " + session_format + "</p>" if session_format else ""}
              {"<p style='font-size:0.82rem; color:#C05621; margin:4px 0;'><strong>CFP deadline:</strong> " + cfp_deadline + "</p>" if cfp_deadline else ""}
            </div>
            """, unsafe_allow_html=True)

            # Action buttons
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                import urllib.parse
                apply_params = urllib.parse.urlencode({
                    "event_id":      event_id,
                    "event_name":    event_name,
                    "event_city":    city,
                    "event_country": country,
                    "event_start":   start,
                })
                apply_url = f"Apply?{apply_params}"
                st.page_link(f"pages/1_Apply.py", label="Apply to Speak", icon="🎤")

            with btn_col2:
                if website:
                    st.link_button("Event site", website, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)
st.markdown("""
<p style="text-align:center; font-size:0.82rem; color:#A0AEC0;">
  Don't see your event here? Organizers can
  <a href="Events" style="color:#29B5E8;">register it</a>
  and request a community speaker.
</p>
""", unsafe_allow_html=True)
