"""tools/overlayer.py — frame-rate handling in the FFmpeg command.

Regression: the concat'd edit is slightly VFR, so `overlay` resolved the output
to a doubled timebase (59.94 for a 29.97 edit) and the encoder emitted every
frame as if it belonged there — video played at 2x while audio stayed put.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import overlayer


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
