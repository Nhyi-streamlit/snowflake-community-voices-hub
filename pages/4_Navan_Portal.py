import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
import streamlit as st
import pandas as pd
from utils.styles import inject_css
from utils.sheets import read_tab, update_cell, col_letter

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
    All approved speaker travel requests from the Snowflake Community Voices program.
    Mark trips as booked once confirmed in Navan.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=90)
def load_navan_data():
    data = {}
    for tab in ["Speaker_Applications", "Travel_Details", "Uber_Requests"]:
        try: data[tab] = read_tab(tab)
        except Exception: data[tab] = pd.DataFrame()
    return data

data = load_navan_data()

if st.button("Refresh", key="navan_refresh"):
    st.cache_data.clear(); st.rerun()

TRAVEL_KEYWORDS = ["travel", "flight", "hotel", "accommodation", "registration"]
BOOKING_STATUSES = ["Pending Booking", "Booked", "Confirmed", "Cancelled"]

# ── Summary row ───────────────────────────────────────────────────────────────
df_apps = data.get("Speaker_Applications", pd.DataFrame())
df_travel = data.get("Travel_Details", pd.DataFrame())
df_uber = data.get("Uber_Requests", pd.DataFrame())

approved_with_travel = pd.DataFrame()
if not df_apps.empty and "status" in df_apps.columns and "support_types" in df_apps.columns:
    approved = df_apps[df_apps["status"] == "Approved"]
    mask = approved["support_types"].str.lower().str.contains("|".join(TRAVEL_KEYWORDS), na=False)
    approved_with_travel = approved[mask].copy()

m1,m2,m3,m4 = st.columns(4)
with m1: st.metric("Travel requests", len(approved_with_travel))
with m2:
    booked = 0
    if "navan_status" in approved_with_travel.columns:
        booked = (approved_with_travel["navan_status"].str.strip() == "Booked").sum()
    st.metric("Booked", int(booked))
with m3:
    pending_b = len(approved_with_travel) - int(booked)
    st.metric("Pending booking", pending_b)
with m4:
    try:
        total = pd.to_numeric(approved_with_travel.get("estimated_cost", pd.Series(dtype=str)), errors="coerce").sum()
        st.metric("Est. total spend", f"${total:,.0f}")
    except Exception: st.metric("Est. total spend", "—")

st.markdown("---")

# ── Tabs ───────────────────────────────────────────────────────────────────────
t_trips, t_details, t_uber, t_export = st.tabs([
    "✈️ Trip Requests", "📋 Speaker Travel Details", "🚗 Uber Requests", "📥 Export"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TRIP REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
with t_trips:
    st.markdown("### Approved speaker travel requests")
    st.markdown("These speakers have been approved and need flights/hotel booked. Mark as **Booked** once confirmed in Navan.")

    if approved_with_travel.empty:
        st.info("No pending travel requests at this time.")
    else:
        # Filter
        fc1,fc2 = st.columns(2)
        with fc1:
            navan_filter = st.multiselect("Filter by Navan status",
                BOOKING_STATUSES + ["(blank — not yet actioned)"],
                default=["(blank — not yet actioned)", "Pending Booking"],
                key="navan_status_filter")
        with fc2:
            region_filter = st.multiselect("Filter by event city",
                sorted(approved_with_travel["event_city"].dropna().unique().tolist()) if "event_city" in approved_with_travel.columns else [],
                key="navan_city_filter")

        filtered = approved_with_travel.copy()
        if region_filter and "event_city" in filtered.columns:
            filtered = filtered[filtered["event_city"].isin(region_filter)]

        for idx, r in filtered.iterrows():
            sheet_row = idx + 2
            full_name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
            email = r.get("email","")
            event = r.get("event_name","")
            city  = r.get("event_city","")
            ev_date = r.get("event_date_start","")
            origin = r.get("traveling_from", r.get("city",""))
            cost   = r.get("estimated_cost","0")
            support= r.get("support_types","")
            talk   = r.get("talk_title","")
            cid    = r.get("confirmation_id","")
            ns     = r.get("navan_status","").strip() if "navan_status" in r.index else ""
            n_notes= r.get("navan_notes","").strip() if "navan_notes" in r.index else ""

            # Apply navan_filter
            ns_display = ns if ns else "(blank — not yet actioned)"
            if navan_filter and ns_display not in navan_filter:
                continue

            status_icon = {"Booked":"🟢","Confirmed":"✅","Cancelled":"❌","Pending Booking":"🟡"}.get(ns,"🔵")

            with st.expander(f"{status_icon} **{full_name}** — {event} ({city}) · {ev_date}"):
                col_info, col_action = st.columns([2,1])

                with col_info:
                    st.markdown(f"""
                    | Field | Value |
                    |-------|-------|
                    | **Traveler** | {full_name} |
                    | **Email** | {email} |
                    | **Talk** | {talk} |
                    | **Event** | {event} |
                    | **Destination** | {city} |
                    | **Event date** | {ev_date} |
                    | **Origin** | {origin} |
                    | **Support needed** | {support} |
                    | **Est. cost** | ${cost} |
                    | **Program ID** | {cid} |
                    """)

                    # Show travel details if submitted by speaker
                    if not df_travel.empty and "confirmation_id" in df_travel.columns:
                        td = df_travel[df_travel["confirmation_id"]==cid]
                        if not td.empty:
                            t = td.iloc[0]
                            st.markdown("**Speaker-submitted travel details:**")
                            st.markdown(f"""
                            - **Airline:** {t.get('airline','')} · Flight: {t.get('flight_number','')}
                            - **Outbound:** {t.get('departure_city','')} → {t.get('arrival_city','')} on {t.get('departure_datetime','')}
                            - **Return:** {t.get('return_flight_number','')} on {t.get('return_departure_datetime','')}
                            - **Hotel:** {t.get('hotel_name','')} · Check-in: {t.get('hotel_checkin','')} → {t.get('hotel_checkout','')}
                            """)

                    # Navan email template
                    navan_email = f"""Hi Navan team,

Please book the following trip for a Snowflake Community Voices speaker:

TRAVELER
Name: {full_name}
Email: {email}
Program reference: {cid}

TRIP
Event: {event}
Destination: {city}
Event date: {ev_date}
Origin: {origin}
Support needed: {support}
Budget: ~${cost} USD

TALK
{talk}

Please confirm booking details by reply.

Regards,
Snowflake Community Voices Team"""

                    st.text_area("Navan booking email (copy & send)", value=navan_email,
                        height=240, key=f"nv_email_{cid}")

                with col_action:
                    new_ns = st.selectbox("Navan booking status",
                        ["(not actioned)"] + BOOKING_STATUSES,
                        index=(BOOKING_STATUSES.index(ns)+1 if ns in BOOKING_STATUSES else 0),
                        key=f"nv_ns_{cid}")
                    new_nn = st.text_area("Navan notes (confirmation #, PNR, etc.)",
                        value=n_notes, height=80, key=f"nv_nn_{cid}")
                    if st.button("Save", key=f"nv_save_{cid}", type="primary"):
                        final_ns = "" if new_ns == "(not actioned)" else new_ns
                        ns_col  = col_letter(df_apps, "navan_status") if "navan_status" in df_apps.columns else "W"
                        nn_col  = col_letter(df_apps, "navan_notes")  if "navan_notes"  in df_apps.columns else "X"
                        ok1 = update_cell("Speaker_Applications", sheet_row, ns_col, final_ns)
                        ok2 = update_cell("Speaker_Applications", sheet_row, nn_col, new_nn)
                        if ok1 and ok2:
                            st.success("Saved!"); st.cache_data.clear()
                        else:
                            st.error("Save failed — check Sheets connection.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: SPEAKER TRAVEL DETAILS
# ══════════════════════════════════════════════════════════════════════════════
with t_details:
    st.markdown("### Travel details submitted by speakers")
    st.markdown("Speakers fill in their flight and hotel details in the Speaker Portal. They appear here for reference.")

    if df_travel.empty or len(df_travel.columns) < 3:
        st.info("No travel details submitted yet.")
    else:
        st.dataframe(df_travel, use_container_width=True, hide_index=True)

        # Export
        csv = df_travel.to_csv(index=False).encode()
        st.download_button("Export travel details CSV", data=csv,
            file_name=f"travel_details_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: UBER REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
with t_uber:
    st.markdown("### Uber gift card requests")
    st.markdown("Speakers requesting Uber gift cards for local transport at their event.")

    if df_uber.empty or len(df_uber.columns) < 3:
        st.info("No Uber requests yet.")
    else:
        # Mark as fulfilled
        for idx, row in df_uber.iterrows():
            sheet_row = idx + 2
            name  = row.get("speaker_name","")
            email = row.get("speaker_email","")
            ev    = row.get("event_name","")
            city  = row.get("event_city","")
            rides = row.get("rides_needed","")
            amt   = row.get("amount_requested_usd","")
            status_u = row.get("status","Pending")
            rid   = row.get("request_id","")

            icon = "🟢" if status_u=="Fulfilled" else "🟡"
            with st.expander(f"{icon} **{name}** — {ev} ({city}) · {rides} ride(s) · ${amt}"):
                sc1,sc2 = st.columns([2,1])
                with sc1:
                    st.markdown(f"""
                    | | |
                    |--|--|
                    | **Speaker** | {name} ({email}) |
                    | **Event** | {ev} — {city} |
                    | **Rides needed** | {rides} |
                    | **Amount requested** | ${amt} |
                    | **Notes** | {row.get('notes','')} |
                    | **Request ID** | {rid} |
                    """)
                with sc2:
                    new_u_status = st.selectbox("Status",["Pending","Fulfilled","Declined"],
                        index=["Pending","Fulfilled","Declined"].index(status_u) if status_u in ["Pending","Fulfilled","Declined"] else 0,
                        key=f"uber_st_{rid}")
                    if st.button("Update", key=f"uber_upd_{rid}", type="primary"):
                        sc = col_letter(df_uber, "status")
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
# TAB 4: EXPORT (NAVAN BATCH)
# ══════════════════════════════════════════════════════════════════════════════
with t_export:
    st.markdown("### Export all pending trips for Navan")
    st.markdown("Download a Navan-compatible CSV of all approved speaker trips that haven't been booked yet.")

    if approved_with_travel.empty:
        st.info("No trips to export.")
    else:
        # Build export
        navan_rows = []
        for _, r in approved_with_travel.iterrows():
            ns = r.get("navan_status","").strip() if "navan_status" in r.index else ""
            if ns in ("Booked","Confirmed"):
                continue  # already handled
            full_name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
            # Check if speaker submitted travel details
            td_row = {}
            if not df_travel.empty and "confirmation_id" in df_travel.columns:
                td = df_travel[df_travel["confirmation_id"]==r.get("confirmation_id","")]
                if not td.empty: td_row = td.iloc[0].to_dict()

            navan_rows.append({
                "traveler_name":      full_name,
                "traveler_email":     r.get("email",""),
                "program_id":         r.get("confirmation_id",""),
                "trip_purpose":       f"Speaking: {r.get('talk_title','')}",
                "event_name":         r.get("event_name",""),
                "origin_city":        r.get("traveling_from", r.get("city","")),
                "destination_city":   r.get("event_city",""),
                "event_date":         r.get("event_date_start",""),
                "return_date":        r.get("event_date_end", r.get("event_date_start","")),
                "support_requested":  r.get("support_types",""),
                "budget_usd":         r.get("estimated_cost","0"),
                "speaker_airline":    td_row.get("airline",""),
                "speaker_flight_no":  td_row.get("flight_number",""),
                "speaker_hotel":      td_row.get("hotel_name",""),
                "speaker_hotel_checkin": td_row.get("hotel_checkin",""),
                "speaker_hotel_checkout":td_row.get("hotel_checkout",""),
                "navan_status":       ns or "Pending Booking",
            })

        if not navan_rows:
            st.info("All approved trips are already booked or confirmed.")
        else:
            navan_df = pd.DataFrame(navan_rows)
            st.markdown(f"**{len(navan_rows)} trip(s) pending booking**")
            st.dataframe(navan_df, use_container_width=True, hide_index=True)
            csv_n = navan_df.to_csv(index=False).encode()
            st.download_button(
                f"Download Navan batch CSV ({len(navan_rows)} trips)",
                data=csv_n,
                file_name=f"navan_batch_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                type="primary",
            )
