"""Private file storage. Files are never shared by URL; the app streams them after authorization."""
from __future__ import annotations

import io
import os
import re
import tempfile
import threading
from typing import Callable, Protocol

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    base = os.path.basename(name or "file")
    cleaned = _SAFE.sub("_", base).strip("._") or "file"
    return cleaned[:120]


def object_path(event_id: str, item_id: str, version: int, file_sha256: str, filename: str) -> str:
    parts = [safe_name(event_id), safe_name(item_id), f"v{int(version)}"]
    return "/".join(parts) + f"/{file_sha256[:16]}_{safe_name(filename)}"


class FileStore(Protocol):
    def put(self, path: str, data: bytes) -> None: ...
    def get(self, path: str) -> bytes: ...


class MemoryFileStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail_next_put = False

    def put(self, path, data):
        if self.fail_next_put:
            self.fail_next_put = False
            raise RuntimeError("simulated storage failure")
        self.objects.setdefault(path, data)  # never overwrite

    def get(self, path):
        return self.objects[path]


class StageFileStore:
    """Snowflake internal stage (SNOWFLAKE_SSE). Paths are built only from sanitized parts."""

    def __init__(self, connect: Callable[[], object], stage: str = "WF_FILES", lock=None):
        self._connect = connect
        self._stage = stage
        self._conn = None
        self._lock = lock or threading.RLock()

    def _c(self):
        if self._conn is None or self._conn.is_closed():
            self._conn = self._connect()
        return self._conn

    @staticmethod
    def _check(path):
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", path) or ".." in path:
            raise ValueError("unsafe stage path")

    def put(self, path, data):
        self._check(path)
        directory, name = path.rsplit("/", 1)
        with self._lock:
            cur = self._c().cursor()
            try:
                # OVERWRITE=FALSE: an existing object at this versioned path is never replaced.
                cur.execute(f"PUT 'file:///{name}' '@{self._stage}/{directory}' "
                            f"AUTO_COMPRESS=FALSE OVERWRITE=FALSE", file_stream=io.BytesIO(data))
            finally:
                cur.close()

    def get(self, path):
        self._check(path)
        with self._lock, tempfile.TemporaryDirectory() as tmp:
            cur = self._c().cursor()
            try:
                cur.execute(f"GET '@{self._stage}/{path}' 'file://{tmp}/'")
            finally:
                cur.close()
            local = os.path.join(tmp, path.rsplit("/", 1)[1])
            with open(local, "rb") as fh:
                return fh.read()
