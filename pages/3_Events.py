import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from io import StringIO, BytesIO
import streamlit as st
import pandas as pd
from utils.styles import inject_css
from utils.sheets import append_row, get_access_token, _secrets
from utils.confirmation import generate_confirmation_id
import requests

st.set_page_config(
    page_title="Register Your Event — Community Voices",
    page_icon="🏟️",
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Guard: already submitted (single form) ─────────────────────────────────────
if st.session_state.get("event_submitted"):
    eid = st.session_state.get("event_id", "")
    st.markdown(f"""
    <div class="success-box">
      <h2>Event registered!</h2>
      <p>
        Your event and speaker request are under review.
        The Community Voices team will be in touch within 5 business days.
      </p>
    </div>
    <div class="id-box" style="margin-top: 24px;">
      <div class="label">Your Event Reference ID</div>
      <div class="id">{eid}</div>
    </div>
    """, unsafe_allow_html=True)
    st.info("Save this ID — you may be asked to reference it in follow-up communications.", icon="📋")
    if st.button("Register another event"):
        del st.session_state["event_submitted"]
        del st.session_state["event_id"]
        st.rerun()
    st.stop()

if st.session_state.get("bulk_submitted"):
    n = st.session_state.get("bulk_count", 0)
    st.markdown(f"""
    <div class="success-box">
      <h2>{n} event{'s' if n != 1 else ''} submitted!</h2>
      <p>The Community Voices team will review and follow up within 5 business days.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Upload another batch"):
        del st.session_state["bulk_submitted"]
        del st.session_state["bulk_count"]
        st.rerun()
    st.stop()

# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-hero" style="background: linear-gradient(135deg, #44337A 0%, #6B46C1 100%);">
  <div class="eyebrow">Event & Vendor Portal</div>
  <h1>Register your event</h1>
  <p>
    Register a single event using the form below, or upload multiple events at once
    via CSV, Excel, or a Google Sheets link.
  </p>
</div>
""", unsafe_allow_html=True)

tab_single, tab_bulk = st.tabs(["Register Single Event", "Bulk Upload (CSV / Excel / Google Sheets)"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Single event form (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════
with tab_single:

    # ── Section 1: About You (Organizer) ──────────────────────────────────────
    st.markdown('<div class="step-label">Section 1 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">About You (Event Organizer)</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-hint">Tell us who you are and how to reach you.</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        organizer_name  = st.text_input("Your full name *", placeholder="Jordan Smith")
    with c2:
        organizer_email = st.text_input("Email address *", placeholder="jordan@event.org")

    c3, c4 = st.columns(2)
    with c3:
        organizer_org  = st.text_input("Organization / company *", placeholder="PyCon Foundation")
    with c4:
        organizer_role = st.text_input("Your role in the event", placeholder="Program Chair")

    org_website = st.text_input("Organization website", placeholder="https://...")

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 2: Event Details ───────────────────────────────────────────────
    st.markdown('<div class="step-label">Section 2 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Event Details</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-hint">Tell us about your event.</div>', unsafe_allow_html=True)

    event_name    = st.text_input("Event name *", placeholder="Data + AI Summit EMEA 2026")
    event_website = st.text_input("Event website *", placeholder="https://...")

    c5, c6 = st.columns(2)
    with c5:
        event_start = st.date_input("Event start date *", min_value=date.today())
    with c6:
        event_end   = st.date_input("Event end date", min_value=date.today())

    c7, c8 = st.columns(2)
    with c7:
        event_city    = st.text_input("City *", placeholder="Amsterdam")
    with c8:
        event_country = st.text_input("Country *", placeholder="Netherlands")

    event_format = st.selectbox(
        "Event format *",
        ["Select...", "In-person conference", "Hybrid conference", "Virtual conference",
         "Community meetup (in-person)", "Community meetup (virtual)", "University / academic",
         "Corporate / industry event", "Other"],
    )

    expected_audience = st.select_slider(
        "Expected total attendance",
        options=["< 50", "50–200", "200–500", "500–1,000", "1,000–5,000", "5,000+"],
        value="200–500",
    )

    community_alignment = st.multiselect(
        "Primary audience profile",
        ["Data Engineers", "Analytics Engineers", "Data Scientists / ML Engineers",
         "Software / App Developers", "Data Analysts", "Data Leaders / Executives",
         "AI / GenAI Builders", "Open Source Community", "Academic / Student"],
    )

    event_description = st.text_area(
        "Describe your event in 2–4 sentences *",
        placeholder="PyData Amsterdam is a community conference...",
        height=100,
    )

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 3: Speaker Request ─────────────────────────────────────────────
    st.markdown('<div class="step-label">Section 3 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Speaker Request</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-hint">What kind of speaker are you looking for?</div>', unsafe_allow_html=True)

    speaker_topic = st.text_area(
        "Describe the topic or talk you'd like a speaker for *",
        placeholder="We're looking for a speaker to talk about AI / LLM applications...",
        height=100,
    )

    topic_tags = st.multiselect(
        "Topic tags",
        ["Data Engineering", "Snowpark / Python", "Cortex AI / LLMs", "Streamlit",
         "Data Sharing", "Cost Optimization", "ML / MLOps", "Iceberg", "Dynamic Tables",
         "Data Governance", "Real-Time / Streaming", "Other"],
    )

    c9, c10 = st.columns(2)
    with c9:
        session_format = st.selectbox(
            "Session format",
            ["Select...", "Conference talk (30–45 min)", "Lightning talk (< 15 min)",
             "Workshop / hands-on lab", "Panel", "Keynote", "Demo / product showcase"],
        )
    with c10:
        audience_level = st.selectbox(
            "Preferred technical level",
            ["No preference", "Beginner-friendly", "Intermediate", "Advanced"],
        )

    cfp_link     = st.text_input("CFP / speaker submission link (if applicable)", placeholder="https://...")
    cfp_deadline = st.date_input("CFP deadline (if applicable)", min_value=date.today(), value=None)

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ── Section 4 ─────────────────────────────────────────────────────────────
    st.markdown('<div class="step-label">Section 4 of 4</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Anything else?</div>', unsafe_allow_html=True)

    how_heard = st.selectbox(
        "How did you hear about Community Voices?",
        ["Select...", "Snowflake website", "Social media", "Word of mouth / referral",
         "Previous Snowflake speaker at our event", "Snowflake team member", "Other"],
    )

    additional_notes = st.text_area("Additional notes or requests", height=90)

    st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    required_ok = all([
        organizer_name, organizer_email, organizer_org,
        event_name, event_website,
        event_city, event_country,
        event_format not in ("", "Select..."),
        event_description, speaker_topic,
    ])
    if not required_ok:
        st.caption("Complete all required fields (marked *) to submit.")

    if st.button("Register Event & Request Speaker", type="primary", use_container_width=True, disabled=not required_ok):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eid = generate_confirmation_id().replace("CV-", "EV-")
        rid = generate_confirmation_id().replace("CV-", "SR-")

        event_row = [
            eid, now, "Pending",
            organizer_name, organizer_email, organizer_org,
            organizer_role or "", org_website or "",
            event_name, event_website,
            str(event_start), str(event_end),
            event_city, event_country,
            event_format, expected_audience,
            ", ".join(community_alignment),
            event_description,
            how_heard if how_heard != "Select..." else "",
            additional_notes or "", "",
        ]
        request_row = [
            rid, now, "Pending", eid, event_name,
            speaker_topic, ", ".join(topic_tags),
            session_format if session_format != "Select..." else "",
            audience_level, cfp_link or "",
            str(cfp_deadline) if cfp_deadline else "", "", "",
        ]
        ok1 = append_row("Events", event_row)
        ok2 = append_row("Speaker_Requests", request_row)
        if ok1 and ok2:
            st.session_state["event_submitted"] = True
            st.session_state["event_id"] = eid
            st.rerun()
        else:
            st.error("Submission failed. Please try again or email community@snowflake.com.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Bulk upload
# ══════════════════════════════════════════════════════════════════════════════
with tab_bulk:
    st.markdown("### Upload multiple events at once")
    st.markdown(
        "Upload a **CSV**, **Excel (.xlsx)**, or paste a **Google Sheets URL** containing "
        "your event list. We'll preview the data before submitting."
    )

    # ── Template download ──────────────────────────────────────────────────────
    TEMPLATE_COLS = [
        "organizer_name", "organizer_email", "organizer_org", "organizer_role",
        "event_name", "event_website", "event_start", "event_end",
        "event_city", "event_country", "event_format", "expected_audience",
        "community_alignment", "event_description",
        "speaker_topic", "topic_tags", "session_format", "cfp_link", "cfp_deadline",
        "additional_notes",
    ]
    template_df = pd.DataFrame(columns=TEMPLATE_COLS)
    template_csv = template_df.to_csv(index=False)

    st.download_button(
        "Download CSV template",
        data=template_csv,
        file_name="community_voices_events_template.csv",
        mime="text/csv",
    )

    st.markdown("---")

    # ── Upload method selector ─────────────────────────────────────────────────
    upload_method = st.radio(
        "Upload method",
        ["Upload CSV or Excel file", "Paste Google Sheets URL"],
        horizontal=True,
    )

    df_upload = None

    if upload_method == "Upload CSV or Excel file":
        uploaded = st.file_uploader(
            "Choose your file",
            type=["csv", "xlsx", "xls"],
            help="CSV or Excel file. First row must be column headers.",
        )
        if uploaded:
            try:
                if uploaded.name.endswith(".csv"):
                    df_upload = pd.read_csv(uploaded, dtype=str).fillna("")
                else:
                    df_upload = pd.read_excel(uploaded, dtype=str).fillna("")
                st.success(f"Loaded {len(df_upload)} row(s) from **{uploaded.name}**")
            except Exception as e:
                st.error(f"Could not parse file: {e}")

    else:
        sheets_url = st.text_input(
            "Google Sheets URL",
            placeholder="https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit",
        )
        if sheets_url and st.button("Load from Google Sheets", key="load_gs"):
            try:
                # Extract spreadsheet ID from URL
                import re
                match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheets_url)
                if not match:
                    st.error("Could not find a spreadsheet ID in that URL.")
                else:
                    gs_id = match.group(1)
                    # Try to read the first sheet using the stored OAuth token
                    try:
                        token = get_access_token()
                        resp = requests.get(
                            f"https://sheets.googleapis.com/v4/spreadsheets/{gs_id}/values/A1:ZZ10000",
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=15,
                        )
                        resp.raise_for_status()
                        rows = resp.json().get("values", [])
                        if not rows or len(rows) < 2:
                            st.warning("Sheet appears to be empty or has only a header row.")
                        else:
                            headers = rows[0]
                            data = [r + [""] * (len(headers) - len(r)) for r in rows[1:]]
                            df_upload = pd.DataFrame(data, columns=headers).fillna("")
                            st.success(f"Loaded {len(df_upload)} row(s) from Google Sheets.")
                    except Exception as e:
                        # Try public CSV export as fallback (for publicly shared sheets)
                        try:
                            csv_url = f"https://docs.google.com/spreadsheets/d/{gs_id}/export?format=csv"
                            r2 = requests.get(csv_url, timeout=15)
                            r2.raise_for_status()
                            df_upload = pd.read_csv(StringIO(r2.text), dtype=str).fillna("")
                            st.success(f"Loaded {len(df_upload)} row(s) via public sheet export.")
                        except Exception as e2:
                            st.error(
                                f"Could not read the sheet. Make sure it's either shared with the "
                                f"program Google account or set to 'Anyone with the link can view'.\n\n"
                                f"Error: {e2}"
                            )
            except Exception as ex:
                st.error(f"Error: {ex}")

    # ── Preview & column mapping ───────────────────────────────────────────────
    if df_upload is not None and not df_upload.empty:
        st.markdown("---")
        st.markdown(f"### Preview — {len(df_upload)} event(s)")

        # Normalize column names
        df_upload.columns = [c.strip().lower().replace(" ", "_") for c in df_upload.columns]

        st.dataframe(df_upload, use_container_width=True, hide_index=True)

        # Check for required columns
        required_cols = {"event_name", "event_city", "event_country", "organizer_name", "organizer_email"}
        missing = required_cols - set(df_upload.columns)
        if missing:
            st.warning(
                f"Missing required columns: **{', '.join(sorted(missing))}**. "
                "These are needed to submit. Add them to your file or rename existing columns to match."
            )
        else:
            st.success("All required columns found. Ready to submit.")

            organizer_email_bulk = st.text_input(
                "Submitter email (for all events in this batch, if not in the file)",
                placeholder="your@email.com",
                key="bulk_email",
            )

            if st.button("Submit All Events", type="primary", use_container_width=True):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                success_count = 0
                errors = []

                progress = st.progress(0)
                for i, row in df_upload.iterrows():
                    try:
                        eid = generate_confirmation_id().replace("CV-", "EV-")
                        rid = generate_confirmation_id().replace("CV-", "SR-")

                        org_email = row.get("organizer_email", organizer_email_bulk or "")

                        event_row = [
                            eid, now, "Pending",
                            row.get("organizer_name", ""),
                            org_email,
                            row.get("organizer_org", row.get("organization", "")),
                            row.get("organizer_role", ""),
                            row.get("org_website", row.get("event_website", "")),
                            row.get("event_name", ""),
                            row.get("event_website", ""),
                            row.get("event_start", row.get("event_date", "")),
                            row.get("event_end", ""),
                            row.get("event_city", ""),
                            row.get("event_country", ""),
                            row.get("event_format", ""),
                            row.get("expected_audience", row.get("audience_size", "")),
                            row.get("community_alignment", ""),
                            row.get("event_description", row.get("description", "")),
                            row.get("how_heard", ""),
                            row.get("additional_notes", row.get("notes", "")),
                            "",  # admin_notes
                        ]
                        request_row = [
                            rid, now, "Pending", eid,
                            row.get("event_name", ""),
                            row.get("speaker_topic", row.get("topic", "")),
                            row.get("topic_tags", ""),
                            row.get("session_format", ""),
                            row.get("audience_level", ""),
                            row.get("cfp_link", ""),
                            row.get("cfp_deadline", ""),
                            "", "",
                        ]
                        ok1 = append_row("Events", event_row)
                        ok2 = append_row("Speaker_Requests", request_row)
                        if ok1 and ok2:
                            success_count += 1
                        else:
                            errors.append(f"Row {i+2}: Write failed")
                    except Exception as e:
                        errors.append(f"Row {i+2}: {e}")

                    progress.progress((i + 1) / len(df_upload))

                if errors:
                    for err in errors:
                        st.warning(err)

                if success_count > 0:
                    st.session_state["bulk_submitted"] = True
                    st.session_state["bulk_count"] = success_count
                    st.rerun()
                else:
                    st.error("No events were submitted successfully. Check the errors above.")
