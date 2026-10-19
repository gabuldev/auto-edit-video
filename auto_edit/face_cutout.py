"""The person cut out of a video frame, for the thumbnail layouts' {{rosto}}
and {{rosto_contorno}} slots (auto_edit/thumb_html.py).

U²-Net trained on people (u2net_human_seg, Apache-2.0) run with onnxruntime,
only on a frame where a face shows (Ultra-Light-Fast-Generic-Face-Detector,
MIT, 1.2 MB): the person mask alone happily cuts out a lone hand. Both models
are downloaded the first time they are needed, into ~/.auto-edit/models, and
checked by SHA-256. Every failure is a CutoutError:
callers then draw the thumbnail without the face.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from auto_edit import config as cfg

MODEL_NAME = "u2net_human_seg.onnx"
MODEL_URL = f"https://github.com/danielgatis/rembg/releases/download/v0.0.0/{MODEL_NAME}"
MODEL_SHA256 = "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c"
INPUT = 320
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
MIN_PERSON = 0.03  # of the frame: less than this is nobody
MAX_SIDE = 1600  # frames are shrunk to this before cutting (thumbnail size is 1280x720)

FACE_MODEL_NAME = "ultraface-rfb-320.onnx"
FACE_MODEL_URL = ("https://raw.githubusercontent.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB/"
                  "master/models/onnx/version-RFB-320.onnx")
FACE_MODEL_SHA256 = "34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017"
FACE_INPUT = (320, 240)
FACE_MIN_SCORE = 0.9  # real faces score ~1.0; a thumbs-up ~0.8


class CutoutError(RuntimeError):
    pass


def models_dir() -> Path:
    return cfg.home_dir() / "models"


def model_path() -> Path:
    return models_dir() / MODEL_NAME


def face_model_path() -> Path:
    return models_dir() / FACE_MODEL_NAME


def model_ready() -> bool:
    return model_path().is_file() and face_model_path().is_file()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _urlretrieve(url: str, dest: Path) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)


_download_lock = threading.Lock()


def ensure_model(download=None) -> Path:
    """The person-mask model, downloading it first if needed."""
    return _ensure(model_path(), MODEL_URL, MODEL_SHA256, download)


def ensure_face_model(download=None) -> Path:
    """The face detector, downloading it first if needed."""
    return _ensure(face_model_path(), FACE_MODEL_URL, FACE_MODEL_SHA256, download)


def _ensure(path: Path, url: str, sha256: str, download=None) -> Path:
    """A model file, downloaded into a .part that only becomes the model when
    its hash matches."""
    if path.is_file():
        return path
    with _download_lock:
        if path.is_file():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        try:
            (download or _urlretrieve)(url, part)
            if _sha256(part) != sha256:
                raise CutoutError("o modelo de recorte baixado veio corrompido")
            part.replace(path)
        except CutoutError:
            raise
        except Exception as exc:
            raise CutoutError(f"não deu pra baixar o modelo de recorte ({exc})") from exc
        finally:
            part.unlink(missing_ok=True)
    return path


def download_in_background() -> None:
    """Start fetching the model without waiting (the Estilos preview)."""
    if model_ready() or _download_lock.locked():
        return

    def run():
        try:
            ensure_face_model()
            ensure_model()
        except CutoutError as exc:
            print(f"[face_cutout] {exc}")

    threading.Thread(target=run, name="face-model-download", daemon=True).start()


_session = None
_face_session = None


def _load(path_of, download=None):
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise CutoutError("onnxruntime não instalado") from exc
    path = path_of(download)
    try:
        opts = ort.SessionOptions()
        opts.log_severity_level = 3  # the face model's export warns about every weight
        return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise CutoutError(f"modelo de recorte inválido ({exc})") from exc


def session(download=None):
    """The person-mask ONNX session (one per process)."""
    global _session
    if _session is None:
        _session = _load(ensure_model, download)
    return _session


def face_session(download=None):
    """The face detector ONNX session (one per process)."""
    global _face_session
    if _face_session is None:
        _face_session = _load(ensure_face_model, download)
    return _face_session


def _face(img: Image.Image, sess) -> tuple[float, tuple[float, float, float, float]] | None:
    """(score, box as fractions of the frame) of the surest face, or None when
    nothing passes for one."""
    x = (np.asarray(img.convert("RGB").resize(FACE_INPUT, Image.BILINEAR), dtype=np.float32) - 127.0) / 128.0
    scores, boxes = sess.run(None, {sess.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})
    p = scores[0, :, 1]
    i = int(p.argmax())
    if float(p[i]) < FACE_MIN_SCORE:
        return None
    return float(p[i]), tuple(float(v) for v in np.clip(boxes[0, i], 0, 1))


def _mask(img: Image.Image, sess) -> Image.Image:
    """The person mask (L, same size as `img`)."""
    x = np.asarray(img.convert("RGB").resize((INPUT, INPUT), Image.LANCZOS), dtype=np.float32) / 255.0
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    m = (out - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(out)
    return Image.fromarray((m * 255).astype(np.uint8), "L").resize(img.size, Image.LANCZOS)


def _open(frame) -> Image.Image:
    img = frame if isinstance(frame, Image.Image) else Image.open(frame)
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


def _coverage(mask: Image.Image) -> float:
    return float((np.asarray(mask) > 128).mean())


def _crop(img: Image.Image, mask: Image.Image) -> Image.Image | None:
    if _coverage(mask) < MIN_PERSON:
        return None
    box = mask.point(lambda v: 255 if v > 128 else 0).getbbox()
    if box is None:
        return None
    pad = round(max(img.size) * 0.01)
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad))
    cut = img.copy()
    cut.putalpha(mask)
    return cut.crop(box)


def cutout(frame, *, session=None) -> Image.Image | None:
    """The person in `frame` (path or image) as RGBA cropped to them, or None
    when there's nobody big enough in it."""
    img = _open(frame)
    return _crop(img, _mask(img, session or globals()["session"]()))


def outlined(cut: Image.Image, px: int | None = None) -> Image.Image:
    """The cut-out with a thick white outline (the classic thumbnail look),
    baked into the PNG: Satori can't outline an image's shape."""
    px = px or max(6, round(cut.height * 0.025))
    w, h = cut.width + 2 * px, cut.height + 2 * px
    alpha = Image.new("L", (w, h), 0)
    alpha.paste(cut.getchannel("A").point(lambda v: 255 if v > 100 else 0), (px, px))
    # Dilate by ~px in one pass: blur, then keep everything the blur reached.
    ring = alpha.filter(ImageFilter.GaussianBlur(px / 2)).point(lambda v: 255 if v > 6 else 0)
    out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    out.putalpha(ring)
    out.alpha_composite(cut, (px, px))
    return out


def cutout_files(frames: list[Path], folder: Path) -> dict | None:
    """{"rosto", "rosto_contorno"} PNGs from the frame with the biggest face
    (cached by the frames' content), or None when no frame shows a face or
    nobody is big enough. Raises CutoutError when a model can't run."""
    frames = [Path(f) for f in frames if Path(f).is_file()]
    if not frames:
        return None
    key = hashlib.sha1(b"face-v2" + b"".join(hashlib.sha1(f.read_bytes()).digest() for f in frames)).hexdigest()[:20]
    folder.mkdir(parents=True, exist_ok=True)
    out = {"rosto": folder / f"{key}-rosto.png", "rosto_contorno": folder / f"{key}-rosto-contorno.png"}
    nobody = folder / f"{key}-ninguem"
    if all(p.is_file() for p in out.values()):
        return out
    if nobody.is_file():
        return None
    faces = face_session()
    best = None
    for f in frames:
        img = _open(f)
        face = _face(img, faces)
        if face is None:
            continue
        x0, y0, x1, y1 = face[1]
        area = (x1 - x0) * (y1 - y0)
        if best is None or area > best[0]:
            best = (area, img)
    cut = _crop(best[1], _mask(best[1], session())) if best else None
    if cut is None:
        nobody.touch()
        return None
    cut.save(out["rosto"], "PNG")
    outlined(cut).save(out["rosto_contorno"], "PNG")
    return out
