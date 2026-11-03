"""Optional expression score (auto_edit/expression.py) in the thumbnail's
face-frame choice. Without mediapipe the frame score must be exactly the old one."""
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import thumbnailer  # noqa: E402

from auto_edit import expression  # noqa: E402


class TestExpressiveness:
    def test_smile_is_expressive(self):
        assert expression.expressiveness({"mouthSmileLeft": 0.9, "mouthSmileRight": 0.95}) > 0.85

    def test_surprise_is_expressive(self):
        assert expression.expressiveness({"eyeWideLeft": 0.8, "eyeWideRight": 0.8, "browInnerUp": 0.9}) > 0.75

    def test_neutral_is_not(self):
        assert expression.expressiveness({"mouthSmileLeft": 0.02, "eyeWideLeft": 0.01}) < 0.05

    def test_closed_eyes_sink_a_smile(self):
        smile = {"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9}
        assert expression.expressiveness({**smile, "eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}) == 0.0
        assert expression.expressiveness({**smile, "eyeBlinkLeft": 0.1, "eyeBlinkRight": 0.1}) > 0.85


class TestOptional:
    def test_without_mediapipe_score_is_none(self, monkeypatch):
        monkeypatch.setattr(expression, "_failed", False)
        monkeypatch.setattr(expression, "available", lambda: False)
        assert expression.score(np.zeros((10, 10, 3), np.uint8)) is None

    def test_a_failure_turns_it_off_for_the_run(self, monkeypatch):
        monkeypatch.setattr(expression, "_failed", False)
        monkeypatch.setattr(expression, "available", lambda: True)
        calls = []

        def boom(rgb, download=None):
            calls.append(1)
            raise RuntimeError("no network")

        monkeypatch.setattr(expression, "blendshapes", boom)
        assert expression.score(np.zeros((10, 10, 3), np.uint8)) is None
        assert expression.score(np.zeros((10, 10, 3), np.uint8)) is None
        assert calls == [1]  # tried once, then off

    def test_no_face_scores_zero(self, monkeypatch):
        monkeypatch.setattr(expression, "_failed", False)
        monkeypatch.setattr(expression, "available", lambda: True)
        monkeypatch.setattr(expression, "blendshapes", lambda rgb, download=None: None)
        assert expression.score(np.zeros((10, 10, 3), np.uint8)) == 0.0

    def test_model_is_checked_by_hash(self, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        with pytest.raises(face_cutout.CutoutError):
            expression._ensure_model(download=lambda url, dest: Path(dest).write_bytes(b"not the model"))
        assert not (tmp_path / "models" / expression.MODEL_NAME).exists()


class TestFrameScore:
    def _img(self):
        return Image.new("RGB", (640, 360), (180, 130, 110))

    def test_without_expression_the_score_is_the_old_formula(self):
        # conftest turns the scorer off (as without the extra)
        s = thumbnailer._score_frame(self._img())
        assert "expression" not in s
        old = (s["face"] * 50.0 + s["mouth_closed"] * thumbnailer.MOUTH_WEIGHT + s["sharpness"] / 500.0
               + s["clarity"] / 10.0 + s["brightness"] * 5.0)
        assert thumbnailer._combined_score(s) == pytest.approx(old)

    def test_expression_is_added_when_measured(self, monkeypatch):
        monkeypatch.setattr(expression, "score", lambda rgb: 0.8)
        s = thumbnailer._score_frame(self._img())
        assert s["expression"] == 0.8
        base = thumbnailer._combined_score({k: v for k, v in s.items() if k != "expression"})
        assert thumbnailer._combined_score(s) == pytest.approx(base + 0.8 * thumbnailer.EXPRESSION_WEIGHT)

    def test_second_frame_never_pays_for_expression(self, monkeypatch):
        monkeypatch.setattr(expression, "score", lambda rgb: pytest.fail("expression scored for frame2"))
        thumbnailer._second_frame_score(self._img(), maker=True)

    def test_the_expressive_frame_wins_among_equal_ones(self, monkeypatch, tmp_path):
        # two identical frames but for the expression → the smiling one is picked
        def extract(video, ts, out):
            Image.new("RGB", (640, 360), (180, 130, 110)).save(out, "PNG")
            return out

        monkeypatch.setattr(thumbnailer, "_extract_frame", extract)
        monkeypatch.setattr(thumbnailer, "NUM_CANDIDATES", 2)
        order = iter([0.1, 0.9])
        monkeypatch.setattr(expression, "score", lambda rgb: next(order))
        _, ts = thumbnailer._pick_best_frame("v.mp4", 100.0, tmp_path, with_ts=True)
        assert ts > 50  # the second candidate (the smiling one)
