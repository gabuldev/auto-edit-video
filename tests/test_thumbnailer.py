"""Tests for tools/thumbnailer.py — templates, safe-zone, chip render."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.thumbnailer import (
    _BUILTIN_TEMPLATES,
    _load_templates,
    _resolve_template,
    _safe_block_top,
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
