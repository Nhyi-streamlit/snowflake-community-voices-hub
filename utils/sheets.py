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

def read_tab(tab: str) -> pd.DataFrame:
    """Read all rows from a named sheet tab. Returns DataFrame (headers as columns)."""
    s = _secrets()
    token = get_access_token()
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{s['GOOGLE_SPREADSHEET_ID']}"
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
