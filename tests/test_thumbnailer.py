"""Tests for tools/thumbnailer.py — templates, safe-zone, chip render."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import thumbnailer
from auto_edit import styles as styles_mod
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
    _frame_source,
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
        assert cmd.index("-movflags") < cmd.index(str(Path("/tmp/out.mp4")))
        assert cmd[-1] == str(Path("/tmp/out.mp4"))


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
        assert cmd[-1] == str(Path("/tmp/c.mp4"))

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
        assert cmd.index(str(Path("/tmp/src.mp4"))) > cmd.index(str(Path("/tmp/v.mp4")))

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
        assert cmd[-1] == str(Path("/tmp/out.mp4"))

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


class TestFrameSource:
    """O frame da thumbnail (e o cover embutido) sai do vídeo DESTE workspace.

    Num short derivado de um long, `pipeline["video_path"]` é o
    `edited_video.mp4` do long inteiro e `transcription.json` é a transcrição
    inteira — amostrar dali espalha os candidatos pelos ~378s do long e quase
    nunca cai dentro do clipe de 30s.
    """

    def test_prefers_the_workspaces_own_cut_video_and_post_cut_duration(self, tmp_path):
        (tmp_path / "captioned_video.mp4").write_bytes(b"x")
        (tmp_path / "post_cut_transcription.json").write_text(
            json.dumps({"duration": 30.0})
        )
        (tmp_path / "transcription.json").write_text(json.dumps({"duration": 378.75}))
        video, transcription = _frame_source(
            tmp_path, {"video_path": "/long/edited_video.mp4"}
        )
        assert video == str(tmp_path / "captioned_video.mp4")
        assert transcription["duration"] == 30.0

    def test_the_clean_cut_wins_over_captioned_and_overlaid(self, tmp_path):
        # captioned/overlaid have subtitles and graphics burned in — they used
        # to show up in the thumbnail.
        for name in ("captioned_video.mp4", "overlaid_video.mp4", "edited_video.mp4"):
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "post_cut_transcription.json").write_text(json.dumps({"duration": 30.0}))
        video, _ = _frame_source(tmp_path, {"video_path": "/long/edited_video.mp4"})
        assert video == str(tmp_path / "edited_video.mp4")

    def test_falls_back_to_overlaid_then_edited(self, tmp_path):
        (tmp_path / "edited_video.mp4").write_bytes(b"x")
        (tmp_path / "post_cut_transcription.json").write_text(
            json.dumps({"duration": 30.0})
        )
        video, _ = _frame_source(tmp_path, {"video_path": "/long/edited_video.mp4"})
        assert video == str(tmp_path / "edited_video.mp4")

    def test_falls_back_to_the_pipeline_source_when_there_is_no_cut_video(self, tmp_path):
        (tmp_path / "transcription.json").write_text(json.dumps({"duration": 378.75}))
        video, transcription = _frame_source(tmp_path, {"video_path": "/raw/v.mp4"})
        assert video == "/raw/v.mp4"
        assert transcription["duration"] == 378.75

    def test_cut_video_without_a_post_cut_transcript_keeps_the_pipeline_pair(self, tmp_path):
        # Sem post-cut não há duração que combine com o vídeo cortado; o par
        # bruto (vídeo + transcrição originais) é o único consistente.
        (tmp_path / "captioned_video.mp4").write_bytes(b"x")
        (tmp_path / "transcription.json").write_text(json.dumps({"duration": 378.75}))
        video, transcription = _frame_source(tmp_path, {"video_path": "/raw/v.mp4"})
        assert video == "/raw/v.mp4"
        assert transcription["duration"] == 378.75


class TestReactRenderer:
    """The React layout (renderer/, `auto-edit-render`) with a fake binary;
    any failure falls back to the Pillow layout."""

    @pytest.fixture
    def fake(self, tmp_path, monkeypatch):
        def make(script: str) -> Path:
            exe = tmp_path / "auto-edit-render"
            exe.write_text(f"#!{sys.executable}\nimport sys, json\n{script}\n")
            exe.chmod(0o755)
            monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
            monkeypatch.delenv("AUTO_EDIT_THUMB_RENDERER", raising=False)
            return exe
        return make

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_spec_goes_with_a_static_font_and_png_comes_back(self, fake, tmp_path):
        fake("""
cmd, spec_file, out = sys.argv[1:]
spec = json.load(open(spec_file))
assert cmd == "thumbnail" and spec["font"].endswith((".ttf", ".otf"))
assert spec["kind"] == "short" and spec["accent"] == [1, 2, 3]
open(out, "wb").write(b"PNG")
""")
        out = tmp_path / "t.png"
        assert thumbnailer._render_react({"kind": "short", "accent": [1, 2, 3]}, out) is True
        assert out.read_bytes() == b"PNG"
        assert "Anton" in thumbnailer._render_font().name

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_failure_means_pillow(self, fake, tmp_path, capsys):
        fake("sys.stderr.write('boom'); sys.exit(1)")
        assert thumbnailer._render_react({"kind": "short"}, tmp_path / "t.png") is False
        assert "boom" in capsys.readouterr().out

    def test_forced_pillow(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTO_EDIT_THUMB_RENDERER", "pillow")
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", "/whatever")
        assert thumbnailer._renderer_cmd() is None
        assert thumbnailer._render_react({}, tmp_path / "t.png") is False

    def test_short_uses_react_and_skips_pillow(self, monkeypatch, tmp_path):
        frame = tmp_path / "frame.jpg"
        Image.new("RGB", (1920, 1080), (40, 40, 40)).save(frame)
        monkeypatch.setattr(thumbnailer, "_frame_source", lambda ws, p: ("v.mp4", {"duration": 10.0}))
        monkeypatch.setattr(thumbnailer, "_pick_best_frame", lambda *a, **kw: frame)
        seen = {}

        def react(spec, output):
            seen.update(spec)
            output.write_bytes(b"PNG")
            return True

        monkeypatch.setattr(thumbnailer, "_render_react", react)
        monkeypatch.setattr(thumbnailer, "_draw_thumbnail_text", lambda *a, **kw: pytest.fail("Pillow ran"))
        meta = {"thumbnail": {"main_text": "Meu carro", "sub_text": "fala", "template": "maker"}}
        out = thumbnailer._thumbnail_short(tmp_path, meta, {})
        assert out.read_bytes() == b"PNG"
        assert seen["background"] == str(frame) and seen["accent"] == [255, 159, 46]
        assert (seen["width"], seen["height"]) == thumbnailer.SHORT_SIZE

    def test_long_falls_back_to_pillow(self, monkeypatch, tmp_path):
        frame = tmp_path / "frame.jpg"
        Image.new("RGB", (1920, 1080), (40, 40, 40)).save(frame)
        monkeypatch.setattr(thumbnailer, "_generate_imagen_bg", lambda *a, **kw: None)
        monkeypatch.setattr(thumbnailer, "_frame_source", lambda ws, p: ("v.mp4", {"duration": 10.0}))
        monkeypatch.setattr(thumbnailer, "_pick_best_frame", lambda *a, **kw: frame)
        monkeypatch.setattr(thumbnailer, "_render_react", lambda spec, output: False)
        out = thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "Título", "sub_text": "sub"}}, {})
        assert Image.open(out).size == thumbnailer.LONG_SIZE
        assert not frame.exists()  # the temporary frame is cleaned up


class TestHtmlLayout:
    """The active style's own HTML layout (long only); the default React
    layout when it fails."""

    HTML = '<div><img src="{{frame}}"/><img src="{{frame2}}"/><span>{{titulo}}</span></div>'

    @pytest.fixture
    def style(self, monkeypatch):
        def use(html):
            tokens = styles_mod.validate({"thumbnail": {"html": html}})
            monkeypatch.setattr(styles_mod, "active", lambda: {"id": "x", "tokens": tokens})
        return use

    @pytest.fixture
    def renderer(self, tmp_path, monkeypatch):
        """A fake auto-edit-render that records every spec; `fail_html` makes
        the HTML spec fail."""
        log = tmp_path / "specs.jsonl"
        exe = tmp_path / "auto-edit-render"
        def make(fail_html=False):
            exe.write_text(f"#!{sys.executable}\nimport sys, json\n"
                           "cmd, spec_file, out = sys.argv[1:]\nspec = json.load(open(spec_file))\n"
                           f"open({str(log)!r}, 'a').write(json.dumps(spec) + '\\n')\n"
                           f"if spec.get('html') and {fail_html}: sys.stderr.write('bad html'); sys.exit(1)\n"
                           "open(out, 'wb').write(b'PNG')\n")
            exe.chmod(0o755)
            monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
            monkeypatch.delenv("AUTO_EDIT_THUMB_RENDERER", raising=False)
            return lambda: [json.loads(x) for x in log.read_text().splitlines()]
        return make

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_long_sends_the_html_with_images(self, style, renderer, tmp_path):
        style(self.HTML)
        specs = renderer()
        spec = {"kind": "long", "width": 1280, "height": 720, "main_text": "Meu carro novo", "sub_text": None,
                "accent": [1, 2, 3], "background": "/a.jpg", "frame2": "/b.jpg", "face": None, "logos": []}
        assert thumbnailer._render_react(spec, tmp_path / "t.png") is True
        sent = specs()[0]
        assert sent["html"] and sent["images"]["frame"] == "/a.jpg" and sent["images"]["frame2"] == "/b.jpg"
        assert sent["values"]["titulo"] == "Meu carro novo" and sent["values"]["destaque"] == "#010203"

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_html_failure_falls_back_to_the_default_layout(self, style, renderer, tmp_path, capsys):
        style(self.HTML)
        specs = renderer(fail_html=True)
        spec = {"kind": "long", "width": 1280, "height": 720, "main_text": "x", "accent": [1, 2, 3]}
        assert thumbnailer._render_react(spec, tmp_path / "t.png") is True
        sent = specs()
        assert len(sent) == 2 and "html" in sent[0] and "html" not in sent[1]
        assert "bad html" in capsys.readouterr().out

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_short_never_uses_the_html(self, style, renderer, tmp_path):
        style(self.HTML)
        specs = renderer()
        thumbnailer._render_react({"kind": "short", "main_text": "x", "accent": [1, 2, 3]}, tmp_path / "t.png")
        assert "html" not in specs()[0]

    def _long(self, monkeypatch, tmp_path, html):
        frame = tmp_path / "frame.jpg"
        Image.new("RGB", (1920, 1080), (40, 40, 40)).save(frame)
        second = tmp_path / "second.jpg"
        Image.new("RGB", (1920, 1080), (90, 90, 90)).save(second)
        monkeypatch.setattr(thumbnailer, "_generate_imagen_bg", lambda *a, **kw: None)
        monkeypatch.setattr(thumbnailer, "_frame_source", lambda ws, p: ("v.mp4", {"duration": 100.0}))
        monkeypatch.setattr(thumbnailer, "_pick_best_frame", lambda *a, with_ts=False, **kw: (frame, 30.0) if with_ts else frame)
        monkeypatch.setattr(thumbnailer, "_style_html", lambda: html)
        seen = {}
        monkeypatch.setattr(thumbnailer, "_render_react", lambda spec, output: seen.update(spec) or output.write_bytes(b"PNG") or True)
        return frame, second, seen

    def test_long_picks_a_second_frame_only_when_used(self, monkeypatch, tmp_path):
        frame, second, seen = self._long(monkeypatch, tmp_path, self.HTML)
        calls = []
        monkeypatch.setattr(thumbnailer, "_pick_second_frame", lambda v, d, ws, ts: calls.append(ts) or second)
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert calls == [30.0] and seen["frame2"] == str(second) and not second.exists()

    def test_long_without_frame2_does_not_look_for_it(self, monkeypatch, tmp_path):
        _, _, seen = self._long(monkeypatch, tmp_path, "<div><span>{{titulo}}</span></div>")
        monkeypatch.setattr(thumbnailer, "_pick_second_frame", lambda *a: pytest.fail("looked for frame2"))
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert seen.get("frame2") is None

    def test_second_frame_is_far_from_the_main_one(self, monkeypatch, tmp_path):
        taken = []

        def extract(video, ts, out):
            taken.append(ts)
            Image.new("RGB", (320, 180), (int(ts) % 255, 50, 50)).save(out)
            return out

        monkeypatch.setattr(thumbnailer, "_extract_frame", extract)
        path = thumbnailer._pick_second_frame("v.mp4", 100.0, tmp_path, 30.0)
        assert path is not None and path.exists()
        assert taken and all(abs(ts - 30.0) >= 15.0 for ts in taken)


class TestFaceCutout:
    """Layouts with {{rosto}}/{{rosto_contorno}} get the person cut out of the
    main frame — unless there's a face photo; never at the thumbnail's cost."""

    def _long(self, monkeypatch, tmp_path, html, face_asset=None):
        frame = tmp_path / "frame.jpg"
        Image.new("RGB", (1920, 1080), (40, 40, 40)).save(frame)
        monkeypatch.setattr(thumbnailer, "_generate_imagen_bg", lambda *a, **kw: None)
        monkeypatch.setattr(thumbnailer, "_frame_source", lambda ws, p: ("v.mp4", {"duration": 100.0}))
        monkeypatch.setattr(thumbnailer, "_pick_best_frame", lambda *a, with_ts=False, **kw: (frame, 30.0) if with_ts else frame)
        monkeypatch.setattr(thumbnailer, "_style_html", lambda: html)
        monkeypatch.setattr(thumbnailer, "_find_face_asset", lambda: face_asset)
        seen = {}
        monkeypatch.setattr(thumbnailer, "_render_react", lambda spec, output: seen.update(spec) or output.write_bytes(b"PNG") or True)
        return frame, seen

    def test_layout_with_face_gets_the_cutout(self, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        frame, seen = self._long(monkeypatch, tmp_path, '<div><img src="{{rosto_contorno}}"/></div>')
        calls = []
        monkeypatch.setattr(face_cutout, "cutout_files", lambda frames, folder: calls.append(frames) or {"rosto": tmp_path / "r.png", "rosto_contorno": tmp_path / "c.png"})
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert calls == [[frame]]
        assert seen["face"] == str(tmp_path / "r.png") and seen["face_outline"] == str(tmp_path / "c.png")

    def test_face_photo_wins_and_no_cutout(self, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        photo = tmp_path / "eu.png"
        _, seen = self._long(monkeypatch, tmp_path, '<div><img src="{{rosto}}"/></div>', face_asset=photo)
        monkeypatch.setattr(face_cutout, "cutout_files", lambda *a: pytest.fail("cut out despite the photo"))
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert seen["face"] == str(photo)

    def test_layout_without_face_does_not_cut(self, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        self._long(monkeypatch, tmp_path, "<div><span>{{titulo}}</span></div>")
        monkeypatch.setattr(face_cutout, "cutout_files", lambda *a: pytest.fail("cut out for nothing"))
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})

    def test_cutout_failure_means_no_face(self, monkeypatch, tmp_path, capsys):
        from auto_edit import face_cutout

        _, seen = self._long(monkeypatch, tmp_path, '<div><img src="{{rosto}}"/></div>')

        def boom(*a):
            raise face_cutout.CutoutError("sem internet")

        monkeypatch.setattr(face_cutout, "cutout_files", boom)
        out = thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert out.read_bytes() == b"PNG" and seen.get("face") is None
        assert "sem internet" in capsys.readouterr().out

    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_outlined_cutout_reaches_the_html_spec(self, tmp_path, monkeypatch):
        tokens = styles_mod.validate({"thumbnail": {"html": '<div><img src="{{rosto_contorno}}"/></div>'}})
        monkeypatch.setattr(styles_mod, "active", lambda: {"id": "x", "tokens": tokens})
        log = tmp_path / "spec.json"
        exe = tmp_path / "auto-edit-render"
        exe.write_text(f"#!{sys.executable}\nimport sys, shutil\nshutil.copy(sys.argv[2], {str(log)!r})\nopen(sys.argv[3], 'wb').write(b'PNG')\n")
        exe.chmod(0o755)
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
        monkeypatch.delenv("AUTO_EDIT_THUMB_RENDERER", raising=False)
        thumbnailer._render_react({"kind": "long", "main_text": "x", "accent": [1, 2, 3], "face": "/r.png", "face_outline": "/c.png"}, tmp_path / "t.png")
        images = json.loads(log.read_text())["images"]
        assert images["rosto"] == "/r.png" and images["rosto_contorno"] == "/c.png"
