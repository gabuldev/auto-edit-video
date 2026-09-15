"""Tests for tools/overlayer.py.

Two concerns:

1. Frame-rate handling in the FFmpeg command. Regression: the concat'd edit is
   slightly VFR, so `overlay` resolved the output to a doubled timebase (59.94
   for a 29.97 edit) and the encoder emitted every frame as if it belonged there
   — video played at 2x while audio stayed put.
2. Overlay resolution and the missing-asset gate: which planned overlays are
   found / missing / removed-by-cut, and whether a missing .mp4 fails the stage
   (default) or is skipped (AUTO_EDIT_OVERLAYS_OPTIONAL=1).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import overlayer
from tools.overlayer import (
    _resolve_overlays,
    _require_assets_present,
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
        ov, asset, post_cut_start = found[0]
        assert asset == tmp_path / "ctas.mp4"
        assert post_cut_start == pytest.approx(5.0)

    def test_timestamp_after_cut_remaps_to_compacted_timeline(self, tmp_path):
        (tmp_path / "ctas.mp4").write_bytes(b"x")
        overlays = [{"file": "ctas.mp4", "original_start": 25.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert not missing and not removed
        # 25s sits in the second kept block; first block (10s) is prepended.
        assert found[0][2] == pytest.approx(15.0)

    def test_all_found(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"x")
        overlays = [{"file": "a.mp4", "original_start": 1.0}]
        found, missing, removed = _resolve_overlays(overlays, [tmp_path], KEPT)
        assert len(found) == 1 and not missing and not removed


class TestRequireAssetsPresent:
    def test_no_missing_is_noop(self):
        _require_assets_present([], [Path("/nowhere")])  # must not raise

    def test_missing_raises_by_default(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_OVERLAYS_OPTIONAL", raising=False)
        with pytest.raises(FileNotFoundError, match="not found"):
            _require_assets_present(["ctas.mp4"], [Path("/opt/overlays")])

    def test_optional_env_downgrades_to_warning(self, monkeypatch, capsys):
        monkeypatch.setenv("AUTO_EDIT_OVERLAYS_OPTIONAL", "1")
        _require_assets_present(["ctas.mp4"], [Path("/opt/overlays")])  # must not raise
        assert "WARNING" in capsys.readouterr().out

    def test_message_points_at_the_env_var(self):
        msg = _missing_assets_message(["ctas.mp4"], [Path("/opt/overlays")])
        assert "ctas.mp4" in msg
        assert "AUTO_EDIT_ASSETS_OVERLAYS" in msg
        assert "AUTO_EDIT_OVERLAYS_OPTIONAL" in msg


class TestOverlaySearchDirs:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTO_EDIT_ASSETS_OVERLAYS", str(tmp_path))
        dirs = overlay_search_dirs(Path("/some/repo"))
        assert dirs == [tmp_path.resolve()]

    def test_default_is_assets_then_mirror(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_ASSETS_OVERLAYS", raising=False)
        repo = Path("/some/repo")
        dirs = overlay_search_dirs(repo)
        assert dirs == [repo / "assets" / "overlays", repo / "overlays"]
