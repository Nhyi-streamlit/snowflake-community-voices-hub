"""Automatic checks on speaker content items (workflow store) plus the prompt for an advisory AI brand review.

Each check returns (status, message) with status "pass", "fail", or "manual" (couldn't check automatically).
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date

PASS, FAIL, MANUAL = "pass", "fail", "manual"
BIO_MIN, BIO_MAX = 50, 100
MIN_HEADSHOT_PX = 400
QR_MARKERS = re.compile(r"rate\s+this\s+talk|talk\s+feedback|speaker_portal\?speaker=|scan\s+to\s+rate", re.I)
REQUIRED_TYPES = ("bio", "headshot", "talk_details", "slides")

BRAND_RULES = ("Use correct product names (Snowflake, Snowpark, Streamlit, Cortex, Snowflake Horizon, Apache Iceberg). "
               "No roadmap dates, unreleased features, pricing, or competitor disparagement. "
               "Professional, practitioner tone. No customer names without permission.")


@dataclass
class CheckResult:
    item_type: str
    status: str
    message: str


@dataclass
class ItemReport:
    event_id: str
    event_name: str
    speaker: str
    item_id: str
    item_type: str
    title: str
    status: str
    due_date: date | None
    overdue: bool
    checks: list = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return self.overdue or any(c.status in (FAIL, MANUAL) for c in self.checks)


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text or ""))


def check_bio(text: dict) -> CheckResult:
    n = words(text.get("bio", ""))
    if BIO_MIN <= n <= BIO_MAX:
        return CheckResult("bio", PASS, f"{n} words")
    return CheckResult("bio", FAIL, f"{n} words (needs {BIO_MIN}–{BIO_MAX})")


def check_talk(text: dict) -> CheckResult:
    missing = [k for k in ("title", "abstract") if not str(text.get(k, "")).strip()]
    if missing:
        return CheckResult("talk_details", FAIL, "Missing " + " and ".join(missing))
    n = words(text.get("abstract", ""))
    return CheckResult("talk_details", PASS if n >= 25 else FAIL,
                       f"Abstract {n} words" + ("" if n >= 25 else " (aim for at least 25)"))


def check_headshot(data: bytes | None) -> CheckResult:
    if not data:
        return CheckResult("headshot", FAIL, "No headshot uploaded")
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(data)).size
    except Exception:
        return CheckResult("headshot", FAIL, "File isn't a readable image")
    if min(w, h) < MIN_HEADSHOT_PX:
        return CheckResult("headshot", FAIL, f"{w}×{h}px (needs at least {MIN_HEADSHOT_PX}px)")
    return CheckResult("headshot", PASS, f"{w}×{h}px")


def slide_text(name: str, data: bytes) -> str | None:
    """Extract text from PDF/PPTX; None if the format can't be read here."""
    lower = name.lower()
    try:
        if lower.endswith(".pptx"):
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(data))
            xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                           if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            return " ".join(re.findall(r"<a:t>([^<]*)</a:t>", xml))
        if lower.endswith(".pdf"):
            try:
                from pypdf import PdfReader
            except ImportError:
                return None
            return " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None
    return None


def check_slides(name: str, data: bytes | None) -> CheckResult:
    if not data:
        return CheckResult("slides", FAIL, "No slides uploaded")
    text = slide_text(name, data)
    if text is None:
        return CheckResult("slides", MANUAL, "Couldn't read this file type automatically. Check the QR slide by eye")
    if QR_MARKERS.search(text):
        return CheckResult("slides", PASS, "Feedback QR slide found")
    return CheckResult("slides", FAIL, "No feedback QR slide found (add the QR from After your talk)")


def run_checks(item, version, file_bytes: bytes | None) -> list[CheckResult]:
    if version is None:
        return [CheckResult(item.item_type, FAIL, "Not submitted yet")]
    text = json.loads(version.text_json or "{}")
    if item.item_type == "bio":
        return [check_bio(text)]
    if item.item_type == "talk_details":
        return [check_talk(text)]
    if item.item_type == "headshot":
        return [check_headshot(file_bytes)]
    if item.item_type == "slides":
        return [check_slides(version.file_name, file_bytes)]
    return []


def brand_prompt(item_type: str, content: str) -> str:
    return ("You review speaker content for a Snowflake community program. Brand rules: " + BRAND_RULES +
            f"\nReview this {item_type.replace('_', ' ')}. Reply in at most 2 short sentences: 'OK' if it follows the "
            "rules, otherwise the specific issue to fix. Do not rewrite it.\n---\n" + content[:3000])


def report(store, files, today: date) -> list[ItemReport]:
    """Reports for every required speaker item (read-only over the workflow store)."""
    from workflow.models import APPROVED, SPEAKER, SUBMITTED
    events = {e.event_id: e for e in store.list_events()}
    members = {}
    out = []
    for item in store.list_items(None):
        if item.party != SPEAKER or item.item_type not in REQUIRED_TYPES or item.event_id not in events:
            continue
        if item.event_id not in members:
            members[item.event_id] = {m.member_id: m for m in store.list_members(event_id=item.event_id)}
        m = members[item.event_id].get(item.assignee_member_id)
        versions = store.list_versions(item.item_id)
        v = max(versions, key=lambda x: x.version) if versions else None
        data = None
        if v is not None and v.file_path:
            try:
                data = files.get(v.file_path)
            except Exception:
                data = None
        checks = [] if item.status == APPROVED else run_checks(item, v, data)
        overdue = bool(item.due_date and item.due_date < today and item.status not in (SUBMITTED, APPROVED))
        out.append(ItemReport(item.event_id, events[item.event_id].name,
                              (m.display_name or m.email) if m else "", item.item_id, item.item_type, item.title,
                              item.status, item.due_date, overdue, checks))
    return sorted(out, key=lambda r: (not r.overdue, r.due_date or date.max))
