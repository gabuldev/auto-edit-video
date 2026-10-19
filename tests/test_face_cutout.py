"""Automatic face cut-out for the {{rosto}} slot: the person segmented out of
a video frame (U²-Net, onnxruntime). A fake session stands in for the model."""
import hashlib

import numpy as np
import pytest
from PIL import Image

from auto_edit import face_cutout as fc


class FakeSession:
    """Answers a mask: 1 inside `box` (fractions of the model input), else 0."""

    def __init__(self, box):
        self.box = box
        self.calls = 0

    def get_inputs(self):
        return [type("I", (), {"name": "input.1"})()]

    def run(self, outputs, feeds):
        self.calls += 1
        x = next(iter(feeds.values()))
        n, c, h, w = x.shape
        m = np.zeros((1, 1, h, w), dtype=np.float32)
        x0, y0, x1, y1 = self.box
        m[0, 0, int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 1.0
        return [m]


def frame(tmp_path, name="f.jpg", color=(120, 90, 70)):
    p = tmp_path / name
    Image.new("RGB", (640, 360), color).save(p)
    return p


def test_cutout_is_the_person_cropped_to_its_box(tmp_path):
    cut = fc.cutout(frame(tmp_path), session=FakeSession((0.25, 0.2, 0.75, 1.0)))
    assert cut.mode == "RGBA"
    w, h = cut.size
    assert 300 <= w <= 340 and 280 <= h <= 300  # ~half the width, 80% of the height (+ small margin)
    alpha = np.asarray(cut)[..., 3]
    assert alpha[h // 2, w // 2] == 255


def test_no_person_is_none(tmp_path):
    assert fc.cutout(frame(tmp_path), session=FakeSession((0.5, 0.5, 0.52, 0.52))) is None


def test_outlined_adds_an_opaque_white_ring(tmp_path):
    cut = fc.cutout(frame(tmp_path), session=FakeSession((0.3, 0.3, 0.7, 0.9)))
    ring = fc.outlined(cut, 12)
    a = np.asarray(ring)
    assert ring.size[0] > cut.size[0]  # room for the ring
    assert (a[..., 3] == 255).sum() > (np.asarray(cut)[..., 3] == 255).sum()
    edge = a[a.shape[0] // 2, 12]  # just left of the person (12px ring + ~6px padding): white
    assert tuple(edge) == (255, 255, 255, 255)


class FakeFaceSession:
    """The face detector: answers `score` for one box (fractions of the frame)."""

    def __init__(self, score, box=(0.4, 0.2, 0.6, 0.5)):
        self.score, self.box = score, box

    def get_inputs(self):
        return [type("I", (), {"name": "input"})()]

    def run(self, outputs, feeds):
        x = next(iter(feeds.values()))
        assert x.shape == (1, 3, 240, 320)
        scores = np.array([[[1 - self.score, self.score], [0.99, 0.01]]], dtype=np.float32)
        boxes = np.array([[self.box, (0, 0, 0.1, 0.1)]], dtype=np.float32)
        return [scores, boxes]


class TestFace:
    def test_a_face_is_its_box(self, tmp_path):
        box = fc._face(Image.open(frame(tmp_path)), FakeFaceSession(0.99))
        assert box is not None and box[1] == pytest.approx((0.4, 0.2, 0.6, 0.5))

    def test_a_hand_is_not_a_face(self, tmp_path):
        """A thumbs-up scores ~0.8 on the detector: below the bar."""
        assert fc._face(Image.open(frame(tmp_path)), FakeFaceSession(0.83)) is None


def _fakes(monkeypatch, faces: dict):
    """Person in every frame (the mask); a face only where `faces` says, by
    the frame's red channel."""
    sessions = {"s": FakeSession((0.2, 0.1, 0.8, 1.0))}
    monkeypatch.setattr(fc, "session", lambda: sessions["s"])
    monkeypatch.setattr(fc, "face_session", lambda: object())
    monkeypatch.setattr(fc, "_face", lambda img, sess: faces.get(img.getpixel((0, 0))[0]))
    return sessions


def test_cutout_files_pick_the_frame_with_the_biggest_face_and_cache(tmp_path, monkeypatch):
    far, near, hands = (frame(tmp_path, f"{n}.jpg", (r, 10, 10)) for n, r in (("a", 10), ("b", 200), ("c", 100)))
    sessions = _fakes(monkeypatch, {10: (0.99, (0.4, 0.4, 0.45, 0.48)), 200: (0.99, (0.3, 0.1, 0.6, 0.6))})
    picked = []
    real = fc._mask
    monkeypatch.setattr(fc, "_mask", lambda img, s: picked.append(img.getpixel((0, 0))[0]) or real(img, s))
    out = fc.cutout_files([far, near, hands], tmp_path / "cache")
    assert out and out["rosto"].is_file() and out["rosto_contorno"].is_file()
    assert picked == [200]  # only the chosen frame is segmented
    calls = sessions["s"].calls
    again = fc.cutout_files([far, near, hands], tmp_path / "cache")
    assert again == out and sessions["s"].calls == calls  # cached: the model didn't run again


def test_cutout_files_none_without_a_face(tmp_path, monkeypatch):
    """Hands and a body but no face (a desk shot): no cut-out, the layout
    goes without it, never a giant outlined hand."""
    _fakes(monkeypatch, {})
    assert fc.cutout_files([frame(tmp_path)], tmp_path / "cache") is None


class TestModel:
    @pytest.fixture
    def home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
        return tmp_path / "home"

    def _fake_download(self, payload: bytes):
        def download(url, dest):
            dest.write_bytes(payload)
        return download

    def test_good_download_lands(self, home, monkeypatch):
        payload = b"modelo"
        monkeypatch.setattr(fc, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
        path = fc.ensure_model(download=self._fake_download(payload))
        assert path.read_bytes() == payload and path.parent == home / "models"
        assert not list(path.parent.glob("*.part"))

    def test_wrong_hash_is_an_error_and_leaves_nothing(self, home, monkeypatch):
        monkeypatch.setattr(fc, "MODEL_SHA256", "0" * 64)
        with pytest.raises(fc.CutoutError, match="baixado"):
            fc.ensure_model(download=self._fake_download(b"corrompido"))
        assert not list((home / "models").glob("*"))

    def test_present_model_is_not_downloaded_again(self, home, monkeypatch):
        payload = b"modelo"
        monkeypatch.setattr(fc, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
        fc.ensure_model(download=self._fake_download(payload))
        assert fc.ensure_model(download=lambda u, d: pytest.fail("downloaded again")).is_file()
        assert not fc.model_ready()  # the face detector is still missing
        monkeypatch.setattr(fc, "FACE_MODEL_SHA256", hashlib.sha256(payload).hexdigest())
        assert fc.ensure_face_model(download=self._fake_download(payload)).parent == home / "models"
        assert fc.model_ready()

    def test_face_model_wrong_hash(self, home, monkeypatch):
        monkeypatch.setattr(fc, "FACE_MODEL_SHA256", "0" * 64)
        with pytest.raises(fc.CutoutError, match="baixado"):
            fc.ensure_face_model(download=self._fake_download(b"x"))
        assert not list((home / "models").glob("*"))

    def test_without_onnxruntime(self, home, monkeypatch):
        import builtins

        real = builtins.__import__

        def no_ort(name, *a, **kw):
            if name == "onnxruntime":
                raise ImportError("no")
            return real(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", no_ort)
        monkeypatch.setattr(fc, "_session", None)
        with pytest.raises(fc.CutoutError, match="onnxruntime"):
            fc.session(download=self._fake_download(b""))
