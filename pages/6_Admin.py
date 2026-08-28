import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date, timedelta
from io import StringIO
import streamlit as st
import pandas as pd
import requests
from utils.styles import inject_css
from utils.sheets import read_tab, update_cell, append_row, col_letter, get_access_token
from utils.confirmation import generate_confirmation_id

st.set_page_config(
    page_title="Admin — Community Voices",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Q3 targets ────────────────────────────────────────────────────────────────
Q3_TARGETS = {
    "Speakers Supported":  25,
    "3P Events":           20,
    "Partners":            4,
    "Satisfaction (avg)":  4.0,
    "Meetups + Conf":      6,
}

STATUS_OPTIONS = ["Pending", "Approved", "Waitlisted", "Not a Fit"]

# ── Password gate ─────────────────────────────────────────────────────────────
if not st.session_state.get("admin_auth"):
    st.markdown("""
    <div class="page-hero" style="max-width:480px; margin:60px auto 0;">
      <div class="eyebrow">Admin Portal</div>
      <h1>Sign in</h1>
      <p>This page is restricted to the Community Voices program team.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("admin_login", clear_on_submit=False):
        pw = st.text_input("Password", type="password")
        login = st.form_submit_button("Sign In", type="primary", use_container_width=True)

    if login:
        expected = ""
        try:
            expected = st.secrets.get("ADMIN_PASSWORD", "community2026")
        except Exception:
            expected = os.environ.get("ADMIN_PASSWORD", "community2026")

        if pw == expected:
            st.session_state["admin_auth"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

# ── Authenticated ─────────────────────────────────────────────────────────────
if st.button("Sign out", key="logout"):
    st.session_state["admin_auth"] = False
    st.rerun()

st.markdown("""
<div class="page-hero">
  <div class="eyebrow">Admin Portal</div>
  <h1>Community Voices — Command Center</h1>
  <p>Manage applications, events, speaker matches, and program analytics.</p>
</div>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_data():
    out = {}
    for tab in ["Speaker_Applications", "Events", "Speaker_Requests", "Talk_Feedback"]:
        try:
            out[tab] = read_tab(tab)
        except Exception as e:
            out[tab] = pd.DataFrame()
            out[f"{tab}_error"] = str(e)
    return out

data = load_data()

if st.button("Refresh data", key="refresh"):
    st.cache_data.clear()
    st.rerun()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_apps, tab_events, tab_matches, tab_q3, tab_feedback, tab_comms, tab_upload, tab_navan = st.tabs([
    "Applications Queue",
    "Vendor Events",
    "Speaker-Event Matches",
    "Q3 Progress",
    "Talk Feedback",
    "Comms Generator",
    "Bulk Upload",
    "✈️ Navan Travel",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: Applications Queue
# ═══════════════════════════════════════════════════════════════════════════════
with tab_apps:
    df_apps = data.get("Speaker_Applications", pd.DataFrame())

    if df_apps.empty:
        st.info("No applications yet. They'll appear here once submitted.")
    else:
        # ── New signups notification ───────────────────────────────────────────
        if "submitted_at" in df_apps.columns:
            try:
                cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                new_signups = df_apps[
                    (df_apps["submitted_at"] >= cutoff) &
                    (df_apps.get("status", pd.Series(dtype=str)) == "Pending")
                ]
                if not new_signups.empty:
                    names = ", ".join(
                        f"{r.get('first_name','')} {r.get('last_name','')}".strip()
                        for _, r in new_signups.iterrows()
                    )
                    st.warning(
                        f"**{len(new_signups)} new application(s) in the last 24 hours:** {names}",
                        icon="🔔",
                    )
            except Exception:
                pass

        # ── Filter bar ────────────────────────────────────────────────────────
        col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
        with col_f1:
            status_filter = st.multiselect(
                "Filter by status",
                STATUS_OPTIONS + ["All"],
                default=["Pending"],
                key="app_status_filter",
            )
        with col_f2:
            search = st.text_input("Search name or event", key="app_search")
        with col_f3:
            st.markdown("&nbsp;")

        filtered = df_apps.copy()
        if status_filter and "All" not in status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]
        if search:
            mask = (
                filtered.apply(
                    lambda r: search.lower() in str(r.get("first_name", "")).lower()
                    or search.lower() in str(r.get("last_name", "")).lower()
                    or search.lower() in str(r.get("event_name", "")).lower(),
                    axis=1,
                )
            )
            filtered = filtered[mask]

        st.markdown(f"**{len(filtered)} application(s)**")

        # ── Per-row display ───────────────────────────────────────────────────
        for idx, row in filtered.iterrows():
            sheet_row = idx + 2  # row 1 = header, data starts at 2
            status = row.get("status", "Pending")
            cid    = row.get("confirmation_id", "")
            name   = f"{row.get('first_name','')} {row.get('last_name','')}".strip()
            event  = row.get("event_name", "")
            city   = row.get("event_city", "")
            country= row.get("event_country", "")
            talk   = row.get("talk_title", "")
            support= row.get("support_types", "")
            submitted = row.get("submitted_at", "")

            badge_map = {
                "Pending":    ("🟡", "#B7791F"),
                "Approved":   ("🟢", "#276749"),
                "Waitlisted": ("🔵", "#2B6CB0"),
                "Not a Fit":  ("🔴", "#9B2335"),
            }
            icon, color = badge_map.get(status, ("⚪", "#718096"))

            with st.expander(f"{icon} **{name}** — {event} ({city}, {country}) · {cid}"):
                c_detail, c_actions = st.columns([2, 1])

                with c_detail:
                    st.markdown(f"**Talk:** {talk}")
                    st.markdown(f"**Support requested:** {support}")
                    st.markdown(f"**Community:** {row.get('community_identity','')}")
                    st.markdown(f"**Email:** {row.get('email','')}")
                    st.markdown(f"**Event date:** {row.get('event_date_start','')} — {row.get('event_date_end','')}")
                    st.markdown(f"**Estimated cost:** ${row.get('estimated_cost','0')}")
                    st.markdown(f"**Submitted:** {submitted}")
                    bio_text = row.get("bio", "")
                    if bio_text:
                        st.markdown(f"**Bio:** {bio_text}")
                    notes = row.get("admin_notes", "")
                    if notes:
                        st.info(f"Admin notes: {notes}")

                with c_actions:
                    new_status = st.selectbox(
                        "Status",
                        STATUS_OPTIONS,
                        index=STATUS_OPTIONS.index(status) if status in STATUS_OPTIONS else 0,
                        key=f"status_{cid}",
                    )
                    new_notes = st.text_area(
                        "Admin notes",
                        value=row.get("admin_notes", ""),
                        height=80,
                        key=f"notes_{cid}",
                        placeholder="Internal notes (visible to speaker on Status page)...",
                    )

                    if st.button("Save changes", key=f"save_{cid}", type="primary"):
                        status_col = col_letter(df_apps, "status")
                        notes_col  = col_letter(df_apps, "admin_notes")
                        ok1 = update_cell("Speaker_Applications", sheet_row, status_col, new_status)
                        ok2 = update_cell("Speaker_Applications", sheet_row, notes_col, new_notes)
                        if ok1 and ok2:
                            st.success("Updated!")
                            st.cache_data.clear()
                        else:
                            st.error("Update failed — check Google Sheets credentials.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: Vendor Events
# ═══════════════════════════════════════════════════════════════════════════════
with tab_events:
    df_events = data.get("Events", pd.DataFrame())
    df_requests = data.get("Speaker_Requests", pd.DataFrame())

    if df_events.empty:
        st.info("No vendor events registered yet.")
    else:
        ev_status_filter = st.multiselect(
            "Filter by status",
            STATUS_OPTIONS + ["All"],
            default=["Pending"],
            key="ev_status_filter",
        )
        filtered_ev = df_events.copy()
        if ev_status_filter and "All" not in ev_status_filter:
            filtered_ev = filtered_ev[filtered_ev["status"].isin(ev_status_filter)]

        st.markdown(f"**{len(filtered_ev)} event(s)**")

        for idx, row in filtered_ev.iterrows():
            sheet_row = idx + 2
            eid    = row.get("event_id", "")
            org    = row.get("organizer_name", "")
            e_name = row.get("event_name", "")
            e_date = row.get("event_start", "")
            e_city = row.get("event_city", "")
            status = row.get("status", "Pending")

            icon = {"Pending": "🟡", "Approved": "🟢", "Waitlisted": "🔵", "Not a Fit": "🔴"}.get(status, "⚪")

            with st.expander(f"{icon} **{e_name}** — {e_city} · {e_date} · {org}"):
                c_ev1, c_ev2 = st.columns([2, 1])

                with c_ev1:
                    st.markdown(f"**Organizer:** {org} ({row.get('organizer_org','')})")
                    st.markdown(f"**Email:** {row.get('organizer_email','')}")
                    st.markdown(f"**Dates:** {e_date} → {row.get('event_end','')}")
                    st.markdown(f"**Location:** {e_city}, {row.get('event_country','')}")
                    st.markdown(f"**Format:** {row.get('event_format','')}")
                    st.markdown(f"**Audience:** {row.get('expected_audience','')} — {row.get('community_alignment','')}")
                    st.markdown(f"**Description:** {row.get('event_description','')}")

                    # Show linked speaker request
                    if not df_requests.empty and "event_id" in df_requests.columns:
                        req = df_requests[df_requests["event_id"] == eid]
                        if not req.empty:
                            st.markdown("---")
                            st.markdown("**Speaker Request:**")
                            st.markdown(f"> {req.iloc[0].get('speaker_topic','')}")
                            st.markdown(f"Topics: {req.iloc[0].get('topic_tags','')} | Format: {req.iloc[0].get('session_format','')}")

                with c_ev2:
                    new_ev_status = st.selectbox(
                        "Status",
                        STATUS_OPTIONS,
                        index=STATUS_OPTIONS.index(status) if status in STATUS_OPTIONS else 0,
                        key=f"ev_status_{eid}",
                    )
                    new_ev_notes = st.text_area(
                        "Admin notes",
                        value=row.get("admin_notes", ""),
                        height=80,
                        key=f"ev_notes_{eid}",
                    )
                    if st.button("Save", key=f"ev_save_{eid}", type="primary"):
                        sc = col_letter(df_events, "status")
                        nc = col_letter(df_events, "admin_notes")
                        ok = update_cell("Events", sheet_row, sc, new_ev_status) and \
                             update_cell("Events", sheet_row, nc, new_ev_notes)
                        if ok:
                            st.success("Updated!")
                            st.cache_data.clear()
                        else:
                            st.error("Update failed.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: Speaker-Event Matches
# ═══════════════════════════════════════════════════════════════════════════════
with tab_matches:
    st.markdown("### Match approved speakers to approved events")
    st.markdown(
        "Select an approved event and an approved speaker to record a match. "
        "This updates both records and generates welcome email copy."
    )

    df_apps_all = data.get("Speaker_Applications", pd.DataFrame())
    df_ev_all   = data.get("Events", pd.DataFrame())

    approved_speakers = pd.DataFrame()
    approved_events   = pd.DataFrame()

    if not df_apps_all.empty and "status" in df_apps_all.columns:
        approved_speakers = df_apps_all[df_apps_all["status"] == "Approved"].copy()
    if not df_ev_all.empty and "status" in df_ev_all.columns:
        approved_events = df_ev_all[df_ev_all["status"] == "Approved"].copy()

    if approved_speakers.empty:
        st.warning("No approved speakers yet.")
    elif approved_events.empty:
        st.info("No approved vendor events yet — matches will be available once an event is approved.")
    else:
        cm1, cm2 = st.columns(2)
        with cm1:
            spk_options = {
                f"{r.get('first_name','')} {r.get('last_name','')} — {r.get('event_name','')}": r.get("confirmation_id","")
                for _, r in approved_speakers.iterrows()
            }
            spk_label = st.selectbox("Approved speaker", list(spk_options.keys()), key="match_spk")
            selected_spk_cid = spk_options.get(spk_label, "")

        with cm2:
            ev_options = {
                f"{r.get('event_name','')} — {r.get('event_city','')}": r.get("event_id","")
                for _, r in approved_events.iterrows()
            }
            ev_label = st.selectbox("Approved vendor event", list(ev_options.keys()), key="match_ev")
            selected_ev_id = ev_options.get(ev_label, "")

        match_notes = st.text_area("Match notes (internal)", height=70, key="match_notes")

        if st.button("Record Match", type="primary", key="record_match"):
            # Update matched_event on speaker row
            if not df_apps_all.empty and "confirmation_id" in df_apps_all.columns:
                spk_rows = df_apps_all[df_apps_all["confirmation_id"] == selected_spk_cid]
                if not spk_rows.empty:
                    spk_idx = spk_rows.index[0]
                    mc = col_letter(df_apps_all, "matched_event")
                    update_cell("Speaker_Applications", spk_idx + 2, mc, selected_ev_id)

            # Update matched_speaker on speaker request row
            if not df_requests.empty and "event_id" in df_requests.columns:
                req_rows = df_requests[df_requests["event_id"] == selected_ev_id]
                if not req_rows.empty:
                    req_idx = req_rows.index[0]
                    msc = col_letter(df_requests, "matched_speaker")
                    update_cell("Speaker_Requests", req_idx + 2, msc, selected_spk_cid)

            st.success(f"Match recorded: {spk_label} ↔ {ev_label}")
            st.cache_data.clear()

    # Existing matches
    st.markdown("---")
    st.markdown("### Existing matches")
    if not df_apps_all.empty and "matched_event" in df_apps_all.columns:
        matched = df_apps_all[df_apps_all["matched_event"].str.strip().ne("")]
        if matched.empty:
            st.caption("No matches yet.")
        else:
            for _, r in matched.iterrows():
                st.markdown(
                    f"- **{r.get('first_name','')} {r.get('last_name','')}** "
                    f"→ Event {r.get('matched_event','')} "
                    f"(talk: {r.get('talk_title','')})"
                )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: Q3 Progress
# ═══════════════════════════════════════════════════════════════════════════════
with tab_q3:
    st.markdown("### Q3 2026 Program Goals")

    df_apps_q = data.get("Speaker_Applications", pd.DataFrame())
    df_feedback_q = data.get("Talk_Feedback", pd.DataFrame())

    # Derive actuals from live data
    actuals = {
        "Speakers Supported": 0,
        "3P Events": 0,
        "Partners": 0,
        "Satisfaction (avg)": 0.0,
        "Meetups + Conf": 0,
    }

    if not df_apps_q.empty and "status" in df_apps_q.columns:
        approved = df_apps_q[df_apps_q["status"] == "Approved"]
        actuals["Speakers Supported"] = len(approved)
        if "event_name" in approved.columns:
            actuals["3P Events"] = approved["event_name"].nunique()

    if not df_feedback_q.empty and "rating_overall" in df_feedback_q.columns:
        try:
            ratings = pd.to_numeric(df_feedback_q["rating_overall"], errors="coerce").dropna()
            if len(ratings) > 0:
                actuals["Satisfaction (avg)"] = round(ratings.mean(), 2)
        except Exception:
            pass

    # Display
    cols = st.columns(len(Q3_TARGETS))
    for i, (metric, target) in enumerate(Q3_TARGETS.items()):
        actual = actuals.get(metric, 0)
        with cols[i]:
            st.markdown(f"""
            <div class="stat-card">
              <div class="num">{actual}</div>
              <div class="label">{metric}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    for metric, target in Q3_TARGETS.items():
        actual = actuals.get(metric, 0)
        if isinstance(target, float):
            pct = min(actual / target, 1.0) if target > 0 else 0
            label = f"{metric}: {actual} / {target}"
        else:
            pct = min(actual / target, 1.0) if target > 0 else 0
            label = f"{metric}: {actual} / {target}"
        st.markdown(f"**{label}**")
        st.progress(float(pct))

    # Manual overrides
    st.markdown("---")
    st.markdown("### Manual overrides (metrics not yet tracked in the sheet)")
    with st.form("q3_manual"):
        c_o1, c_o2 = st.columns(2)
        with c_o1:
            partners_manual  = st.number_input("Partners (actual)", min_value=0, max_value=100, value=0)
        with c_o2:
            meetups_manual   = st.number_input("Meetups + Conf (actual)", min_value=0, max_value=100, value=0)
        st.form_submit_button("Update display")

    # Re-render with manual overrides
    if partners_manual or meetups_manual:
        actuals["Partners"] = partners_manual
        actuals["Meetups + Conf"] = meetups_manual
        for metric in ["Partners", "Meetups + Conf"]:
            target = Q3_TARGETS[metric]
            actual = actuals[metric]
            pct = min(actual / target, 1.0) if target > 0 else 0
            st.markdown(f"**{metric}: {actual} / {target}** (updated)")
            st.progress(float(pct))

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: Talk Feedback
# ═══════════════════════════════════════════════════════════════════════════════
with tab_feedback:
    df_fb = data.get("Talk_Feedback", pd.DataFrame())

    if df_fb.empty:
        st.info("No feedback collected yet.")
    else:
        # Summary metrics
        numeric_cols = ["rating_overall", "rating_content", "rating_delivery", "rating_relevance"]
        for col in numeric_cols:
            if col in df_fb.columns:
                df_fb[col] = pd.to_numeric(df_fb[col], errors="coerce")

        cm_f1, cm_f2, cm_f3, cm_f4 = st.columns(4)
        with cm_f1:
            st.metric("Total responses", len(df_fb))
        with cm_f2:
            if "rating_overall" in df_fb.columns:
                st.metric("Avg overall", f"{df_fb['rating_overall'].mean():.1f} / 5")
        with cm_f3:
            if "rating_content" in df_fb.columns:
                st.metric("Avg content", f"{df_fb['rating_content'].mean():.1f} / 5")
        with cm_f4:
            if "rating_delivery" in df_fb.columns:
                st.metric("Avg delivery", f"{df_fb['rating_delivery'].mean():.1f} / 5")

        # Per-speaker rollup
        if "speaker_name" in df_fb.columns:
            st.markdown("### By speaker")
            spk_fb = (
                df_fb.groupby("speaker_name")
                .agg(
                    Responses=("rating_overall", "count"),
                    Avg_Overall=("rating_overall", "mean"),
                    Avg_Content=("rating_content", "mean"),
                    Avg_Delivery=("rating_delivery", "mean"),
                )
                .round(2)
                .reset_index()
                .sort_values("Avg_Overall", ascending=False)
            )
            st.dataframe(spk_fb, use_container_width=True, hide_index=True)

        # Free text responses
        if "most_valuable" in df_fb.columns:
            st.markdown("### What audiences found most valuable")
            for v in df_fb["most_valuable"].dropna():
                if str(v).strip():
                    st.markdown(f"> {v}")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6: Comms Generator
# ═══════════════════════════════════════════════════════════════════════════════
with tab_comms:
    st.markdown("### Welcome email generator")
    st.markdown("Select an approved speaker to generate a welcome email draft.")

    df_apps_cm = data.get("Speaker_Applications", pd.DataFrame())

    if df_apps_cm.empty or "status" not in df_apps_cm.columns:
        st.info("No applications loaded.")
    else:
        approved_cm = df_apps_cm[df_apps_cm["status"] == "Approved"]
        if approved_cm.empty:
            st.warning("No approved speakers yet.")
        else:
            spk_cm_options = {
                f"{r.get('first_name','')} {r.get('last_name','')} — {r.get('event_name','')}": idx
                for idx, r in approved_cm.iterrows()
            }
            selected_label = st.selectbox("Select speaker", list(spk_cm_options.keys()))
            selected_idx   = spk_cm_options[selected_label]
            r = approved_cm.loc[selected_idx]

            email_draft = f"""Subject: Welcome to Snowflake Community Voices — {r.get('event_name','')} 🎉

Hi {r.get('first_name','[Name]')},

Congratulations — your Community Voices application has been approved!

We're thrilled to support you at {r.get('event_name','[Event]')} in {r.get('event_city','[City]')}, {r.get('event_country','[Country]')}.

**Your talk:** {r.get('talk_title','[Talk Title]')}

**Next steps:**
1. Check the Speaker Resources page for brand assets, slide templates, and prep guides:
   [APP_URL]/Resources
2. Generate your feedback QR code before your talk:
   [APP_URL]/Feedback
3. If travel support was approved, our team will follow up separately with booking instructions.

We're excited to have you represent the Snowflake community on stage. Please reply to this email with any questions.

Talk soon,
Aba Micah
Community Voices Program Manager
Snowflake | community@snowflake.com
"""
            st.text_area("Email draft (click to copy)", value=email_draft, height=380, key="email_draft_text")
            st.caption("Replace [APP_URL] with the deployed app URL before sending.")

    st.markdown("---")
    st.markdown("### Rejection email generator")
    df_apps_rej = data.get("Speaker_Applications", pd.DataFrame())
    if not df_apps_rej.empty and "status" in df_apps_rej.columns:
        not_fit = df_apps_rej[df_apps_rej["status"] == "Not a Fit"]
        if not not_fit.empty:
            rej_options = {
                f"{r.get('first_name','')} {r.get('last_name','')} — {r.get('event_name','')}": idx
                for idx, r in not_fit.iterrows()
            }
            rej_label = st.selectbox("Select applicant", list(rej_options.keys()), key="rej_select")
            rej_idx   = rej_options[rej_label]
            r2 = not_fit.loc[rej_idx]

            rej_draft = f"""Subject: Your Community Voices Application — {r2.get('event_name','')}

Hi {r2.get('first_name','[Name]')},

Thank you for applying to the Snowflake Community Voices program for {r2.get('event_name','[Event]')}.

After reviewing your application, we're not able to provide program support for this particular event.
This decision doesn't reflect on the quality of your work or your standing in the community —
availability and fit vary significantly by event and timing.

We'd love to see you apply again for a future event. Your profile stays in our system and we
review all applicants on an ongoing basis.

In the meantime, the Speaker Resources page has templates and guides available to all community members:
[APP_URL]/Resources

Thank you for being part of the Snowflake community.

Aba Micah
Community Voices Program Manager
Snowflake | community@snowflake.com
"""
            st.text_area("Rejection draft", value=rej_draft, height=300, key="rej_draft_text")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7: Bulk Upload (Admin — events and speaker applications)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.markdown("### Bulk upload events or speaker applications")
    st.markdown(
        "Upload a **CSV**, **Excel (.xlsx)**, or paste a **Google Sheets URL**. "
        "Choose whether you're uploading **Events** (from vendors) or **Speaker Applications**."
    )

    upload_type = st.radio(
        "What are you uploading?",
        ["Events (from vendors)", "Speaker Applications"],
        horizontal=True,
        key="admin_upload_type",
    )

    TEMPLATE_EVENTS = [
        "organizer_name", "organizer_email", "organizer_org", "organizer_role",
        "event_name", "event_website", "event_start", "event_end",
        "event_city", "event_country", "event_format", "expected_audience",
        "community_alignment", "event_description",
        "speaker_topic", "topic_tags", "session_format", "cfp_link", "cfp_deadline",
        "additional_notes",
    ]
    TEMPLATE_SPEAKERS = [
        "first_name", "last_name", "email", "job_title", "company", "country", "city",
        "community_identity", "bio",
        "event_name", "event_city", "event_country", "event_date_start",
        "talk_title", "talk_abstract", "session_type",
        "support_types", "estimated_cost",
    ]

    cols_for_template = TEMPLATE_EVENTS if "Events" in upload_type else TEMPLATE_SPEAKERS
    template_csv = pd.DataFrame(columns=cols_for_template).to_csv(index=False)
    st.download_button(
        f"Download {'Events' if 'Events' in upload_type else 'Speaker Applications'} CSV template",
        data=template_csv,
        file_name=f"cv_{'events' if 'Events' in upload_type else 'speakers'}_template.csv",
        mime="text/csv",
        key="admin_template_dl",
    )

    st.markdown("---")
    admin_upload_method = st.radio(
        "Upload method",
        ["Upload CSV or Excel file", "Paste Google Sheets URL"],
        horizontal=True,
        key="admin_upload_method",
    )

    df_admin_upload = None

    if admin_upload_method == "Upload CSV or Excel file":
        admin_file = st.file_uploader(
            "Choose file",
            type=["csv", "xlsx", "xls"],
            key="admin_file_upload",
        )
        if admin_file:
            try:
                if admin_file.name.endswith(".csv"):
                    df_admin_upload = pd.read_csv(admin_file, dtype=str).fillna("")
                else:
                    df_admin_upload = pd.read_excel(admin_file, dtype=str).fillna("")
                st.success(f"Loaded {len(df_admin_upload)} row(s) from **{admin_file.name}**")
            except Exception as e:
                st.error(f"Could not parse file: {e}")
    else:
        admin_gs_url = st.text_input(
            "Google Sheets URL",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key="admin_gs_url",
        )
        if admin_gs_url and st.button("Load Sheet", key="admin_load_gs"):
            import re
            match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", admin_gs_url)
            if not match:
                st.error("Could not extract spreadsheet ID from that URL.")
            else:
                gs_id = match.group(1)
                try:
                    token = get_access_token()
                    resp = requests.get(
                        f"https://sheets.googleapis.com/v4/spreadsheets/{gs_id}/values/A1:ZZ10000",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    rows = resp.json().get("values", [])
                    if rows and len(rows) >= 2:
                        headers = rows[0]
                        data = [r + [""] * (len(headers) - len(r)) for r in rows[1:]]
                        df_admin_upload = pd.DataFrame(data, columns=headers).fillna("")
                        st.success(f"Loaded {len(df_admin_upload)} row(s)")
                    else:
                        st.warning("Sheet is empty or header-only.")
                except Exception as e:
                    try:
                        csv_url = f"https://docs.google.com/spreadsheets/d/{gs_id}/export?format=csv"
                        r2 = requests.get(csv_url, timeout=15)
                        r2.raise_for_status()
                        from io import StringIO
                        df_admin_upload = pd.read_csv(StringIO(r2.text), dtype=str).fillna("")
                        st.success(f"Loaded {len(df_admin_upload)} row(s) via public export")
                    except Exception as e2:
                        st.error(f"Could not read sheet: {e2}")

    if df_admin_upload is not None and not df_admin_upload.empty:
        df_admin_upload.columns = [c.strip().lower().replace(" ", "_") for c in df_admin_upload.columns]
        st.markdown("---")
        st.markdown(f"**Preview — {len(df_admin_upload)} row(s)**")
        st.dataframe(df_admin_upload, use_container_width=True, hide_index=True)

        upload_status = st.selectbox(
            "Set initial status for all rows",
            ["Pending", "Approved"],
            key="admin_upload_status",
        )

        if st.button("Submit All Rows", type="primary", key="admin_bulk_submit"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ok_count = 0
            prog = st.progress(0)

            if "Events" in upload_type:
                for i, row in df_admin_upload.iterrows():
                    eid = generate_confirmation_id().replace("CV-", "EV-")
                    rid = generate_confirmation_id().replace("CV-", "SR-")
                    event_row = [
                        eid, now, upload_status,
                        row.get("organizer_name",""), row.get("organizer_email",""),
                        row.get("organizer_org", row.get("organization","")),
                        row.get("organizer_role",""), row.get("org_website",""),
                        row.get("event_name",""), row.get("event_website",""),
                        row.get("event_start", row.get("event_date","")), row.get("event_end",""),
                        row.get("event_city",""), row.get("event_country",""),
                        row.get("event_format",""), row.get("expected_audience", row.get("audience_size","")),
                        row.get("community_alignment",""), row.get("event_description", row.get("description","")),
                        row.get("how_heard",""), row.get("additional_notes", row.get("notes","")), "",
                    ]
                    request_row = [
                        rid, now, upload_status, eid, row.get("event_name",""),
                        row.get("speaker_topic", row.get("topic","")), row.get("topic_tags",""),
                        row.get("session_format",""), row.get("audience_level",""),
                        row.get("cfp_link",""), row.get("cfp_deadline",""), "", "",
                    ]
                    if append_row("Events", event_row) and append_row("Speaker_Requests", request_row):
                        ok_count += 1
                    prog.progress((i + 1) / len(df_admin_upload))
            else:
                for i, row in df_admin_upload.iterrows():
                    cid = generate_confirmation_id()
                    spk_row = [
                        cid, now, upload_status,
                        row.get("first_name",""), row.get("last_name",""), row.get("email",""),
                        row.get("job_title",""), row.get("company",""), row.get("linkedin",""),
                        row.get("country",""), row.get("city",""),
                        row.get("community_identity",""), row.get("years_snowflake",""), row.get("bio",""),
                        row.get("event_name",""), row.get("event_website",""),
                        row.get("event_date_start",""), row.get("event_date_end",""),
                        row.get("event_city",""), row.get("event_country",""),
                        row.get("event_type",""), row.get("audience_size",""),
                        row.get("talk_title",""), row.get("talk_abstract",""),
                        row.get("session_type",""), row.get("audience_level",""),
                        row.get("snowflake_topics",""), row.get("support_types",""),
                        row.get("traveling_from",""), row.get("estimated_cost","0"),
                        row.get("additional_notes",""), "", "",
                    ]
                    if append_row("Speaker_Applications", spk_row):
                        ok_count += 1
                    prog.progress((i + 1) / len(df_admin_upload))

            st.success(f"Submitted {ok_count} of {len(df_admin_upload)} row(s) successfully.")
            st.cache_data.clear()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8: Navan Travel Requests
# ═══════════════════════════════════════════════════════════════════════════════
with tab_navan:
    st.markdown("""
    <div class="info-card" style="border-color:#0E2346; background:linear-gradient(135deg,#EBF8FF,#F0F9FF);">
      <h4>Navan Travel Request Hub</h4>
      <p>
        Approved speakers who requested travel support are listed below.
        Generate formatted trip requests to send to Navan, export a batch CSV,
        or mark requests as submitted once you've raised them in Navan.
      </p>
    </div>
    """, unsafe_allow_html=True)

    df_navan_apps = data.get("Speaker_Applications", pd.DataFrame())

    # Filter: approved + requested travel/hotel
    TRAVEL_KEYWORDS = ["travel", "flight", "hotel", "accommodation", "registration"]

    if df_navan_apps.empty or "status" not in df_navan_apps.columns:
        st.info("No applications loaded.")
    else:
        approved_apps = df_navan_apps[df_navan_apps["status"] == "Approved"].copy()

        # Filter to those who want travel support
        if "support_types" in approved_apps.columns:
            travel_mask = approved_apps["support_types"].str.lower().str.contains(
                "|".join(TRAVEL_KEYWORDS), na=False
            )
            travel_apps = approved_apps[travel_mask].copy()
        else:
            travel_apps = approved_apps.copy()

        # Separate already-sent from pending
        if "admin_notes" in travel_apps.columns:
            sent_mask    = travel_apps["admin_notes"].str.contains("Navan: sent", na=False)
            pending_apps = travel_apps[~sent_mask].copy()
            sent_apps    = travel_apps[sent_mask].copy()
        else:
            pending_apps = travel_apps.copy()
            sent_apps    = pd.DataFrame()

        # ── Summary metrics ────────────────────────────────────────────────────
        mn1, mn2, mn3 = st.columns(3)
        with mn1:
            st.metric("Pending Navan requests", len(pending_apps))
        with mn2:
            st.metric("Sent to Navan", len(sent_apps))
        with mn3:
            try:
                total_cost = pd.to_numeric(travel_apps.get("estimated_cost", pd.Series(dtype=str)), errors="coerce").sum()
                st.metric("Total est. travel cost", f"${total_cost:,.0f}")
            except Exception:
                st.metric("Total est. travel cost", "—")

        st.markdown("---")

        # ── Export all pending as CSV ──────────────────────────────────────────
        if not pending_apps.empty:
            # Build Navan-compatible CSV columns
            navan_rows = []
            for _, r in pending_apps.iterrows():
                full_name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
                navan_rows.append({
                    "traveler_name":       full_name,
                    "traveler_email":      r.get("email", ""),
                    "trip_purpose":        f"Speaking: {r.get('talk_title', r.get('event_name',''))}",
                    "event_name":          r.get("event_name", ""),
                    "origin_city":         r.get("traveling_from", r.get("city", "")),
                    "destination_city":    r.get("event_city", ""),
                    "destination_country": r.get("event_country", ""),
                    "departure_date":      r.get("event_date_start", ""),
                    "return_date":         r.get("event_date_end", r.get("event_date_start", "")),
                    "estimated_cost_usd":  r.get("estimated_cost", "0"),
                    "support_requested":   r.get("support_types", ""),
                    "confirmation_id":     r.get("confirmation_id", ""),
                    "notes":               r.get("additional_notes", ""),
                })
            navan_df = pd.DataFrame(navan_rows)
            csv_bytes = navan_df.to_csv(index=False).encode()

            st.download_button(
                f"Export {len(pending_apps)} pending request(s) as Navan CSV",
                data=csv_bytes,
                file_name=f"navan_travel_requests_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                type="primary",
                key="navan_export",
            )

        st.markdown("---")

        # ── Per-request cards ──────────────────────────────────────────────────
        if pending_apps.empty:
            st.info("No pending travel requests.")
        else:
            st.markdown(f"### {len(pending_apps)} pending request(s)")

            for idx, r in pending_apps.iterrows():
                sheet_row  = idx + 2
                full_name  = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
                email      = r.get("email", "")
                event_name = r.get("event_name", "")
                event_city = r.get("event_city", "")
                event_country = r.get("event_country", "")
                dep_date   = r.get("event_date_start", "")
                ret_date   = r.get("event_date_end", dep_date)
                origin     = r.get("traveling_from", r.get("city", ""))
                cost       = r.get("estimated_cost", "0")
                support    = r.get("support_types", "")
                talk       = r.get("talk_title", "")
                cid        = r.get("confirmation_id", "")

                with st.expander(f"✈️ **{full_name}** — {event_name} ({event_city}) · {dep_date}"):
                    col_detail, col_actions = st.columns([2, 1])

                    with col_detail:
                        st.markdown(f"""
                        | Field | Value |
                        |-------|-------|
                        | **Traveler** | {full_name} |
                        | **Email** | {email} |
                        | **Talk** | {talk} |
                        | **Event** | {event_name} |
                        | **Destination** | {event_city}, {event_country} |
                        | **Departure date** | {dep_date} |
                        | **Return date** | {ret_date} |
                        | **Traveling from** | {origin} |
                        | **Support requested** | {support} |
                        | **Est. cost (USD)** | ${cost} |
                        | **Confirmation ID** | {cid} |
                        """)

                    with col_actions:
                        # Navan email template
                        navan_email = f"""Hi Navan team,

Please book the following trip for a Snowflake Community Voices speaker:

Traveler: {full_name}
Email: {email}
Trip: Speaking at {event_name}
Talk: {talk}

Travel details:
- Origin: {origin}
- Destination: {event_city}, {event_country}
- Outbound: {dep_date}
- Return: {ret_date}
- Support needed: {support}
- Budget: ~${cost} USD

Reference ID: {cid}

Please confirm once booked. Any questions, reply to this email.

Thanks,
Aba Micah
Community Voices Program, Snowflake"""

                        st.text_area(
                            "Navan email template",
                            value=navan_email,
                            height=260,
                            key=f"navan_email_{cid}",
                            help="Copy and send to your Navan travel coordinator.",
                        )

                        if st.button(
                            "Mark as sent to Navan",
                            key=f"navan_sent_{cid}",
                            type="primary",
                        ):
                            sent_note = f"Navan: sent {datetime.now().strftime('%Y-%m-%d')}"
                            existing_notes = r.get("admin_notes", "")
                            new_notes = f"{existing_notes} | {sent_note}".strip(" |")
                            notes_col = col_letter(df_navan_apps, "admin_notes")
                            if update_cell("Speaker_Applications", sheet_row, notes_col, new_notes):
                                st.success("Marked as sent!")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Could not update — check Sheets connection.")

        # ── Already sent ───────────────────────────────────────────────────────
        if not sent_apps.empty:
            st.markdown("---")
            with st.expander(f"Requests already sent to Navan ({len(sent_apps)})"):
                for _, r in sent_apps.iterrows():
                    full_name  = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
                    event_name = r.get("event_name", "")
                    dep_date   = r.get("event_date_start", "")
                    notes      = r.get("admin_notes", "")
                    sent_date  = notes.split("Navan: sent")[-1].strip().split("|")[0].strip() if "Navan: sent" in notes else ""
                    st.markdown(f"- ✅ **{full_name}** — {event_name} ({dep_date}){' · sent ' + sent_date if sent_date else ''}")

