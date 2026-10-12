"""Count people in event photos with the open-source YOLOX-S detector (Apache-2.0).

Runs on CPU via onnxruntime inside the Streamlit app — no external API, photos never
leave the app. The model (~36 MB) is downloaded once and cached on disk.
Large photos are also scanned in overlapping tiles so small, distant people are found.
"""
import hashlib
import os
import tempfile
import urllib.request
from io import BytesIO

import numpy as np

MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx"
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
MODEL_PATH = os.path.join(tempfile.gettempdir(), "cv_yolox_s.onnx")
INPUT = 640
PERSON = 0  # COCO class id
SCORE_MIN = 0.35
IOU_MAX = 0.5


def _download_model() -> str:
    if os.path.exists(MODEL_PATH) and _sha(MODEL_PATH) == MODEL_SHA256:
        return MODEL_PATH
    tmp = MODEL_PATH + ".part"
    urllib.request.urlretrieve(MODEL_URL, tmp)
    if _sha(tmp) != MODEL_SHA256:
        os.remove(tmp)
        raise RuntimeError("Downloaded detection model failed its integrity check")
    os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_session():
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    return ort.InferenceSession(_download_model(), opts, providers=["CPUExecutionProvider"])


def _grids():
    grids, strides = [], []
    for s in (8, 16, 32):
        n = INPUT // s
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids), np.concatenate(strides)


_GRID, _STRIDE = _grids()


def _detect(session, img) -> np.ndarray:
    """Person boxes [x1, y1, x2, y2, score] in the coordinates of `img` (PIL RGB)."""
    w, h = img.size
    r = min(INPUT / w, INPUT / h)
    resized = img.resize((max(1, int(w * r)), max(1, int(h * r))))
    canvas = np.full((INPUT, INPUT, 3), 114, dtype=np.float32)
    arr = np.asarray(resized, dtype=np.float32)[:, :, ::-1]  # RGB -> BGR (YOLOX training format)
    canvas[: arr.shape[0], : arr.shape[1]] = arr
    blob = canvas.transpose(2, 0, 1)[None]
    out = session.run(None, {session.get_inputs()[0].name: blob})[0][0]

    xy = (out[:, :2] + _GRID) * _STRIDE
    wh = np.exp(out[:, 2:4]) * _STRIDE
    score = out[:, 4] * out[:, 5 + PERSON]
    keep = score >= SCORE_MIN
    xy, wh, score = xy[keep], wh[keep], score[keep]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
    return np.concatenate([boxes, score[:, None]], 1)


def _nms(dets: np.ndarray) -> np.ndarray:
    if len(dets) == 0:
        return dets
    x1, y1, x2, y2, s = dets.T
    area = (x2 - x1) * (y2 - y1)
    order, keep = s.argsort()[::-1], []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        # Also drop boxes mostly contained in the kept one (tile-edge duplicates).
        small = np.minimum(area[i], area[order[1:]])
        dup = (inter / (area[i] + area[order[1:]] - inter) > IOU_MAX) | (inter / small > 0.8)
        order = order[1:][~dup]
    return dets[keep]


def count_people(session, data: bytes, max_dim: int = 2560) -> dict:
    """Return {'count', 'confidence', 'notes'} for one photo."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    w, h = img.size
    dets = [_detect(session, img)]
    if max(w, h) > INPUT * 1.5:
        # 2x2 overlapping tiles give distant faces enough pixels to be detected.
        tw, th = int(w * 0.6), int(h * 0.6)
        for ox in (0, w - tw):
            for oy in (0, h - th):
                d = _detect(session, img.crop((ox, oy, ox + tw, oy + th)))
                d[:, [0, 2]] += ox
                d[:, [1, 3]] += oy
                dets.append(d)
    final = _nms(np.concatenate(dets))
    n = len(final)
    mean = float(final[:, 4].mean()) if n else 0.0
    confidence = "high" if n and mean >= 0.6 else "medium" if n and mean >= 0.45 else "low"
    notes = f"Detected {n} people" + (" — dense crowds may be undercounted; adjust if needed" if n >= 40 else "")
    return {"count": n, "confidence": confidence, "notes": notes, "boxes": final[:, :4].round().astype(int).tolist()}
