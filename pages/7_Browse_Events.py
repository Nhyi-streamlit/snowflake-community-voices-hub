import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
import streamlit as st
import pandas as pd
import requests as _requests
from utils.styles import inject_css
from utils.sheets import read_tab, append_row, get_access_token
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Open Events — Community Voices",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Config ─────────────────────────────────────────────────────────────────────
# The working sheet that tracks open speaking slots
SLOTS_SHEET_ID = "1IgTYK8vV-AhDI3HuYB3KEjN8knRjY66LAOIWF0QT5II"
SLOTS_TAB = "Sheet1"

REGION_COLORS = {
    "US Central":  ("#EBF8FF", "#2B6CB0"),
    "US East":     ("#EBF8FF", "#2B6CB0"),
    "US West":     ("#EBF8FF", "#2B6CB0"),
    "APAC":        ("#F0FFF4", "#276749"),
    "EMEA":        ("#FAF5FF", "#553C9A"),
    "LATAM":       ("#FFFBEB", "#B7791F"),
    "Canada":      ("#E6FFFA", "#234E52"),
}

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Events Seeking Speakers</div>
  <h1>Open speaking slots</h1>
  <p>
    These events are confirmed and actively need Snowflake community speakers.
    Find a city that works for you, sign up, and the program team will follow up directly.
  </p>
</div>
""", unsafe_allow_html=True)


# ── Load slots from working sheet ──────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_slots():
    try:
        token = get_access_token()
        resp = _requests.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{SLOTS_SHEET_ID}"
            f"/values/A1:G200",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("values", [])
    except Exception as e:
        return []

@st.cache_data(ttl=300)
def load_platform_events():
    try:
        ev = read_tab("Events")
        rq = read_tab("Speaker_Requests")
        return ev, rq
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def write_signup_to_slots(sheet_row: int, name: str, email: str) -> bool:
    """Write speaker name + email into the slots working sheet."""
    try:
        token = get_access_token()
        cell_range = f"Sheet1!F{sheet_row}:G{sheet_row}"
        resp = _requests.put(
            f"https://sheets.googleapis.com/v4/spreadsheets/{SLOTS_SHEET_ID}"
            f"/values/{cell_range}",
            params={"valueInputOption": "RAW"},
            json={"values": [[name, email]]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Refresh button ─────────────────────────────────────────────────────────────
if st.button("Refresh", key="refresh_board"):
    st.cache_data.clear()
    st.rerun()

raw_rows = load_slots()
df_platform, df_requests = load_platform_events()

# ── Parse slots sheet ──────────────────────────────────────────────────────────
# Structure: row 0 = title, row 1 = description, row 2 = headers, rows 3+ = data
if not raw_rows or len(raw_rows) < 4:
    st.info("No open slots found. Check back soon.")
    st.stop()

# Find the header row (contains "City")
header_idx = next((i for i, r in enumerate(raw_rows) if r and str(r[0]).strip().lower() == "city"), 2)
data_rows = raw_rows[header_idx + 1:]

# Pad rows to 7 cols
data_rows = [r + [""] * (7 - len(r)) for r in data_rows if r and str(r[0]).strip()]

df_slots = pd.DataFrame(data_rows, columns=["City", "Date", "Region", "Partner", "Status", "Interested_Name", "Email"])
df_slots["_sheet_row"] = range(header_idx + 2, header_idx + 2 + len(df_slots))  # 1-based sheet row

open_slots = df_slots[df_slots["Status"].str.upper().str.strip() == "OPEN"].copy()

# ── Sidebar filters ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filter slots")

    regions = sorted(open_slots["Region"].dropna().unique().tolist())
    sel_region = st.multiselect("Region", regions, key="filter_region")

    partners = sorted(open_slots["Partner"].dropna().unique().tolist())
    sel_partner = st.multiselect("Partner / event series", partners, key="filter_partner")

    show_unclaimed = st.checkbox("Show only unclaimed slots", value=False, key="unclaimed_only")

filtered_slots = open_slots.copy()
if sel_region:
    filtered_slots = filtered_slots[filtered_slots["Region"].isin(sel_region)]
if sel_partner:
    filtered_slots = filtered_slots[filtered_slots["Partner"].isin(sel_partner)]
if show_unclaimed:
    filtered_slots = filtered_slots[filtered_slots["Interested_Name"].str.strip() == ""]

# ══════════════════════════════════════════════════════════════════════════════
# OPEN SLOTS — from working sheet
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"### {len(filtered_slots)} open slot(s)")

if filtered_slots.empty:
    st.info("No slots match your filters.")
else:
    # Group by partner for display
    for partner, group in filtered_slots.groupby("Partner"):
        st.markdown(f"**{partner}**")
        cols = st.columns(3, gap="medium")
        col_idx = 0

        for _, slot in group.iterrows():
            city         = slot["City"]
            ev_date      = slot["Date"]
            region       = slot["Region"]
            sheet_row    = int(slot["_sheet_row"])
            claimed_name = slot["Interested_Name"].strip()
            claimed_email= slot["Email"].strip()

            bg, accent = REGION_COLORS.get(region, ("#F7FAFC", "#4A5568"))
            tag_style   = f"background:{accent}20; color:{accent}; border:1px solid {accent}40;"

            with cols[col_idx % 3]:
                # Claimed badge
                claimed_html = ""
                if claimed_name:
                    claimed_html = f"<br><span style='font-size:0.78rem; color:#718096;'>Interested: {claimed_name}</span>"

                st.markdown(f"""
                <div style="background:{bg}; border:1px solid {accent}40; border-radius:12px;
                             padding:18px 20px; margin-bottom:8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:0.7rem; font-weight:700; padding:2px 10px;
                                 border-radius:20px; {tag_style}">{region}</span>
                    <span style="font-size:0.7rem; color:#A0AEC0;">{partner}</span>
                  </div>
                  <div style="font-size:1.1rem; font-weight:700; color:#0E2346;">{city}</div>
                  <div style="font-size:0.88rem; color:#4A5568; margin-top:2px;">📅 {ev_date}</div>
                  {claimed_html}
                </div>
                """, unsafe_allow_html=True)

                # Sign-up state key
                key_open = f"open_{sheet_row}"
                key_done = f"done_{sheet_row}"

                if st.session_state.get(key_done):
                    st.success("You're on the list!", icon="✅")
                elif st.session_state.get(key_open):
                    with st.form(key=f"form_{sheet_row}"):
                        spk_name  = st.text_input("Your name", key=f"name_{sheet_row}")
                        spk_email = st.text_input("Your email", key=f"email_{sheet_row}")
                        sub = st.form_submit_button("Submit", type="primary", use_container_width=True)
                        cancel = st.form_submit_button("Cancel")

                    if cancel:
                        st.session_state[key_open] = False
                        st.rerun()

                    if sub and spk_name and spk_email:
                        # 1. Write to working sheet
                        write_signup_to_slots(sheet_row, spk_name, spk_email)

                        # 2. Create speaker application in platform
                        cid = generate_confirmation_id()
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        app_row = [
                            cid, now, "Pending",
                            spk_name.split()[0] if spk_name else "",
                            " ".join(spk_name.split()[1:]) if len(spk_name.split()) > 1 else "",
                            spk_email,
                            "", "", "", "", "",  # job_title, company, linkedin, country, city
                            "Community Member", "", "",  # community_identity, years, bio
                            f"{partner} — {city}", "",  # event_name, event_website
                            ev_date, "",   # event_date_start, end
                            city, "",      # event_city, event_country
                            "In-person conference", "",   # event_type, audience_size
                            "", "",        # talk_title, talk_abstract
                            "", "",        # session_type, audience_level
                            "", "Travel grant (flights), Snowflake swag kit",  # topics, support_types
                            "", "0", f"Signed up from Events Board — {partner} {city} {ev_date}", "", "",
                        ]
                        append_row("Speaker_Applications", app_row)

                        st.session_state[key_done] = True
                        st.session_state[key_open] = False
                        st.session_state[f"cid_{sheet_row}"] = cid
                        st.cache_data.clear()
                        st.rerun()
                    elif sub:
                        st.warning("Please enter both your name and email.")
                else:
                    st.button(
                        "I'm interested",
                        key=f"btn_{sheet_row}",
                        on_click=lambda k=key_open: st.session_state.update({k: True}),
                        use_container_width=True,
                    )

                # Show confirmation ID after sign-up
                if st.session_state.get(key_done) and st.session_state.get(f"cid_{sheet_row}"):
                    cid_display = st.session_state[f"cid_{sheet_row}"]
                    st.markdown(f"""
                    <div class="id-box" style="margin:4px 0; padding:10px 14px;">
                      <div class="label" style="font-size:0.65rem;">Confirmation ID</div>
                      <div class="id" style="font-size:0.95rem;">{cid_display}</div>
                    </div>
                    """, unsafe_allow_html=True)

            col_idx += 1

        st.markdown("<br>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM EVENTS — from Events tab (vendor-registered)
# ══════════════════════════════════════════════════════════════════════════════
if not df_platform.empty and "status" in df_platform.columns:
    open_platform = df_platform[df_platform["status"].str.strip() == "Approved"].copy()

    # Exclude already matched
    if not df_requests.empty and "event_id" in df_requests.columns and "matched_speaker" in df_requests.columns:
        matched = set(df_requests[df_requests["matched_speaker"].str.strip().ne("")]["event_id"].tolist())
        open_platform = open_platform[~open_platform.get("event_id", pd.Series(dtype=str)).isin(matched)]

    if not open_platform.empty:
        st.markdown("---")
        st.markdown("### Community-submitted events also seeking speakers")

        rows_p = [open_platform.iloc[i:i+2] for i in range(0, len(open_platform), 2)]
        for row_df in rows_p:
            cols_p = st.columns(len(row_df), gap="large")
            for col_p, (_, ev) in zip(cols_p, row_df.iterrows()):
                event_id    = ev.get("event_id", "")
                event_name  = ev.get("event_name", "")
                city        = ev.get("event_city", "")
                country     = ev.get("event_country", "")
                fmt         = ev.get("event_format", "")
                start       = ev.get("event_start", "")
                audience    = ev.get("expected_audience", "")
                description = ev.get("event_description", "")
                website     = ev.get("event_website", "")

                req = {}
                if not df_requests.empty and "event_id" in df_requests.columns:
                    m = df_requests[df_requests["event_id"] == event_id]
                    if not m.empty:
                        req = m.iloc[0].to_dict()

                with col_p:
                    st.markdown(f"""
                    <div class="info-card" style="border-color:#29B5E8;">
                      <span class="step-label">{fmt or 'Event'}</span>
                      <h4 style="margin-bottom:4px;">{event_name}</h4>
                      <p style="color:#4A5568; margin:0 0 6px 0;">
                        📍 {city}{', ' + country if country else ''} &nbsp;·&nbsp; 📅 {start}
                        {f"&nbsp;·&nbsp; 👥 {audience}" if audience else ""}
                      </p>
                      {"<p style='font-size:0.85rem;color:#718096;'>" + description[:180] + "...</p>" if len(description) > 180 else ("<p style='font-size:0.85rem;color:#718096;'>" + description + "</p>" if description else "")}
                      {"<p style='font-size:0.85rem;'><strong>Topic:</strong> " + req.get('speaker_topic','')[:120] + "</p>" if req.get('speaker_topic') else ""}
                    </div>
                    """, unsafe_allow_html=True)
                    import urllib.parse
                    params = urllib.parse.urlencode({
                        "event_id": event_id, "event_name": event_name,
                        "event_city": city, "event_country": country, "event_start": start,
                    })
                    st.page_link("pages/1_Apply.py", label="Apply to Speak", icon="🎤")
                    if website:
                        st.link_button("Event site", website, use_container_width=True)
            st.markdown("<br>", unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)
st.markdown("""
<p style="text-align:center; font-size:0.82rem; color:#A0AEC0;">
  Hosting an event and need a speaker?
  <a href="Events" style="color:#29B5E8;">Register it here</a>
  and the Community Voices team will find a match.
</p>
""", unsafe_allow_html=True)
