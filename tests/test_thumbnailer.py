"""Tests for tools/thumbnailer.py — templates, safe-zone, chip render."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.thumbnailer import (
    _cover_concat_cmd,
    _BUILTIN_TEMPLATES,
    _TEMPLATE_TO_STYLE,
    _load_templates,
    _resolve_template,
    _safe_block_top,
    _draw_sub_chip,
    _draw_thumbnail_text,
    _apply_grade,
    IG_SAFE_TOP,
    IG_SAFE_BOT,
    FACE_ZONE_TOP,
)


class TestLoadTemplates:
    def test_builtin_has_three_types(self):
        assert set(_BUILTIN_TEMPLATES["templates"]) >= {"dev", "maker", "gadget"}
        assert _BUILTIN_TEMPLATES["default"] in _BUILTIN_TEMPLATES["templates"]

    def test_reads_json_from_env(self, tmp_path, monkeypatch):
        custom = {"default": "x", "templates": {"x": {
            "description": "d", "accent": [1, 2, 3],
            "grade": [[0, 0, 0], [1, 1, 1]], "sub_text_color": [9, 9, 9]}}}
        f = tmp_path / "templates.json"
        f.write_text(json.dumps(custom))
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", str(f))
        reg = _load_templates()
        assert reg["templates"]["x"]["accent"] == [1, 2, 3]

    def test_missing_file_falls_back_to_builtin(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", "/nonexistent/nope.json")
        reg = _load_templates()
        assert "dev" in reg["templates"]

    def test_invalid_json_falls_back(self, tmp_path, monkeypatch):
        f = tmp_path / "bad.json"
        f.write_text("{not valid")
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", str(f))
        reg = _load_templates()
        assert "dev" in reg["templates"]


class TestResolveTemplate:
    def setup_method(self):
        self.reg = _BUILTIN_TEMPLATES

    def test_explicit_name_wins(self):
        name, tpl = _resolve_template("maker", None, self.reg)
        assert name == "maker"
        assert tpl["accent"] == [255, 159, 46]

    def test_unknown_name_falls_back_to_default(self):
        name, _ = _resolve_template("banana", None, self.reg)
        assert name == "dev"

    def test_legacy_style_hint_maps(self):
        name, _ = _resolve_template(None, "bold-energy", self.reg)
        assert name == "gadget"

    def test_none_uses_default(self):
        name, _ = _resolve_template(None, None, self.reg)
        assert name == "dev"


class TestSafeBlockTop:
    H = 1920

    def test_center_small_block_at_upper_safe(self):
        top = _safe_block_top(self.H, 300, "center")
        assert top == int(self.H * 0.24)
        assert top >= int(self.H * IG_SAFE_TOP)
        assert top + 300 <= int(self.H * FACE_ZONE_TOP)

    def test_center_tall_block_pinned_to_top_limit(self):
        # block too tall to fit above the face zone -> pinned at safe top
        top = _safe_block_top(self.H, 900, "center")
        assert top == int(self.H * IG_SAFE_TOP)

    def test_center_never_above_safe_top(self):
        for total_h in (100, 400, 700, 1200):
            top = _safe_block_top(self.H, total_h, "center")
            assert top >= int(self.H * IG_SAFE_TOP)

    def test_left_stays_within_safe_bottom(self):
        top = _safe_block_top(self.H, 300, "left")
        assert top >= int(self.H * IG_SAFE_TOP)
        assert top + 300 <= int(self.H * IG_SAFE_BOT)


class TestSubChip:
    def test_chip_paints_accent_pixels(self):
        img = Image.new("RGBA", (300, 120), (0, 0, 0, 255))
        font = ImageFont.load_default(size=24)
        out = _draw_sub_chip(img, "SÓ R$100", font, (255, 0, 0), (255, 255, 255), (150, 60))
        arr = np.asarray(out.convert("RGB"))
        # há pixels vermelhos do chip
        red = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] < 60)
        assert red.sum() > 0

    def test_chip_left_align_stays_on_screen(self):
        img = Image.new("RGBA", (1080, 200), (0, 0, 0, 255))
        font = ImageFont.load_default(size=24)
        out = _draw_sub_chip(
            img, "PTFE 2,5MM", font, (255, 0, 0), (255, 255, 255),
            (int(1080 * 0.05), 60), align="left",
        )
        arr = np.asarray(out.convert("RGB"))
        red = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] < 60)
        xs = np.where(red.any(axis=0))[0]
        assert xs.size > 0
        assert xs.min() >= 0 and xs.max() < 1080


class TestTemplateToStyle:
    def test_template_to_style_covers_registry(self):
        for name in _BUILTIN_TEMPLATES["templates"]:
            assert name in _TEMPLATE_TO_STYLE


class TestDrawThumbnailText:
    def test_accepts_template_dict_and_renders(self):
        img = Image.new("RGB", (1080, 1920), (40, 40, 40))
        template = _BUILTIN_TEMPLATES["templates"]["gadget"]
        out = _draw_thumbnail_text(img, "CASE DA GOPRO", "SÓ R$100", template, "center")
        assert out.size == (1080, 1920)
        arr = np.asarray(out.convert("RGB"))
        # chip magenta do gadget aparece em algum lugar
        magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 90) & (arr[:, :, 2] > 110)
        assert magenta.sum() > 0

    def test_no_subtext_still_renders(self):
        img = Image.new("RGB", (1080, 1920), (40, 40, 40))
        template = _BUILTIN_TEMPLATES["templates"]["dev"]
        out = _draw_thumbnail_text(img, "CAIU O FLUTTER", None, template, "center")
        assert out.size == (1080, 1920)


class TestApplyGrade:
    def test_same_size_and_changes_pixels(self):
        img = Image.new("RGB", (200, 400), (128, 128, 128))
        out = _apply_grade(img, [[255, 0, 0], [0, 0, 255]])
        assert out.size == img.size
        arr = np.asarray(out)
        # topo puxa vermelho, base puxa azul
        assert int(arr[5, 100, 0]) > int(arr[395, 100, 0])
        assert int(arr[395, 100, 2]) > int(arr[5, 100, 2])

    def test_none_grade_returns_rgb(self):
        img = Image.new("RGB", (50, 50), (10, 20, 30))
        out = _apply_grade(img, None)
        assert out.mode == "RGB"
        assert out.size == (50, 50)


# ── _cover_concat_cmd (faststart / brand) ────────────────────────────────────

class TestCoverConcatCmd:
    def test_includes_faststart(self):
        cmd = _cover_concat_cmd(Path("/tmp/list.txt"), Path("/tmp/out.mp4"))
        assert "-movflags" in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

    def test_includes_mp42_brand(self):
        cmd = _cover_concat_cmd(Path("/tmp/list.txt"), Path("/tmp/out.mp4"))
        assert "-brand" in cmd
        assert cmd[cmd.index("-brand") + 1] == "mp42"

    def test_flags_before_output(self):
        # ffmpeg output options must precede the output path
        cmd = _cover_concat_cmd(Path("/tmp/list.txt"), Path("/tmp/out.mp4"))
        assert cmd.index("-movflags") < cmd.index("/tmp/out.mp4")
        assert cmd[-1] == "/tmp/out.mp4"
