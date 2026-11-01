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

    def test_three_d_and_price_are_not_technical(self):
        # "3D" is a dimension and "R$5" a price — plain language, not jargon.
        assert not qa.is_technical("3D")
        assert not qa.is_technical("4d")
        assert not qa.is_technical("R$5")
        assert not qa.is_technical("R$1.500")
        assert qa.check_main_text("IMPRESSORA 3D")["ok"]
        assert qa.technical_terms("PESEI COM R$5") == []

    def test_punctuation_token_is_not_a_word(self):
        # a lone em-dash must not count toward the 4-word budget
        assert qa.word_count("CRIEI UM APP — SOZINHO") == 4
        assert qa.check_main_text("CRIEI UM APP — SOZINHO")["ok"]

    def test_versus_between_terms_flags_technical_excess(self):
        # the task's bad example: one spec term + a versus comparison → reject
        r = qa.check_main_text("ESP8266 X BALANÇA TOLEDO")
        assert not r["ok"]
        assert any("X/VS" in x for x in r["reasons"])

    def test_versus_without_tech_is_allowed(self):
        # a plain-language versus ("CARRO X MOTO") is a legit thumbnail style
        r = qa.check_main_text("CARRO X MOTO")
        assert r["ok"]


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

    def test_big_text_fully_over_small_face_fails(self):
        # The exact bug: a 1200×400 text box fully covering a 150×150 face.
        # Measuring the face's coverage (not the text's) catches it.
        face = (100, 100, 250, 250)
        text = (0, 0, 1200, 400)
        assert qa.overlap_fraction(face, text) == pytest.approx(1.0)  # face fully covered
        assert qa.overlap_fraction(text, face) < 0.05                 # text barely touched
        r = qa.evaluate("ok curto", text_box=text, face_box=face)
        assert r["approved"] is False
        assert r["checks"]["text_not_over_face"]["ok"] is False

    def test_text_clear_of_face_passes(self):
        # text on the left, face on the right — no overlap
        r = qa.evaluate("ok curto", text_box=(0, 0, 400, 300), face_box=(900, 400, 1280, 720))
        assert r["checks"]["text_not_over_face"]["ok"] is True


# ── Mobile legibility (item 6) ───────────────────────────────────────────────

class TestMobile:
    def test_cap_height_scales(self):
        # 200px tall text in a 720px-tall thumb → ~26px at 94px preview
        assert qa.cap_height_px((0, 0, 100, 200), 720) == pytest.approx(200 * 94 / 720, abs=0.1)

    def test_cap_height_divides_by_line_count(self):
        # a 2-line block measures per line — two 8px lines must read as ~8px,
        # not the 16px the whole block would suggest (the item-3 bug)
        block = (0, 0, 100, 240)  # 240px block in a 720px thumb → 31.3px at feed
        one = qa.cap_height_px(block, 720, lines=1)
        two = qa.cap_height_px(block, 720, lines=2)
        assert two == pytest.approx(one / 2, abs=0.1)

    def test_two_small_lines_fail_mobile_height(self):
        # a 2-line block that passes as one line fails once divided per line
        r1 = qa.evaluate("ok", text_box=(0, 0, 100, 170), full_height=1080, text_lines=1)
        r2 = qa.evaluate("ok", text_box=(0, 0, 100, 170), full_height=1080, text_lines=2)
        assert r1["checks"]["mobile_text_height"]["ok"] is True
        assert r2["checks"]["mobile_text_height"]["ok"] is False

    def test_save_mobile_preview_landscape(self, tmp_path):
        src = tmp_path / "thumb.png"
        Image.new("RGB", (1280, 720), (10, 20, 30)).save(src)
        out = qa.save_mobile_preview(src, tmp_path / "prev.png")
        with Image.open(out) as im:
            assert im.size == qa.MOBILE_SIZE  # 168×94

    def test_save_mobile_preview_portrait_is_not_squashed(self, tmp_path):
        # a vertical short (1080×1920) keeps its orientation: 94×168, not 168×94
        src = tmp_path / "short.png"
        Image.new("RGB", (1080, 1920), (10, 20, 30)).save(src)
        out = qa.save_mobile_preview(src, tmp_path / "prev.png")
        with Image.open(out) as im:
            assert im.size == (94, 168)


# ── evaluate / run ───────────────────────────────────────────────────────────

class TestEvaluate:
    def test_skipped_checks_are_parcial_not_approved(self):
        r = qa.evaluate("peguei com r$5")  # only text given → can't check everything
        assert r["checks"]["contrast"] is None
        assert r["checks"]["text_not_over_face"] is None
        assert r["approved"] is None  # parcial: nothing failed, but checks were skipped

    def test_all_checks_pass_is_approved(self):
        r = qa.evaluate(
            "ok curto",
            text_box=(0, 0, 400, 300), face_box=(900, 400, 1280, 720),
            text_rgb=(255, 255, 255), bg_rgb=(10, 10, 10), full_height=720,
        )
        assert r["approved"] is True
        assert all(c is not None for c in r["checks"].values())

    def test_a_failure_beats_a_skip(self):
        # 6 words fails text_rules even though other checks are skipped
        r = qa.evaluate("codei sem ia por dois dias")
        assert r["approved"] is False

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
