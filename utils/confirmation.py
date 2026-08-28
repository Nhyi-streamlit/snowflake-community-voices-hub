import uuid
from datetime import datetime


def generate_confirmation_id() -> str:
    """Generate a human-readable confirmation ID like CV-2026-A4F82E1B."""
    year = datetime.now().year
    suffix = uuid.uuid4().hex[:8].upper()
    return f"CV-{year}-{suffix}"
