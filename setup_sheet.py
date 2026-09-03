"""
Run this once to create all sheet tabs and headers in the new Google Sheet.
Usage: python setup_sheet.py
Set GOOGLE_REFRESH_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SPREADSHEET_ID env vars first.
"""
import os, requests


def get_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "grant_type":    "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_sheet_ids(sid, token):
    resp = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in resp.json().get("sheets", [])}


def add_sheet(sid, token, title):
    resp = requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"  Created tab: {title}")


def write_headers(sid, token, tab, headers):
    resp = requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{requests.utils.quote(tab)}!A1",
        params={"valueInputOption": "RAW"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"values": [headers]},
        timeout=10,
    )
    if resp.status_code == 200:
        print(f"  Headers written to: {tab}")
    else:
        print(f"  ERROR writing headers to {tab}: {resp.text}")


TABS = {
    "Speaker_Applications": [
        "confirmation_id", "submitted_at", "status",
        "first_name", "last_name", "email",
        "job_title", "company", "linkedin",
        "country", "city",
        "community_identity", "years_snowflake", "bio",
        "event_name", "event_website",
        "event_date_start", "event_date_end",
        "event_city", "event_country",
        "event_type", "audience_size",
        "talk_title", "talk_abstract",
        "session_type", "audience_level",
        "snowflake_topics",
        "support_types",
        "traveling_from",
        "estimated_cost",
        "additional_notes",
        "admin_notes",
        "matched_event",
    ],
    "Events": [
        "event_id", "submitted_at", "status",
        "organizer_name", "organizer_email", "organizer_org",
        "organizer_role", "org_website",
        "event_name", "event_website",
        "event_start", "event_end",
        "event_city", "event_country",
        "event_format", "expected_audience",
        "community_alignment",
        "event_description",
        "how_heard",
        "additional_notes",
        "admin_notes",
    ],
    "Speaker_Requests": [
        "request_id", "submitted_at", "status",
        "event_id", "event_name",
        "speaker_topic",
        "topic_tags",
        "session_format",
        "audience_level",
        "cfp_link",
        "cfp_deadline",
        "matched_speaker",
        "admin_notes",
    ],
    "Talk_Feedback": [
        "submission_id", "submitted_at",
        "speaker_name", "event_name", "talk_title", "talk_date",
        "rating_overall", "rating_content", "rating_delivery", "rating_relevance",
        "most_valuable",
        "would_attend_again",
        "community_interest",
        "interested_areas",
        "respondent_name",
        "respondent_email",
        "other_feedback",
    ],
    "Program_Resources": [
        "resource_type", "title", "url", "description", "last_updated",
    ],
    "Travel_Details": [
        "request_id", "submitted_at", "name", "email",
        "event_name", "event_city", "event_date",
        "passport_name", "dob", "passport_no", "passport_exp", "nationality", "phone",
        "fly_from", "fly_to", "outbound_date", "return_date", "seat_class",
        "airline_pref", "ff_number",
        "hotel_checkin", "hotel_checkout", "hotel_pref",
        "hotel_loyalty", "hotel_notes",
        "dietary", "emergency_name", "emergency_phone",
        "notes", "uber_code", "status",
    ],
    "Uber_Requests": [
        "request_id", "submitted_at", "name", "email",
        "event_name", "event_city", "event_date",
        "rides_needed", "amount_usd", "notes", "uber_code", "status",
    ],
    "Uber_Codes": [
        "code", "status", "assigned_to_email", "assigned_date", "assigned_tab",
    ],
}


if __name__ == "__main__":
    sid = os.environ.get("GOOGLE_SPREADSHEET_ID")
    if not sid:
        print("ERROR: Set GOOGLE_SPREADSHEET_ID environment variable.")
        raise SystemExit(1)

    print(f"Setting up spreadsheet: {sid}")
    token = get_token()
    existing = get_sheet_ids(sid, token)
    print(f"Existing tabs: {list(existing.keys())}")

    for tab, headers in TABS.items():
        if tab not in existing:
            add_sheet(sid, token, tab)
        else:
            print(f"  Tab already exists: {tab}")
        write_headers(sid, token, tab, headers)

    print("\nDone. Spreadsheet is ready.")
