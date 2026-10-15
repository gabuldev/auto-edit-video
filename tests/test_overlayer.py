"""Tests for tools/overlayer.py.

Two concerns:

1. Frame-rate handling in the FFmpeg command. Regression: the concat'd edit is
   slightly VFR, so `overlay` resolved the output to a doubled timebase (59.94
   for a 29.97 edit) and the encoder emitted every frame as if it belonged there
   — video played at 2x while audio stayed put.
2. Overlay resolution and the missing-asset gate: which planned overlays are
   found / missing / removed-by-cut, and whether a missing .mp4 is skipped with
   a warning (default) or fails the stage (AUTO_EDIT_OVERLAYS_STRICT=1).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import overlayer
from tools.overlayer import (
    _resolve_overlays,
    _check_assets_present,
    _missing_assets_message,
)
from auto_edit.overlay_assets import overlay_search_dirs


# ── Frame-rate handling (2x/slow-motion regression) ──────────────────────────

def _capture_cmd(monkeypatch, fps="30000/1001", has_audio=True):
    """Run _run_ffmpeg_overlay with FFmpeg stubbed; return the argv it built."""
    captured = {}

    class Result:
        returncode = 0

    monkeypatch.setattr(overlayer, "_video_size", lambda p: (3840, 2160))
    monkeypatch.setattr(overlayer, "_video_fps", lambda p: fps)
    monkeypatch.setattr(overlayer, "_has_audio_stream", lambda p: has_audio)
    monkeypatch.setattr(overlayer, "_get_video_codec", lambda: ("libx264", ["-crf", "23"]))
    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr(overlayer.subprocess, "run", fake_run)

    overlayer._run_ffmpeg_overlay(
        Path("edit.mp4"),
        [{"asset": Path("cta.mp4"), "start": 2.0, "end": 8.0}],
        Path("out.mp4"),
    )
    return captured["cmd"]


def test_output_is_pinned_to_the_edit_frame_rate(monkeypatch):
    cmd = _capture_cmd(monkeypatch)

    assert "-r" in cmd
    assert cmd[cmd.index("-r") + 1] == "30000/1001"
    assert "-fps_mode" in cmd and cmd[cmd.index("-fps_mode") + 1] == "cfr"


def test_both_streams_are_normalized_before_overlay(monkeypatch):
    cmd = _capture_cmd(monkeypatch)
    filters = cmd[cmd.index("-filter_complex") + 1]

    assert "[0:v]fps=30000/1001[base]" in filters  # main video
    assert "[1:v]fps=30000/1001,scale=" in filters  # overlay asset
    assert "[base][ck0]overlay=" in filters


def test_unknown_frame_rate_falls_back_to_previous_behaviour(monkeypatch):
    """Never block the render because ffprobe could not report a frame rate."""
    cmd = _capture_cmd(monkeypatch, fps=None)
    filters = cmd[cmd.index("-filter_complex") + 1]

    assert "-r" not in cmd
    assert "fps=" not in filters
    assert "[0:v][ck0]overlay=" in filters


def test_audio_is_copied_untouched(monkeypatch):
    cmd = _capture_cmd(monkeypatch)

    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_video_without_audio_maps_no_audio(monkeypatch):
    cmd = _capture_cmd(monkeypatch, has_audio=False)

    assert "-c:a" not in cmd


# ── Overlay resolution + missing-asset gate ──────────────────────────────────

KEPT = [(0.0, 10.0), (20.0, 30.0)]  # 10-20s is cut


class TestResolveOverlays:
    def test_found_missing_and_removed_are_split(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")  # asset present
        overlays = [
            {"file": "ctas.mp4", "original_start": 5.0},    # kept → found
            {"file": "gone.mp4", "original_start": 5.0},    # asset absent → missing
            {"file": "ctas.mp4", "original_start": 15.0},   # inside a cut → removed
        ]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)

        assert missing == ["gone.mp4"]
        assert removed == ["ctas.mp4"]
        assert len(found) == 1
        ov, kind, asset, post_cut_start = found[0]
        assert kind == "cta"
        assert asset == tmp_path / "ctas.mp4"
        assert post_cut_start == pytest.approx(5.0)

    def test_timestamp_after_cut_remaps_to_compacted_timeline(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")
        overlays = [{"file": "ctas.mp4", "original_start": 25.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert not missing and not removed
        # 25s sits in the second kept block; first block (10s) is prepended.
        assert found[0][3] == pytest.approx(15.0)

    def test_all_found(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"x")
        overlays = [{"file": "a.mp4", "original_start": 1.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert len(found) == 1 and not missing and not removed


class TestKindsAndSources:
    def test_legacy_file_names_map_to_kinds(self):
        assert overlayer._kind({"file": "ctas.mp4"}) == "cta"
        assert overlayer._kind({"file": "lowerthid_gabul.mp4"}) == "lower_third"
        assert overlayer._kind({"overlay": "lower_third"}) == "lower_third"
        assert overlayer._kind({"file": "custom.mp4"}) is None

    def test_start_is_already_on_the_edit(self, tmp_path):
        """The agent reads the post-cut transcript (cold open, reordered blocks
        included), so `start` is used as is — no remap, no kept segments."""
        found, missing, removed = _resolve_overlays(
            [{"overlay": "cta", "start": 15.0}], [tmp_path], None)
        assert not missing and not removed
        assert found[0][3] == pytest.approx(15.0)

    def test_no_mp4_means_react(self, tmp_path):
        found, missing, _ = _resolve_overlays(
            [{"overlay": "lower_third", "start": 3.0}], [tmp_path], None)
        assert not missing
        _, kind, asset, _ = found[0]
        assert kind == "lower_third" and asset is None

    def test_own_mp4_wins_by_default(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")
        found, _, _ = _resolve_overlays([{"overlay": "cta", "start": 1.0}], [tmp_path], None)
        assert found[0][2] == tmp_path / "ctas.mp4"

    def test_source_react_ignores_the_mp4(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")
        found, _, _ = _resolve_overlays([{"overlay": "cta", "start": 1.0}], [tmp_path], None, "react")
        assert found[0][2] is None

    def test_source_mp4_without_the_file_is_missing(self, tmp_path):
        found, missing, _ = _resolve_overlays([{"overlay": "cta", "start": 1.0}], [tmp_path], None, "mp4")
        assert not found and missing == ["ctas.mp4"]

    def test_custom_file_without_mp4_is_missing(self, tmp_path):
        """React only stands in for the kinds it knows how to draw."""
        found, missing, _ = _resolve_overlays([{"file": "intro.mp4", "start": 1.0}], [tmp_path], None)
        assert not found and missing == ["intro.mp4"]

    def test_bad_source_env_is_auto(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_OVERLAY_SOURCE", "whatever")
        assert overlayer._source() == "auto"


class TestFfmpegPlacement:
    def test_mp4_is_shifted_to_its_start(self, monkeypatch):
        """Regression: without setpts the MP4's clock started at 0, so an
        overlay placed past its own length only showed its last (empty) frame."""
        filters = (cmd := _capture_cmd(monkeypatch))[cmd.index("-filter_complex") + 1]
        assert "setpts=PTS-STARTPTS+2.000/TB[ck0]" in filters
        assert "eof_action=pass" in filters

    def test_react_frames_are_a_concat_input_placed_at_x_y(self, monkeypatch):
        captured = {}

        class Result:
            returncode = 0

        monkeypatch.setattr(overlayer, "_video_size", lambda p: (3840, 2160))
        monkeypatch.setattr(overlayer, "_video_fps", lambda p: "30000/1001")
        monkeypatch.setattr(overlayer, "_has_audio_stream", lambda p: True)
        monkeypatch.setattr(overlayer, "_get_video_codec", lambda: ("libx264", []))
        monkeypatch.setattr(overlayer.subprocess, "run", lambda cmd, *a, **k: captured.setdefault("cmd", cmd) and Result())
        overlayer._run_ffmpeg_overlay(
            Path("edit.mp4"),
            [{"frames": Path("lt/frames.txt"), "x": 120, "y": 1620, "start": 30.0, "end": 36.0},
             {"asset": Path("ctas.mp4"), "start": 90.0, "end": 98.0}],
            Path("out.mp4"),
        )
        cmd = captured["cmd"]
        i = cmd.index(str(Path("lt/frames.txt")))
        assert cmd[i - 5:i] == ["-f", "concat", "-safe", "0", "-i"]
        filters = cmd[cmd.index("-filter_complex") + 1]
        assert "[1:v]format=rgba,setpts=PTS-STARTPTS+30.000/TB[ck0]" in filters
        assert "overlay=x=120:y=1620:eof_action=pass" in filters
        assert "[ovchain0][ck1]overlay=x=0:y=0" in filters  # the MP4 is still chroma-keyed after it


FAKE_RENDERER = """#!/bin/sh
# fake auto-edit-render: overlay <spec> <dir>
echo "$2" > "$3/spec_seen"
cp "$2" "$3/spec_copy.json"
printf 'ffconcat version 1.0\nfile f00000.png\n' > "$3/frames.txt"
echo '{"x":10,"y":20,"width":100,"height":50,"duration":6,"frames":180,"unique":3}' > "$3/overlay.json"
"""


class TestRenderReact:
    @pytest.fixture
    def fake_bin(self, tmp_path, monkeypatch):
        exe = tmp_path / "auto-edit-render"
        exe.write_text(FAKE_RENDERER)
        exe.chmod(0o755)
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
        monkeypatch.setattr(overlayer, "_video_size", lambda p: (1920, 1080))
        monkeypatch.setattr(overlayer, "_video_fps", lambda p: "30000/1001")
        return exe

    @pytest.mark.skipif(sys.platform == "win32", reason="shell script renderer")
    def test_renders_with_the_brand_and_the_video_size(self, fake_bin, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(overlayer.render, "brand", lambda: {"name": "Gabul", "handle": "@gabul.dev", "logo": None})
        r = overlayer._render_react("lower_third", Path("v.mp4"), tmp_path / "lt")
        assert r["x"] == 10 and r["duration"] == 6
        assert r["frames_file"] == tmp_path / "lt" / "frames.txt"
        spec = json.loads((tmp_path / "lt" / "spec_copy.json").read_text())
        assert spec["kind"] == "lower_third" and spec["brand"]["name"] == "Gabul"
        assert spec["style"]["colors"]["accent"] == "#00d6ff"  # the default style
        assert set(spec["fonts"]) == {"Bold", "Regular"}
        assert (spec["video_width"], spec["video_height"]) == (1920, 1080)
        assert spec["fps"] == pytest.approx(29.97, abs=0.01)

    def test_lower_third_without_a_name_is_skipped(self, fake_bin, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(overlayer.render, "brand", lambda: {"name": None, "handle": None, "logo": None})
        assert overlayer._render_react("lower_third", Path("v.mp4"), tmp_path / "lt") is None
        assert "no name" in capsys.readouterr().out

    def test_no_renderer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(overlayer.render, "command", lambda: None)
        assert overlayer._render_react("cta", Path("v.mp4"), tmp_path / "c") is None

    @pytest.mark.skipif(sys.platform == "win32", reason="shell script renderer")
    def test_renderer_failure(self, tmp_path, monkeypatch):
        exe = tmp_path / "bad"
        exe.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
        exe.chmod(0o755)
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
        monkeypatch.setattr(overlayer, "_video_size", lambda p: (1920, 1080))
        monkeypatch.setattr(overlayer, "_video_fps", lambda p: None)
        assert overlayer._render_react("cta", Path("v.mp4"), tmp_path / "c") is None


class TestCheckAssetsPresent:
    def test_no_missing_is_noop(self, capsys):
        _check_assets_present([], [Path("/nowhere")])
        assert capsys.readouterr().out == ""

    def test_missing_only_warns_by_default(self, monkeypatch, capsys):
        """Overlays live outside the repo, so a fresh install has none — the
        edit must still ship instead of dying at the overlay stage."""
        monkeypatch.delenv("AUTO_EDIT_OVERLAYS_STRICT", raising=False)
        _check_assets_present(["ctas.mp4"], [Path("/opt/overlays")])  # must not raise
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "ctas.mp4" in out

    def test_strict_env_turns_it_into_a_failure(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_OVERLAYS_STRICT", "1")
        with pytest.raises(FileNotFoundError, match="not found"):
            _check_assets_present(["ctas.mp4"], [Path("/opt/overlays")])

    def test_message_points_at_the_env_var(self):
        msg = _missing_assets_message(["ctas.mp4"], [Path("/opt/overlays")])
        assert "ctas.mp4" in msg
        assert "AUTO_EDIT_ASSETS_OVERLAYS" in msg


class TestOverlaySearchDirs:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTO_EDIT_ASSETS_OVERLAYS", str(tmp_path))
        dirs = overlay_search_dirs(Path("/some/repo"))
        assert dirs == [tmp_path.resolve()]

    def test_default_is_assets_then_mirror(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_ASSETS_OVERLAYS", raising=False)
        repo = Path("/some/repo")
        dirs = overlay_search_dirs(repo)
        # overlay_search_dirs resolves the root (adds the drive on Windows).
        root = repo.resolve()
        assert dirs == [root / "assets" / "overlays", root / "overlays"]
