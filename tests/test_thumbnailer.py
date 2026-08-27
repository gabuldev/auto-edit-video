"""Tests for tools/thumbnailer.py — templates, safe-zone, chip render."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import thumbnailer
from tools.thumbnailer import (
    COVER_FRAMES,
    COVER_TAG,
    _assert_frame_rate_preserved,
    _combined_score,
    _cover_body_cmd,
    _cover_clip_cmd,
    _cover_concat_cmd,
    _cover_mux_cmd,
    _cover_strip_point,
    _forced_timestamp,
    _score_mouth_closed,
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


# ── _score_mouth_closed ──────────────────────────────────────────────────────

def _face_patch(mouth: str) -> np.ndarray:
    """Synthetic 120x120 skin-toned face; `mouth` is closed / open / teeth."""
    rgb = np.zeros((120, 120, 3), dtype=np.uint8)
    rgb[:, :] = (190, 140, 110)  # skin
    if mouth == "open":
        rgb[75:100, 45:75] = (20, 12, 10)          # dark cavity
    elif mouth == "teeth":
        rgb[75:100, 45:75] = (20, 12, 10)
        rgb[78:86, 48:72] = (250, 248, 245)        # teeth
    return rgb


class TestScoreMouthClosed:
    def test_closed_mouth_scores_high(self):
        assert _score_mouth_closed(_face_patch("closed")) > 0.9

    def test_open_mouth_scores_lower_than_closed(self):
        assert _score_mouth_closed(_face_patch("open")) < _score_mouth_closed(
            _face_patch("closed")
        )

    def test_visible_teeth_penalized(self):
        assert _score_mouth_closed(_face_patch("teeth")) < 0.5

    def test_no_face_scores_zero(self):
        blank = np.zeros((120, 120, 3), dtype=np.uint8)
        assert _score_mouth_closed(blank) == 0.0

    def test_score_in_unit_range(self):
        for mouth in ("closed", "open", "teeth"):
            score = _score_mouth_closed(_face_patch(mouth))
            assert 0.0 <= score <= 1.0


# ── _combined_score ──────────────────────────────────────────────────────────

BASE_SCORES = {
    "face": 0.30, "sharpness": 1000.0, "clarity": 40.0,
    "brightness": 0.9, "mouth_closed": 1.0,
}


class TestCombinedScore:
    def test_open_mouth_loses_to_closed_mouth(self):
        closed = _combined_score(BASE_SCORES)
        talking = _combined_score({**BASE_SCORES, "mouth_closed": 0.0})
        assert talking < closed

    def test_mouth_does_not_outweigh_face_visibility(self):
        # A frame with a visible, talking face still beats a faceless one
        talking_face = _combined_score({**BASE_SCORES, "face": 0.30, "mouth_closed": 0.0})
        no_face = _combined_score({**BASE_SCORES, "face": 0.02, "mouth_closed": 1.0})
        assert talking_face > no_face

    def test_missing_mouth_key_does_not_raise(self):
        scores = {k: v for k, v in BASE_SCORES.items() if k != "mouth_closed"}
        assert _combined_score(scores) > 0


# ── _forced_timestamp (AUTO_EDIT_THUMB_TS) ───────────────────────────────────

class TestForcedTimestamp:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_THUMB_TS", raising=False)
        assert _forced_timestamp() is None

    def test_parses_float(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_THUMB_TS", "42.5")
        assert _forced_timestamp() == 42.5

    def test_invalid_ignored(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_THUMB_TS", "meio-do-video")
        assert _forced_timestamp() is None

    def test_negative_ignored(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_THUMB_TS", "-3")
        assert _forced_timestamp() is None


# ── _cover_strip_point (idempotência) ────────────────────────────────────────

class TestCoverStripPoint:
    def test_detects_previously_embedded_cover(self):
        # 2 cover frames, then the real content keyframe
        packets = [(0.021, True), (0.054, False), (0.121, True), (0.154, False)]
        assert _cover_strip_point(packets) == 0.121

    def test_no_second_keyframe_means_no_cover(self):
        packets = [(0.0, True), (0.033, False), (0.066, False)]
        assert _cover_strip_point(packets) is None

    def test_distant_keyframe_is_not_a_cover(self):
        packets = [(0.0, True)] + [(i * 0.033, False) for i in range(1, 20)] + [(2.0, True)]
        assert _cover_strip_point(packets) is None

    def test_too_many_leading_frames_is_not_a_cover(self):
        packets = [
            (0.0, True), (0.033, False), (0.066, False), (0.1, False),
            (0.133, False), (0.166, False), (0.2, True),
        ]
        assert _cover_strip_point(packets) is None


# ── cover ffmpeg commands ────────────────────────────────────────────────────

class TestCoverClipCmd:
    def test_encodes_fixed_frame_count(self):
        cmd = _cover_clip_cmd(Path("/tmp/t.png"), 1080, 1920, "30/1", Path("/tmp/c.mp4"))
        assert cmd[cmd.index("-frames:v") + 1] == str(COVER_FRAMES)

    def test_scales_to_video_size(self):
        cmd = _cover_clip_cmd(Path("/tmp/t.png"), 1080, 1920, "30/1", Path("/tmp/c.mp4"))
        assert "scale=1080:1920:flags=lanczos,format=yuv420p" in cmd[cmd.index("-vf") + 1]

    def test_has_no_audio_input(self):
        cmd = _cover_clip_cmd(Path("/tmp/t.png"), 1080, 1920, "30/1", Path("/tmp/c.mp4"))
        assert "anullsrc" not in " ".join(cmd)

    def test_matches_the_body_track_timescale(self):
        # The executor writes segments at 1/90000. A cover muxed at ffmpeg's
        # default 1/30000 makes the concat demuxer read every body timestamp
        # 3x too large -> the delivered video plays in slow motion.
        cmd = _cover_clip_cmd(
            Path("/tmp/t.png"), 3840, 2160, "30000/1001", Path("/tmp/c.mp4"), 90000
        )
        assert cmd[cmd.index("-video_track_timescale") + 1] == "90000"

    def test_output_path_stays_last(self):
        cmd = _cover_clip_cmd(
            Path("/tmp/t.png"), 3840, 2160, "30000/1001", Path("/tmp/c.mp4"), 90000
        )
        assert cmd[-1] == "/tmp/c.mp4"

    def test_unknown_timescale_omits_the_flag(self):
        cmd = _cover_clip_cmd(
            Path("/tmp/t.png"), 1080, 1920, "30/1", Path("/tmp/c.mp4"), None
        )
        assert "-video_track_timescale" not in cmd


class TestCoverBodyCmd:
    def test_drops_audio_and_copies_video(self):
        cmd = _cover_body_cmd(Path("/tmp/in.mp4"), None, Path("/tmp/body.mp4"))
        assert "-an" in cmd
        assert cmd[cmd.index("-c:v") + 1] == "copy"

    def test_no_strip_point_means_no_seek(self):
        cmd = _cover_body_cmd(Path("/tmp/in.mp4"), None, Path("/tmp/body.mp4"))
        assert "-ss" not in cmd

    def test_strip_point_seeks_before_input(self):
        cmd = _cover_body_cmd(Path("/tmp/in.mp4"), 0.121, Path("/tmp/body.mp4"))
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-ss") + 1] == "0.121"


class TestCoverMuxCmd:
    def test_audio_comes_from_the_original_file(self):
        cmd = _cover_mux_cmd(
            Path("/tmp/v.mp4"), Path("/tmp/src.mp4"), Path("/tmp/out.mp4"), True
        )
        assert cmd[cmd.index("-map") + 1] == "0:v:0"
        assert "1:a:0" in cmd
        # the untrimmed source is the second input
        assert cmd.index("/tmp/src.mp4") > cmd.index("/tmp/v.mp4")

    def test_silent_video_maps_no_audio(self):
        cmd = _cover_mux_cmd(
            Path("/tmp/v.mp4"), Path("/tmp/src.mp4"), Path("/tmp/out.mp4"), False
        )
        assert "1:a:0" not in cmd

    def test_keeps_faststart_and_mp42(self):
        cmd = _cover_mux_cmd(
            Path("/tmp/v.mp4"), Path("/tmp/src.mp4"), Path("/tmp/out.mp4"), True
        )
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"
        assert cmd[cmd.index("-brand") + 1] == "mp42"
        assert cmd[-1] == "/tmp/out.mp4"

    def test_tags_the_file_as_covered(self):
        cmd = _cover_mux_cmd(
            Path("/tmp/v.mp4"), Path("/tmp/src.mp4"), Path("/tmp/out.mp4"), True
        )
        assert f"comment={COVER_TAG}" in cmd


class TestAssertFrameRatePreserved:
    def test_raises_when_the_concat_stretched_the_timestamps(self, monkeypatch):
        monkeypatch.setattr(thumbnailer.probe, "video_fps", lambda _p: "10000/1001")
        with pytest.raises(RuntimeError, match="changed the frame rate"):
            _assert_frame_rate_preserved(Path("/tmp/out.mp4"), "30000/1001")

    def test_passes_when_the_frame_rate_survived(self, monkeypatch):
        monkeypatch.setattr(thumbnailer.probe, "video_fps", lambda _p: "30000/1001")
        _assert_frame_rate_preserved(Path("/tmp/out.mp4"), "30000/1001")

    def test_unknown_frame_rate_does_not_block(self, monkeypatch):
        monkeypatch.setattr(thumbnailer.probe, "video_fps", lambda _p: None)
        _assert_frame_rate_preserved(Path("/tmp/out.mp4"), "30000/1001")
