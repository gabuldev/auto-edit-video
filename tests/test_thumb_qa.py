"""Tests for auto_edit.thumb_qa — the pure thumbnail QA checks."""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import thumb_qa as qa


# ── Text rules (item 5) ──────────────────────────────────────────────────────

class TestTextRules:
    def test_word_count(self):
        assert qa.word_count("CODEI SEM IA") == 3
        assert qa.word_count("") == 0

    def test_technical_terms_detects_codes_and_vocab(self):
        assert qa.is_technical("ESP32")        # letters + digits
        assert qa.is_technical("NFC")          # vocabulary
        assert qa.is_technical("firmware")     # vocabulary
        assert qa.is_technical("GPT-4")        # mixed with punctuation
        assert not qa.is_technical("IA")       # 2-letter, common
        # NOT keyed on ALL-CAPS — hero text is uppercase, so plain words pass:
        assert not qa.is_technical("CARRO")
        assert qa.technical_terms("APP COM IA LÊ MEU CARRO") == []

    def test_check_main_text_ok(self):
        r = qa.check_main_text("peguei com r$5")
        assert r["ok"] and r["word_count"] == 3

    def test_check_main_text_too_many_words(self):
        r = qa.check_main_text("codei sem ia por dois dias")
        assert not r["ok"]
        assert any("palavras" in x for x in r["reasons"])

    def test_check_main_text_too_technical(self):
        r = qa.check_main_text("ESP8266 vs ESP32")
        assert not r["ok"]
        assert any("técnico" in x for x in r["reasons"])


# ── WCAG contrast (item 6) ───────────────────────────────────────────────────

class TestContrast:
    def test_black_on_white_is_max(self):
        assert qa.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.1)

    def test_same_colour_is_one(self):
        assert qa.contrast_ratio((120, 30, 200), (120, 30, 200)) == pytest.approx(1.0, abs=1e-6)

    def test_order_independent(self):
        a = qa.contrast_ratio((10, 10, 10), (200, 200, 200))
        b = qa.contrast_ratio((200, 200, 200), (10, 10, 10))
        assert a == pytest.approx(b)

    def test_low_contrast_is_below_threshold(self):
        assert qa.contrast_ratio((120, 120, 120), (140, 140, 140)) < qa.MIN_CONTRAST


# ── Geometry (item 2) ────────────────────────────────────────────────────────

class TestGeometry:
    def test_no_overlap(self):
        assert qa.overlap_fraction((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_full_overlap(self):
        assert qa.overlap_fraction((0, 0, 10, 10), (0, 0, 20, 20)) == 1.0

    def test_half_overlap(self):
        # text box half-covered by the face box
        assert qa.overlap_fraction((0, 0, 10, 10), (5, 0, 20, 10)) == pytest.approx(0.5)

    def test_iou(self):
        assert qa.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
        assert qa.iou((0, 0, 10, 10), (10, 10, 20, 20)) == 0.0


# ── Mobile legibility (item 6) ───────────────────────────────────────────────

class TestMobile:
    def test_cap_height_scales(self):
        # 200px tall text in a 720px-tall thumb → ~26px at 94px preview
        assert qa.cap_height_px((0, 0, 100, 200), 720) == pytest.approx(200 * 94 / 720, abs=0.1)

    def test_save_mobile_preview(self, tmp_path):
        src = tmp_path / "thumb.png"
        Image.new("RGB", (1280, 720), (10, 20, 30)).save(src)
        out = qa.save_mobile_preview(src, tmp_path / "prev.png")
        with Image.open(out) as im:
            assert im.size == qa.MOBILE_SIZE


# ── evaluate / run ───────────────────────────────────────────────────────────

class TestEvaluate:
    def test_skipped_checks_are_null_not_failures(self):
        r = qa.evaluate("peguei com r$5")  # only text given
        assert r["checks"]["contrast"] is None
        assert r["checks"]["text_not_over_face"] is None
        assert r["approved"] is True  # the one check that ran passed

    def test_text_over_face_fails(self):
        r = qa.evaluate("ok curto", text_box=(0, 0, 100, 100), face_box=(0, 0, 100, 100))
        assert r["approved"] is False
        assert r["checks"]["text_not_over_face"]["ok"] is False

    def test_low_contrast_fails(self):
        r = qa.evaluate("ok", text_rgb=(130, 130, 130), bg_rgb=(150, 150, 150))
        assert r["approved"] is False
        assert r["checks"]["contrast"]["ok"] is False

    def test_small_mobile_text_fails(self):
        r = qa.evaluate("ok", text_box=(0, 0, 100, 40), full_height=1080)
        assert r["checks"]["mobile_text_height"]["ok"] is False


class TestRun:
    def test_writes_report_and_preview_non_fatally(self, tmp_path):
        thumb = tmp_path / "thumbnail.png"
        Image.new("RGB", (1280, 720), (0, 0, 0)).save(thumb)
        report = qa.run(tmp_path, thumb, "codei sem ia por dois dias")
        assert (tmp_path / "thumbnail_qa.json").exists()
        assert (tmp_path / "thumbnail_168.png").exists()
        saved = json.loads((tmp_path / "thumbnail_qa.json").read_text())
        assert saved["approved"] is False  # 6 words > 4
        assert report["mobile_preview"] == "thumbnail_168.png"

    def test_missing_thumb_does_not_raise(self, tmp_path):
        report = qa.run(tmp_path, tmp_path / "nope.png", "ok curto")
        assert "mobile_preview_error" in report  # preview failed, but no exception
