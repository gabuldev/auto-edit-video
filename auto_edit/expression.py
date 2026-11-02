"""How expressive the face in a frame is, for picking the thumbnail's face
frame (tools/thumbnailer.py). A smiling or surprised face sells the click; a
blank stare or closed eyes does not.

Optional: needs the ``expression`` extra (``pip install "auto-edit-video[expression]"``,
which brings mediapipe). MediaPipe's Face Landmarker (Apache-2.0, 3.7 MB) is
downloaded the first time into ~/.auto-edit/models and checked by SHA-256.
Without mediapipe — or on any failure — :func:`score` returns None and the
thumbnailer keeps its usual frame score, unchanged.
"""
from __future__ import annotations

import importlib.util

import numpy as np

from auto_edit import face_cutout

MODEL_NAME = "face_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
MAX_SIDE = 640  # landmarks need no more than this; keeps 13 candidates fast

_landmarker = None
_failed = False  # one failure (no model, no network) → stop trying for this run


def available() -> bool:
    """mediapipe is installed (the optional extra)."""
    try:
        return importlib.util.find_spec("mediapipe") is not None
    except (ImportError, ValueError):
        return False


def expressiveness(blendshapes: dict[str, float]) -> float:
    """0..1 from MediaPipe's face blendshapes: a smile, or wide eyes with
    raised brows (surprise). Closed eyes sink it — a blink is the worst
    thumbnail face there is."""
    g = blendshapes.get
    smile = (g("mouthSmileLeft", 0.0) + g("mouthSmileRight", 0.0)) / 2
    eyes = (g("eyeWideLeft", 0.0) + g("eyeWideRight", 0.0)) / 2
    brows = g("browInnerUp", 0.0)
    surprise = 0.6 * eyes + 0.4 * brows
    blink = (g("eyeBlinkLeft", 0.0) + g("eyeBlinkRight", 0.0)) / 2
    value = max(smile, surprise) * (1.0 - min(1.0, max(0.0, blink - 0.3) / 0.4))
    return float(min(1.0, max(0.0, value)))


def _ensure_model(download=None):
    return face_cutout._ensure(face_cutout.models_dir() / MODEL_NAME, MODEL_URL, MODEL_SHA256, download)


def _get_landmarker(download=None):
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks.python import BaseOptions, vision

        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(_ensure_model(download))),
            output_face_blendshapes=True,
            num_faces=1,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def blendshapes(rgb: np.ndarray, download=None) -> dict[str, float] | None:
    """The face's blendshapes ({name: 0..1}), or None (no face / no mediapipe)."""
    import mediapipe as mp

    h, w = rgb.shape[:2]
    if max(h, w) > MAX_SIDE:
        from PIL import Image

        k = MAX_SIDE / max(h, w)
        rgb = np.array(Image.fromarray(rgb).resize((max(1, int(w * k)), max(1, int(h * k)))))
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb[:, :, :3], dtype=np.uint8))
    result = _get_landmarker(download).detect(image)
    if not result.face_blendshapes:
        return None
    return {c.category_name: float(c.score) for c in result.face_blendshapes[0]}


def score(rgb: np.ndarray, download=None) -> float | None:
    """Expressiveness of the face in an RGB frame (0..1); 0.0 when the frame
    has no face; None when it can't be measured (no mediapipe, model failed) —
    then the caller scores the frame as it always did."""
    global _failed
    if _failed or not available():
        return None
    try:
        shapes = blendshapes(rgb, download)
    except Exception as exc:  # noqa: BLE001 — an optional scorer never costs the thumbnail
        _failed = True
        print(f"[expression] indisponível ({type(exc).__name__}: {exc}) — score de rosto sem expressão")
        return None
    return 0.0 if shapes is None else expressiveness(shapes)
