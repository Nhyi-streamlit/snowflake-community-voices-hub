"""Expense form uploads (Speaker Portal → Travel & expenses): files to Drive, a row in Expense_Forms, an email to Aba.

Speakers attach the completed expense form plus any receipts (photos, screenshots, PDFs) in one go. Every file goes
into "Community Voices Receipts/<expense id>" in Drive. The email to Aba has links only: no bank or payment details
are collected here. Tests inject `upload`, `append` and `send` so nothing reaches Google.
"""
from __future__ import annotations

import html
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

TAB = "Expense_Forms"
NOTIFY = "aba.micah@snowflake.com"
FILE_TYPES = ["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg", "heic", "webp", "doc", "docx"]
MAX_FILES = 10
MAX_MB = 20


@dataclass
class Result:
    saved: bool
    expense_id: str
    folder_link: str = ""
    failed_files: tuple = ()
    email_reason: str = ""          # "" = Aba was emailed


def _upload_default(expense_id: str, files: list[dict]) -> tuple[str, list[str], list[str]]:
    """(folder_link, file_links, failed_names)."""
    from utils.sheets import get_or_create_receipts_folder, upload_file_to_drive
    folder = get_or_create_receipts_folder(expense_id)
    if not folder:
        return "", [], [f["filename"] for f in files]
    links, failed = [], []
    for f in files:
        try:
            link = upload_file_to_drive(f["data"], f["filename"], f["mime_type"], folder)
        except Exception:
            link = None
        (links.append(link) if link else failed.append(f["filename"]))
    return f"https://drive.google.com/drive/folders/{folder}", links, failed


def _append_default(row: list) -> bool:
    from utils.sheets import append_row
    return append_row(TAB, row)


def _send_default(to: list[str], subject: str, body: str):
    from utils.sheets import send_gmail_result
    return send_gmail_result(to, subject, body)


def as_files(uploaded) -> list[dict]:
    """Streamlit UploadedFile list → [{filename, data, mime_type}]."""
    out = []
    for u in uploaded or []:
        out.append({"filename": u.name, "data": u.getvalue(),
                    "mime_type": u.type or mimetypes.guess_type(u.name)[0] or "application/octet-stream"})
    return out


def check(files: list[dict]) -> str:
    """"" when the files are acceptable, else a message for the speaker."""
    if not files:
        return "Attach your expense form or at least one receipt."
    if len(files) > MAX_FILES:
        return f"Attach up to {MAX_FILES} files at a time."
    big = [f["filename"] for f in files if len(f["data"]) > MAX_MB * 1024 * 1024]
    return f"These files are over {MAX_MB} MB: {', '.join(big)}" if big else ""


def submit(*, name: str, email: str, event: str, notes: str, files: list[dict],
           upload=None, append=None, send=None) -> Result:
    upload, append, send = upload or _upload_default, append or _append_default, send or _send_default
    eid = "EXP-2026-" + uuid.uuid4().hex[:8].upper()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        folder, links, failed = upload(eid, files)
    except Exception:
        folder, links, failed = "", [], [f["filename"] for f in files]
    if links and not failed:
        status = "Uploaded to Drive"
    elif links:
        status = f"Partly uploaded — missing: {', '.join(failed)}"
    else:
        status = "Upload failed — ask the speaker to email the files"
    names = "; ".join(f["filename"] for f in files)
    row = [eid, now, name.strip(), email.strip().lower(), event.strip(), names, folder or "; ".join(links),
           notes.strip(), status]
    if not append(row):
        return Result(False, eid)
    e = lambda v: html.escape(str(v or "")) or "—"   # noqa: E731
    file_list = "".join(f"<li><a href='{e(l)}'>{e(f['filename'])}</a></li>" for f, l in zip(
        [f for f in files if f["filename"] not in failed], links))
    file_list += "".join(f"<li>{e(n)} (upload failed)</li>" for n in failed)
    body = (f"<p>Hi Aba,</p><p><b>{e(name)}</b> submitted an expense form for <b>{e(event)}</b>.</p>"
            f"<table cellpadding='4'><tr><td><b>Expense ID</b></td><td>{e(eid)}</td></tr>"
            f"<tr><td><b>Email</b></td><td>{e(email)}</td></tr>"
            f"<tr><td><b>Submitted</b></td><td>{e(now)}</td></tr>"
            f"<tr><td><b>Status</b></td><td>{e(status)}</td></tr>"
            f"<tr><td style='vertical-align:top'><b>Notes</b></td><td style='white-space:pre-wrap'>{e(notes)}</td></tr>"
            "</table>"
            f"<p><b>Files</b></p><ul>{file_list}</ul>"
            + (f"<p><a href='{e(folder)}'>Open the Drive folder</a></p>" if folder else "")
            + "<p>Also saved in the hub sheet, tab Expense_Forms.</p>")
    r = send([NOTIFY], f"Expense form submitted · {name.strip()} · {event.strip()}", body)
    reason = "" if r else (getattr(r, "reason", "") or "send_failed")
    return Result(True, eid, folder, tuple(failed), reason)
