# Shared Google Sheets authentication and CRUD helpers.
import os
import requests
import streamlit as st
import pandas as pd
from functools import lru_cache
from datetime import datetime


# ── Secret resolution ──────────────────────────────────────────────────────────

def _secrets() -> dict:
    keys = ["GOOGLE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "GOOGLE_SPREADSHEET_ID"]
    out = {}
    for k in keys:
        try:
            out[k] = st.secrets.get(k, "")
        except Exception:
            out[k] = os.environ.get(k, "")
    return out


# ── Access token (cached per ~55 min to avoid hammering token endpoint) ────────

_token_cache: dict = {"token": "", "expires": 0}

def get_access_token() -> str:
    import time
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    s = _secrets()
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": s["GOOGLE_CLIENT_ID"],
            "client_secret": s["GOOGLE_CLIENT_SECRET"],
            "refresh_token": s["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = now + data.get("expires_in", 3500) - 60
    return _token_cache["token"]


# ── Read ───────────────────────────────────────────────────────────────────────

def read_tab(tab: str, spreadsheet_id: str | None = None) -> pd.DataFrame:
    """Read all rows from a named sheet tab. Returns DataFrame (headers as columns).

    `spreadsheet_id` reads another spreadsheet the same Google account can see (default: the hub sheet).
    """
    s = _secrets()
    token = get_access_token()
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id or s['GOOGLE_SPREADSHEET_ID']}"
        f"/values/{requests.utils.quote(tab)}"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    rows = resp.json().get("values", [])
    if not rows or len(rows) < 2:
        return pd.DataFrame()
    headers = rows[0]
    data = rows[1:]
    # Pad short rows
    padded = [row + [""] * (len(headers) - len(row)) for row in data]
    return pd.DataFrame(padded, columns=headers)


def read_tab_raw(tab: str) -> list:
    """Return raw list-of-lists from a tab (including header row)."""
    s = _secrets()
    token = get_access_token()
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}"
        f"/values/{requests.utils.quote(tab)}"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("values", [])


# ── Append ─────────────────────────────────────────────────────────────────────

def append_row(tab: str, row: list) -> bool:
    """Append a single row to the given sheet tab. Returns True on success."""
    s = _secrets()
    if not all([s["GOOGLE_REFRESH_TOKEN"], s["GOOGLE_CLIENT_ID"],
                s["GOOGLE_CLIENT_SECRET"], s["GOOGLE_SPREADSHEET_ID"]]):
        return False
    try:
        token = get_access_token()
        resp = requests.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}"
            f"/values/{requests.utils.quote(tab)}!A1:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"values": [row]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Update (single cell or row) ───────────────────────────────────────────────

def update_cell(tab: str, sheet_row: int, col_letter: str, value: str) -> bool:
    """Update a single cell. sheet_row is 1-based (row 1 = header)."""
    s = _secrets()
    try:
        token = get_access_token()
        cell = f"{tab}!{col_letter}{sheet_row}"
        resp = requests.put(
            f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}"
            f"/values/{requests.utils.quote(cell)}",
            params={"valueInputOption": "RAW"},
            json={"values": [[value]]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


def update_row(tab: str, sheet_row: int, values: list) -> bool:
    """Overwrite a full row. sheet_row is 1-based (row 2 = first data row)."""
    s = _secrets()
    try:
        token = get_access_token()
        n_cols = len(values)
        end_col = chr(ord("A") + n_cols - 1) if n_cols <= 26 else "Z"
        cell_range = f"{tab}!A{sheet_row}:{end_col}{sheet_row}"
        resp = requests.put(
            f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}"
            f"/values/{requests.utils.quote(cell_range)}",
            params={"valueInputOption": "RAW"},
            json={"values": [values]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Uber code pool ─────────────────────────────────────────────────────────────

def claim_uber_code(email: str, tab_source: str) -> str | None:
    """Claim the next available Uber code from the Uber_Codes tab.

    Returns the code string on success, or None if no codes are available.
    The Uber_Codes tab must have columns: code, status, assigned_to_email,
    assigned_date, assigned_tab. Paste codes with status=AVAILABLE.
    """
    s = _secrets()
    token = get_access_token()
    sheet_id = s["GOOGLE_SPREADSHEET_ID"]

    # Read all rows
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"/values/{requests.utils.quote('Uber_Codes')}"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    rows = resp.json().get("values", [])
    if not rows or len(rows) < 2:
        return None

    # Find first AVAILABLE row (column B = status)
    for i, row in enumerate(rows[1:], start=2):  # sheet row 2+
        padded = row + [""] * (5 - len(row))
        if padded[1].strip().upper() == "AVAILABLE":
            code = padded[0].strip()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Update columns B-E in that row
            cell_range = f"Uber_Codes!B{i}:E{i}"
            requests.put(
                f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
                f"/values/{requests.utils.quote(cell_range)}",
                params={"valueInputOption": "RAW"},
                json={"values": [["USED", email, now, tab_source]]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            return code

    return None


# ── Gmail notification ─────────────────────────────────────────────────────────

def _gmail_token() -> str:
    """Cached access token; token-endpoint errors become TokenError with Google's reason."""
    from utils.gmail_diag import TokenError, parse_google_error
    try:
        return get_access_token()
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = {}
        status = e.response.status_code if e.response is not None else 0
        r = parse_google_error(status, body)
        raise TokenError(r.reason, r.detail, r.status) from None


_gmail_client = None


def gmail_client():
    """Process-wide Gmail client (keeps the last send result for the Email health panel)."""
    global _gmail_client
    if _gmail_client is None:
        from utils.gmail_diag import GmailClient
        _gmail_client = GmailClient(_secrets, requests.post, requests.get)
    return _gmail_client


def send_gmail_result(to: list[str], subject: str, body_html: str, cc: list[str] | None = None):
    """Send via Gmail API; returns a SendResult with a diagnosable `reason` on failure."""
    s = _secrets()
    if not (s["GOOGLE_CLIENT_ID"] and s["GOOGLE_CLIENT_SECRET"] and s["GOOGLE_REFRESH_TOKEN"]):
        return gmail_client().send(to, subject, body_html, cc=cc)   # records missing_credentials
    return gmail_client().send(to, subject, body_html, token_fn=_gmail_token, cc=cc)


def gmail_probe() -> dict:
    return gmail_client().probe(token_fn=_gmail_token)


def send_gmail(to: list[str], subject: str, body_html: str) -> bool:
    """Send an email via Gmail API. Returns True on success (see send_gmail_result for the reason)."""
    return bool(send_gmail_result(to, subject, body_html))


def send_gmail_with_attachments(
    to: list[str],
    subject: str,
    body_html: str,
    attachments: list[dict] | None = None,
) -> bool:
    """Send an email with optional file attachments via Gmail API.

    `attachments` is a list of dicts: {"filename": str, "data": bytes, "mime_type": str}
    e.g. {"filename": "receipt.pdf", "data": b"...", "mime_type": "application/pdf"}
    Returns True on success.
    """
    import base64
    import mimetypes
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    try:
        token = get_access_token()

        if attachments:
            msg = MIMEMultipart()
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject
            msg.attach(MIMEText(body_html, "html"))
            for att in attachments:
                main_type, sub_type = att.get("mime_type", "application/octet-stream").split("/", 1)
                part = MIMEBase(main_type, sub_type)
                part.set_payload(att["data"])
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=att["filename"],
                )
                msg.attach(part)
        else:
            msg = MIMEText(body_html, "html")
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Google Drive upload ────────────────────────────────────────────────────────

_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

_receipts_folder_cache: dict = {}


def _find_drive_folder(name: str, parent_id: str | None = None) -> str | None:
    """Search for a Drive folder by name. Returns folder ID or None."""
    token = get_access_token()
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = requests.get(
        _DRIVE_FILES_URL,
        params={"q": q, "fields": "files(id)", "pageSize": 1},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def _create_drive_folder(name: str, parent_id: str | None = None) -> str | None:
    """Create a Drive folder. Returns folder ID or None."""
    token = get_access_token()
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    resp = requests.post(
        _DRIVE_FILES_URL,
        json=metadata,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    return None


def get_or_create_receipts_folder(subfolder_name: str) -> str | None:
    """Get or create 'Community Voices Receipts/{subfolder_name}' in Drive.

    Returns the subfolder ID, or None on failure.
    """
    # Top-level folder (cached for the session)
    top_id = _receipts_folder_cache.get("top")
    if not top_id:
        top_id = _find_drive_folder("Community Voices Receipts")
        if not top_id:
            top_id = _create_drive_folder("Community Voices Receipts")
        if not top_id:
            return None
        _receipts_folder_cache["top"] = top_id

    # Per-reimbursement subfolder
    sub_id = _find_drive_folder(subfolder_name, parent_id=top_id)
    if not sub_id:
        sub_id = _create_drive_folder(subfolder_name, parent_id=top_id)
    return sub_id


def upload_file_to_drive(
    file_data: bytes, filename: str, mime_type: str, folder_id: str
) -> str | None:
    """Upload a file to a Drive folder and make it viewable via link.

    Returns the shareable webViewLink, or None on failure.
    """
    import json as _json

    token = get_access_token()
    metadata = {"name": filename, "parents": [folder_id]}
    # Multipart upload: metadata + file content
    boundary = "----ReceiptUploadBoundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{_json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n"
    ).encode()

    import base64 as _b64
    body += _b64.b64encode(file_data) + f"\r\n--{boundary}--\r\n".encode()

    resp = requests.post(
        _DRIVE_UPLOAD_URL,
        params={"uploadType": "multipart", "fields": "id,webViewLink"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=body,
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        return None
    file_id = resp.json().get("id")
    web_link = resp.json().get("webViewLink")

    # Return viewable link so it can be embedded in the spreadsheet
    return web_link or f"https://drive.google.com/file/d/{file_id}/view"


def upload_receipts_to_drive(
    reimb_id: str, files: list[dict]
) -> list[str]:
    """Upload receipt files to Drive under a reimbursement subfolder.

    `files` is a list of dicts: {"filename": str, "data": bytes, "mime_type": str}
    Returns a list of shareable links (may be shorter than input if uploads fail).
    """
    if not files:
        return []
    folder_id = get_or_create_receipts_folder(reimb_id)
    if not folder_id:
        return []
    links = []
    for f in files:
        link = upload_file_to_drive(f["data"], f["filename"], f["mime_type"], folder_id)
        if link:
            links.append(link)
    return links


# ── Column index helpers ───────────────────────────────────────────────────────

def col_letter(df: pd.DataFrame, col_name: str) -> str:
    """Return the spreadsheet column letter (A, B, ...) for a DataFrame column name."""
    try:
        idx = list(df.columns).index(col_name)
        if idx < 26:
            return chr(ord("A") + idx)
        return "A"  # fallback
    except ValueError:
        return "A"


# ── Whole-tab replace (small summary tabs such as Digest) ────────────────────────

def replace_tab(tab: str, rows: list[list]) -> bool:
    """Clear a tab and write `rows` (first row = headers). Returns True on success."""
    s = _secrets()
    try:
        token = get_access_token()
        base = f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}/values/"
        h = {"Authorization": f"Bearer {token}"}
        q = requests.utils.quote(tab)
        if requests.post(base + f"{q}:clear", headers=h, timeout=15).status_code != 200:
            return False
        resp = requests.put(base + f"{q}!A1", params={"valueInputOption": "RAW"},
                            json={"values": rows}, headers=h, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


# ── Google Doc from HTML (Drive upload with conversion) ─────────────────────────

def create_google_doc(title: str, html_body: str, folder_id: str | None = None):
    """Upload HTML converted to a Google Doc. Returns (url, reason); reason is "" on success.

    Uses the Drive scope receipts already rely on. A missing scope comes back as a reason such as
    ACCESS_TOKEN_SCOPE_INSUFFICIENT instead of an exception.
    """
    import json as _json
    from utils.gmail_diag import TokenError, parse_google_error
    try:
        token = _gmail_token()
    except TokenError as e:
        return "", e.reason
    except Exception:
        return "", "token_error"
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        meta["parents"] = [folder_id]
    boundary = "----RecapDocBoundary"
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{_json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html_body}\r\n--{boundary}--\r\n")
    try:
        resp = requests.post(_DRIVE_UPLOAD_URL, params={"uploadType": "multipart", "fields": "id,webViewLink"},
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": f"multipart/related; boundary={boundary}"},
                             data=body.encode("utf-8"), timeout=60)
    except Exception:
        return "", "network_error"
    if resp.status_code not in (200, 201):
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        return "", parse_google_error(resp.status_code, payload).reason
    d = resp.json()
    return d.get("webViewLink") or f"https://docs.google.com/document/d/{d.get('id')}/edit", ""
