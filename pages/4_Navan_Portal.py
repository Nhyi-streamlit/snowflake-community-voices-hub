import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
import streamlit as st
import pandas as pd
from utils.styles import inject_css
from utils.sheets import read_tab, update_cell, col_letter, send_gmail

st.set_page_config(
    page_title="Navan Travel Portal — Community Voices",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Password gate (separate from admin) ───────────────────────────────────────
if not st.session_state.get("navan_auth"):
    st.markdown("""
    <div class="page-hero" style="max-width:480px;margin:60px auto 0;">
      <div class="eyebrow">Travel Vendor Portal</div>
      <h1>Navan — Sign in</h1>
      <p>Restricted to the Snowflake travel booking team.</p>
    </div>
    """, unsafe_allow_html=True)
    with st.form("navan_login"):
        pw = st.text_input("Password", type="password")
        login = st.form_submit_button("Sign In", type="primary", use_container_width=True)
    if login:
        expected = ""
        try: expected = st.secrets.get("NAVAN_PASSWORD", "navan2026")
        except Exception: expected = os.environ.get("NAVAN_PASSWORD", "navan2026")
        if pw == expected:
            st.session_state["navan_auth"] = True; st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

if st.button("Sign out", key="navan_logout"):
    st.session_state["navan_auth"] = False; st.rerun()

st.markdown("""
<div class="page-hero" style="background:linear-gradient(135deg,#1A202C 0%,#2D3748 100%);">
  <div class="eyebrow">Navan Travel Portal</div>
  <h1>Community Voices — Travel Bookings</h1>
  <p>
    Speaker travel requests submitted through the Community Voices platform.
    Review details and update booking status as you confirm trips.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=90)
def load_navan_data():
    data = {}
    for tab in ["Travel_Details", "Uber_Requests"]:
        try: data[tab] = read_tab(tab)
        except Exception: data[tab] = pd.DataFrame()
    return data

data = load_navan_data()

if st.button("Refresh", key="navan_refresh"):
    st.cache_data.clear(); st.rerun()

BOOKING_STATUSES = ["Pending Booking", "In Progress", "Booked", "Confirmed", "Cancelled"]

df_travel = data.get("Travel_Details", pd.DataFrame())
df_uber = data.get("Uber_Requests", pd.DataFrame())

# ── Travel_Details column indices (positional — the tab has no header row yet,
#    or the header row matches the order written by the Speaker Portal form) ────
# The Speaker Portal writes rows in this order:
#  0: request_id, 1: submitted_at, 2: name, 3: email, 4: event_name,
#  5: event_city, 6: event_date, 7: passport_name, 8: dob, 9: passport_no,
# 10: passport_exp, 11: nationality, 12: phone, 13: fly_from, 14: fly_to,
# 15: outbound_date, 16: return_date, 17: seat_class, 18: airline_pref,
# 19: ff_number, 20: hotel_checkin, 21: hotel_checkout, 22: hotel_pref,
# 23: hotel_loyalty, 24: hotel_notes, 25: dietary, 26: emergency_name,
# 27: emergency_phone, 28: notes, 29: uber_code, 30: status

def _tv(row, col_name, default=""):
    """Safe column accessor for travel rows."""
    return str(row.get(col_name, default)).strip() if col_name in row.index else default

# ── Summary metrics ──────────────────────────────────────────────────────────
total_requests = len(df_travel)
if total_requests > 0 and "status" in df_travel.columns:
    booked_count = df_travel["status"].str.strip().isin(["Booked", "Confirmed"]).sum()
    pending_count = total_requests - int(booked_count)
else:
    booked_count = 0
    pending_count = total_requests

m1, m2, m3, m4 = st.columns(4)
with m1: st.metric("Total requests", total_requests)
with m2: st.metric("Booked / Confirmed", int(booked_count))
with m3: st.metric("Pending", int(pending_count))
with m4: st.metric("Uber requests", len(df_uber))

st.markdown("---")

# ── Tabs ───────────────────────────────────────────────────────────────────────
t_trips, t_uber, t_export = st.tabs([
    "✈️ Travel Requests", "🚗 Uber Requests", "📥 Export"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TRAVEL REQUESTS (from Travel_Details — the primary view)
# ══════════════════════════════════════════════════════════════════════════════
with t_trips:
    st.markdown("### Speaker travel requests")
    st.markdown("Each row is a travel request submitted by a speaker. Update the **booking status** as you process each trip.")

    if df_travel.empty or len(df_travel.columns) < 5:
        st.info("No travel requests submitted yet. Requests appear here when speakers fill in the Book Your Travel form.")
    else:
        # Filters
        fc1, fc2 = st.columns(2)
        with fc1:
            status_opts = sorted(df_travel["status"].dropna().unique().tolist()) if "status" in df_travel.columns else []
            navan_filter = st.multiselect(
                "Filter by booking status",
                status_opts or BOOKING_STATUSES,
                default=[s for s in ["Pending Booking", "In Progress"] if s in (status_opts or BOOKING_STATUSES)],
                key="nv_status_filter",
            )
        with fc2:
            city_col = "event_city" if "event_city" in df_travel.columns else None
            if city_col:
                city_opts = sorted(df_travel[city_col].dropna().unique().tolist())
                city_filter = st.multiselect("Filter by event city", city_opts, key="nv_city_filter")
            else:
                city_filter = []

        filtered = df_travel.copy()
        if navan_filter and "status" in filtered.columns:
            filtered = filtered[filtered["status"].str.strip().isin(navan_filter)]
        if city_filter and city_col:
            filtered = filtered[filtered[city_col].isin(city_filter)]

        if filtered.empty:
            st.info("No requests match the selected filters.")
        else:
            for idx, r in filtered.iterrows():
                sheet_row = idx + 2  # 1-indexed header + 0-indexed data
                req_id     = _tv(r, "request_id")
                submitted  = _tv(r, "submitted_at")
                name       = _tv(r, "name")
                email      = _tv(r, "email")
                event      = _tv(r, "event_name")
                city       = _tv(r, "event_city")
                ev_date    = _tv(r, "event_date")
                fly_from   = _tv(r, "fly_from")
                fly_to     = _tv(r, "fly_to")
                outbound   = _tv(r, "outbound_date")
                ret_date   = _tv(r, "return_date")
                seat_class = _tv(r, "seat_class")
                airline    = _tv(r, "airline_pref")
                ff         = _tv(r, "ff_number")
                h_in       = _tv(r, "hotel_checkin")
                h_out      = _tv(r, "hotel_checkout")
                h_pref     = _tv(r, "hotel_pref")
                h_loyalty  = _tv(r, "hotel_loyalty")
                h_notes    = _tv(r, "hotel_notes")
                passport   = _tv(r, "passport_name")
                dob        = _tv(r, "dob")
                passport_no= _tv(r, "passport_no")
                passport_exp=_tv(r, "passport_exp")
                nationality= _tv(r, "nationality")
                phone      = _tv(r, "phone")
                dietary    = _tv(r, "dietary")
                emerg_name = _tv(r, "emergency_name")
                emerg_phone= _tv(r, "emergency_phone")
                notes      = _tv(r, "notes")
                uber_code  = _tv(r, "uber_code")
                status     = _tv(r, "status", "Pending Booking")

                status_icon = {
                    "Booked": "🟢", "Confirmed": "✅", "Cancelled": "❌",
                    "Pending Booking": "🟡", "In Progress": "🔵",
                }.get(status, "🟡")

                with st.expander(f"{status_icon} **{name}** — {event} ({city}) · {ev_date} · submitted {submitted[:10] if len(submitted)>=10 else submitted}"):
                    col_info, col_action = st.columns([2, 1])

                    with col_info:
                        st.markdown("**Trip overview**")
                        st.markdown(f"""
| Field | Value |
|-------|-------|
| **Traveler** | {name} |
| **Email** | {email} |
| **Phone** | {phone} |
| **Event** | {event} |
| **Event city** | {city} |
| **Event date** | {ev_date} |
""")
                        st.markdown("**Flight details**")
                        st.markdown(f"""
| Field | Value |
|-------|-------|
| **From** | {fly_from} |
| **To** | {fly_to} |
| **Outbound** | {outbound} |
| **Return** | {ret_date} |
| **Class** | {seat_class} |
| **Airline pref** | {airline or '—'} |
| **FF number** | {ff or '—'} |
""")
                        st.markdown("**Hotel details**")
                        st.markdown(f"""
| Field | Value |
|-------|-------|
| **Check-in** | {h_in} |
| **Check-out** | {h_out} |
| **Preference** | {h_pref} |
| **Loyalty #** | {h_loyalty or '—'} |
| **Notes** | {h_notes or '—'} |
""")
                        with st.popover("View passport & additional details"):
                            st.markdown(f"""
- **Passport name:** {passport}
- **DOB:** {dob}
- **Passport #:** {passport_no or '—'}
- **Passport exp:** {passport_exp or '—'}
- **Nationality:** {nationality or '—'}
- **Dietary:** {dietary or '—'}
- **Emergency contact:** {emerg_name or '—'} ({emerg_phone or '—'})
- **Speaker notes:** {notes or '—'}
- **Uber code issued:** {uber_code or '—'}
""")

                        # Pre-filled email for Navan team
                        navan_email = f"""Hi Navan team,

Please book the following trip for a Snowflake Community Voices speaker:

TRAVELER
Name: {passport}
Email: {email}
Phone: {phone}
Nationality: {nationality}

FLIGHTS
From: {fly_from}
To: {fly_to}
Outbound: {outbound}
Return: {ret_date}
Preferred class: {seat_class}
Airline preference: {airline or 'None'}
Frequent flyer: {ff or 'None'}

HOTEL
Check-in: {h_in}
Check-out: {h_out}
Preference: {h_pref}
Loyalty: {h_loyalty or 'None'}
Special requirements: {h_notes or 'None'}

EVENT
{event} — {city} — {ev_date}

ADDITIONAL
Dietary: {dietary or 'None'}
Emergency contact: {emerg_name or 'None'} ({emerg_phone or 'None'})
Speaker notes: {notes or 'None'}

Please confirm booking details by reply.

Regards,
Snowflake Community Voices Team"""

                        st.text_area("Navan booking email (copy & send)", value=navan_email,
                            height=240, key=f"nv_email_{req_id}")

                    with col_action:
                        st.markdown("**Update booking**")
                        new_status = st.selectbox(
                            "Booking status",
                            BOOKING_STATUSES,
                            index=BOOKING_STATUSES.index(status) if status in BOOKING_STATUSES else 0,
                            key=f"nv_st_{req_id}",
                        )
                        navan_ref = st.text_input(
                            "Navan reference / PNR",
                            placeholder="NAV-123456",
                            key=f"nv_ref_{req_id}",
                        )
                        navan_notes = st.text_area(
                            "Booking notes",
                            height=80,
                            placeholder="Flight confirmed, hotel pending...",
                            key=f"nv_notes_{req_id}",
                        )
                        if st.button("Save", key=f"nv_save_{req_id}", type="primary", use_container_width=True):
                            # Update the status column in Travel_Details
                            status_col = col_letter(df_travel, "status") if "status" in df_travel.columns else "AE"
                            ok = update_cell("Travel_Details", sheet_row, status_col, new_status)
                            if ok:
                                st.success(f"Status updated to **{new_status}**")
                                st.cache_data.clear()
                            else:
                                st.error("Save failed — check Sheets connection.")

        st.markdown("---")
        csv_t = df_travel.to_csv(index=False).encode()
        st.download_button("Export all travel requests CSV", data=csv_t,
            file_name=f"travel_requests_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: UBER REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
with t_uber:
    st.markdown("### Uber gift card requests")
    st.markdown("Speakers requesting Uber gift cards for local transport at their event.")

    if df_uber.empty or len(df_uber.columns) < 3:
        st.info("No Uber requests yet.")
    else:
        for idx, row in df_uber.iterrows():
            sheet_row = idx + 2
            # Use positional fallback for column names
            cols = list(row.index)
            name     = str(row.iloc[2]).strip() if len(cols) > 2 else ""
            email    = str(row.iloc[3]).strip() if len(cols) > 3 else ""
            ev       = str(row.iloc[4]).strip() if len(cols) > 4 else ""
            city     = str(row.iloc[5]).strip() if len(cols) > 5 else ""
            ev_date  = str(row.iloc[6]).strip() if len(cols) > 6 else ""
            rides    = str(row.iloc[7]).strip() if len(cols) > 7 else ""
            amt      = str(row.iloc[8]).strip() if len(cols) > 8 else ""
            ub_notes = str(row.iloc[9]).strip() if len(cols) > 9 else ""
            ub_code  = str(row.iloc[10]).strip() if len(cols) > 10 else ""
            status_u = str(row.iloc[11]).strip() if len(cols) > 11 else "Pending"
            rid      = str(row.iloc[0]).strip() if len(cols) > 0 else str(idx)

            icon = {"Fulfilled": "🟢", "Pending": "🟡"}.get(status_u.split("—")[0].strip(), "🟡")
            with st.expander(f"{icon} **{name}** — {ev} ({city}) · {rides} · ${amt}"):
                sc1, sc2 = st.columns([2, 1])
                with sc1:
                    st.markdown(f"""
| | |
|--|--|
| **Speaker** | {name} ({email}) |
| **Event** | {ev} — {city} — {ev_date} |
| **Rides needed** | {rides} |
| **Amount** | ${amt} |
| **Notes** | {ub_notes or '—'} |
| **Uber code issued** | {ub_code or '—'} |
| **Status** | {status_u} |
""")
                with sc2:
                    uber_statuses = ["Pending", "Fulfilled", "Pending — No codes", "Declined"]
                    cur_idx = 0
                    for i, s in enumerate(uber_statuses):
                        if status_u.strip() == s:
                            cur_idx = i; break
                    new_u_status = st.selectbox("Status", uber_statuses, index=cur_idx,
                        key=f"uber_st_{rid}")
                    if st.button("Update", key=f"uber_upd_{rid}", type="primary"):
                        # Status is the last column
                        sc = chr(ord("A") + len(cols) - 1) if len(cols) <= 26 else "L"
                        if update_cell("Uber_Requests", sheet_row, sc, new_u_status):
                            st.success("Updated!"); st.cache_data.clear(); st.rerun()
                        else:
                            st.error("Update failed.")

        st.markdown("---")
        csv_u = df_uber.to_csv(index=False).encode()
        st.download_button("Export Uber requests CSV", data=csv_u,
            file_name=f"uber_requests_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: EXPORT (NAVAN BATCH)
# ══════════════════════════════════════════════════════════════════════════════
with t_export:
    st.markdown("### Export pending trips for Navan")
    st.markdown("Download a CSV of all travel requests that haven't been booked yet — ready to import into Navan.")

    if df_travel.empty:
        st.info("No trips to export.")
    else:
        pending = df_travel.copy()
        if "status" in pending.columns:
            pending = pending[~pending["status"].str.strip().isin(["Booked", "Confirmed", "Cancelled"])]

        if pending.empty:
            st.info("All trips are already booked, confirmed, or cancelled.")
        else:
            # Build clean export
            export_cols = []
            col_map = {
                "name": "traveler_name", "email": "traveler_email",
                "event_name": "event", "event_city": "destination",
                "event_date": "event_date", "fly_from": "origin_airport",
                "fly_to": "dest_airport", "outbound_date": "depart",
                "return_date": "return", "seat_class": "class",
                "airline_pref": "airline_pref", "hotel_checkin": "hotel_in",
                "hotel_checkout": "hotel_out", "hotel_pref": "hotel_pref",
                "phone": "phone", "status": "booking_status",
            }
            export_df = pd.DataFrame()
            for src, dst in col_map.items():
                if src in pending.columns:
                    export_df[dst] = pending[src]

            st.markdown(f"**{len(export_df)} trip(s) pending booking**")
            st.dataframe(export_df, use_container_width=True, hide_index=True)
            csv_n = export_df.to_csv(index=False).encode()
            st.download_button(
                f"Download Navan batch CSV ({len(export_df)} trips)",
                data=csv_n,
                file_name=f"navan_batch_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                type="primary",
            )
