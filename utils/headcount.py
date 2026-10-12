"""Event headcount: count attendees in event photos with Cortex AI_COMPLETE.

Uses the [connections.cv_headcount] secret (a dedicated service user; speakers never
get Snowflake credentials). Object names are unqualified and resolve against that
connection's database/schema. See migrations/002_headcount_schema.sql.
"""
import json
import re
import threading
import uuid
from io import BytesIO

MODEL = "claude-sonnet-4-5"
STAGE = "HEADCOUNT_PHOTOS"
MAX_DIM = 2048  # the vision model returns nothing for very large originals
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

COUNT_PROMPT = (
    "You are counting attendance at an event. Count every distinct person visible in this photo, "
    "including people partially visible, seated, in the background, or on stage. Do not count people "
    "shown on screens, posters, or reflections. Respond ONLY with JSON with keys count (integer), "
    "confidence (one of high, medium, low), notes (one short sentence)."
)

_lock = threading.Lock()


def connection_params(secrets) -> dict:
    try:
        return dict((secrets.get("connections", {}) or {}).get("cv_headcount", {}) or {})
    except Exception:
        return {}


def connect(params: dict):
    import snowflake.connector
    return snowflake.connector.connect(**params, paramstyle="qmark", client_session_keep_alive=True)


def prepare_image(data: bytes) -> bytes:
    """Downscale to MAX_DIM and re-encode as JPEG (also strips EXIF/GPS metadata)."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(BytesIO(data)))
    img.thumbnail((MAX_DIM, MAX_DIM))
    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


def parse_count_response(raw) -> dict:
    if raw is None:
        return {"count": None, "confidence": "low", "notes": "Model returned no result — enter a manual count"}
    text = raw if isinstance(raw, str) else json.dumps(raw)
    try:
        decoded = json.loads(text)
        if isinstance(decoded, str):
            text = decoded
        elif isinstance(decoded, dict):
            return _normalise(decoded)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return _normalise(json.loads(m.group(0)))
        except ValueError:
            pass
    n = re.search(r"\d+", text)
    return {"count": int(n.group(0)) if n else None, "confidence": "low", "notes": "Could not parse model output"}


def _normalise(obj: dict) -> dict:
    try:
        count = max(0, round(float(obj.get("count"))))
    except (TypeError, ValueError):
        count = None
    return {
        "count": count,
        "confidence": str(obj.get("confidence", "low")).lower()[:10],
        "notes": str(obj.get("notes", ""))[:500],
    }


class HeadcountStore:
    def __init__(self, conn):
        self._conn = conn

    def _q(self, sql, params=()):
        with _lock:
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []
            finally:
                cur.close()

    def create_event(self, owner_email, name, event_date, location) -> str:
        eid = str(uuid.uuid4())
        self._q(
            "INSERT INTO HEADCOUNT_EVENTS (EVENT_ID, OWNER_EMAIL, EVENT_NAME, EVENT_DATE, LOCATION) VALUES (?, ?, ?, ?, ?)",
            (eid, owner_email, name, event_date, location),
        )
        return eid

    def list_events(self, owner_email):
        rows = self._q(
            """SELECT e.EVENT_ID, e.EVENT_NAME, e.EVENT_DATE, e.LOCATION, e.REPORTED_ATTENDANCE,
                      COUNT(p.PHOTO_ID), MAX(COALESCE(p.MANUAL_COUNT, p.PEOPLE_COUNT)),
                      SUM(COALESCE(p.MANUAL_COUNT, p.PEOPLE_COUNT))
               FROM HEADCOUNT_EVENTS e LEFT JOIN HEADCOUNT_PHOTOS p ON p.EVENT_ID = e.EVENT_ID
               WHERE e.OWNER_EMAIL = ?
               GROUP BY ALL ORDER BY e.EVENT_DATE DESC NULLS LAST, MAX(e.CREATED_AT) DESC""",
            (owner_email,),
        )
        keys = ["id", "name", "date", "location", "reported", "photos", "peak", "total"]
        return [dict(zip(keys, r)) for r in rows]

    def _owns(self, owner_email, event_id) -> bool:
        return bool(self._q("SELECT 1 FROM HEADCOUNT_EVENTS WHERE EVENT_ID = ? AND OWNER_EMAIL = ?", (event_id, owner_email)))

    def list_photos(self, owner_email, event_id):
        if not self._owns(owner_email, event_id):
            return []
        rows = self._q(
            "SELECT PHOTO_ID, FILE_NAME, PEOPLE_COUNT, MANUAL_COUNT, CONFIDENCE, NOTES FROM HEADCOUNT_PHOTOS WHERE EVENT_ID = ? ORDER BY CREATED_AT",
            (event_id,),
        )
        keys = ["id", "file_name", "ai_count", "manual_count", "confidence", "notes"]
        return [dict(zip(keys, r)) for r in rows]

    def add_photo(self, owner_email, event_id, file_name, data: bytes) -> dict:
        if not self._owns(owner_email, event_id):
            raise PermissionError("Event not found")
        photo_id = str(uuid.uuid4())
        # Generated names only — user-supplied text never goes into PUT/TO_FILE paths.
        stage_path = f"{event_id}/{photo_id}.jpg"
        with _lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"PUT file:///{photo_id}.jpg @{STAGE}/{event_id}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE",
                    file_stream=BytesIO(prepare_image(data)),
                )
            finally:
                cur.close()
        self._q(f"ALTER STAGE {STAGE} REFRESH")
        raw = self._q(f"SELECT AI_COMPLETE(?, ?, TO_FILE('@{STAGE}', ?))", (MODEL, COUNT_PROMPT, stage_path))
        result = parse_count_response(raw[0][0] if raw else None)
        self._q(
            """INSERT INTO HEADCOUNT_PHOTOS (PHOTO_ID, EVENT_ID, FILE_PATH, FILE_NAME, PEOPLE_COUNT, CONFIDENCE, NOTES, MODEL)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (photo_id, event_id, stage_path, file_name[:255], result["count"], result["confidence"], result["notes"], MODEL),
        )
        return result

    def set_manual(self, owner_email, event_id, photo_id, value):
        if self._owns(owner_email, event_id):
            self._q("UPDATE HEADCOUNT_PHOTOS SET MANUAL_COUNT = ? WHERE PHOTO_ID = ? AND EVENT_ID = ?", (value, photo_id, event_id))

    def set_reported(self, owner_email, event_id, value):
        self._q("UPDATE HEADCOUNT_EVENTS SET REPORTED_ATTENDANCE = ? WHERE EVENT_ID = ? AND OWNER_EMAIL = ?", (value, event_id, owner_email))

    def delete_event(self, owner_email, event_id):
        if not self._owns(owner_email, event_id):
            return
        self._q(f"REMOVE @{STAGE}/{event_id}/")
        self._q("DELETE FROM HEADCOUNT_PHOTOS WHERE EVENT_ID = ?", (event_id,))
        self._q("DELETE FROM HEADCOUNT_EVENTS WHERE EVENT_ID = ?", (event_id,))
