"""
EXECUTOR stage — Fase 3
Reads reviewed_plan.json, applies end-padding (default 0.2s, override AUTO_EDIT_END_PADDING), runs FFmpeg cuts.
Writes workspace/edited_video.mp4 and updates pipeline stage.

Usage: python tools/executor.py <workspace_dir>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FILTER_SCRIPT_THRESHOLD = 100  # above this, write filter to file (avoids ARG_MAX)
MIN_INTERVAL_DURATION = 1.0 / 30  # 1 frame at 30fps ≈ 0.033s

_CODEC_PREFERENCE = [
    ("h264_videotoolbox", ["-q:v", "50"]),
    ("libx264",           ["-crf", "23", "-preset", "fast"]),
    ("libx265",           ["-crf", "28", "-preset", "fast"]),
]


def _get_video_codec() -> tuple[str, list[str]]:
    """Return (codec_name, extra_flags) for the best available H.264/H.265 encoder."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True
    )
    for codec, flags in _CODEC_PREFERENCE:
        if codec in result.stdout:
            return codec, flags
    # Fallback to libx264 (almost universally available)
    return "libx264", ["-crf", "23", "-preset", "fast"]


def execute(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    video_path = Path(pipeline["video_path"])
    duration = _get_duration(video_path)

    reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
    _validate_plan(reviewed_plan, duration)  # validate before processing
    kept = _build_keep_intervals(reviewed_plan, duration)

    if not kept:
        raise RuntimeError("reviewed_plan has no kept_segments — nothing to cut")

    print(f"[executor] Keeping {len(kept)} segments from {duration:.1f}s video")
    for i, (s, e) in enumerate(kept):
        print(f"  [{i+1}] {s:.2f}s → {e:.2f}s  ({e-s:.2f}s)")

    output = workspace / "edited_video.mp4"
    _run_ffmpeg_cuts(video_path, kept, output)
    print(f"[executor] Done → {output}")


# ── Interval logic ────────────────────────────────────────────────────────────

def _validate_plan(plan: dict, duration: float) -> None:
    """Raise ValueError with a clear message if the cut plan has invalid bounds."""
    segments = plan.get("kept_segments", [])
    cuts = plan.get("cuts", [])

    if not segments and not cuts:
        raise ValueError("reviewed_plan.json has neither kept_segments nor cuts")

    for i, seg in enumerate(segments):
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"kept_segments[{i}] missing/invalid start or end: {e}") from e

        if start < 0:
            raise ValueError(f"kept_segments[{i}] start={start} is negative")
        if end > duration + 1.0:  # 1s tolerance for rounding
            raise ValueError(
                f"kept_segments[{i}] end={end:.3f} exceeds video duration {duration:.3f}"
            )
        if start >= end:
            raise ValueError(
                f"kept_segments[{i}] start={start:.3f} >= end={end:.3f} (empty interval)"
            )

    for i, cut in enumerate(cuts):
        try:
            start = float(cut["start"])
            end = float(cut["end"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"cuts[{i}] missing/invalid start or end: {e}") from e

        if start >= end:
            raise ValueError(f"cuts[{i}] start={start:.3f} >= end={end:.3f}")


def _build_keep_intervals(plan: dict, duration: float) -> list[tuple[float, float]]:
    """
    Convert kept_segments from reviewed_plan.json into (start, end) tuples.
    Applies end-padding (default 0.2s, override AUTO_EDIT_END_PADDING) to each
    segment end (not start) to avoid cutting word tails.
    Clamps to video duration and merges overlapping intervals.
    """
    end_padding = float(os.environ.get("AUTO_EDIT_END_PADDING", "0.2"))
    raw = plan.get("kept_segments", [])
    if not raw:
        # Fallback: invert the cuts list
        cuts = sorted(plan.get("cuts", []), key=lambda c: c["start"])
        raw = _invert_cuts(cuts, duration)

    padded: list[tuple[float, float]] = []
    for seg in raw:
        start = max(0.0, float(seg["start"]))
        end = min(duration, float(seg["end"]) + end_padding)
        if end > start:
            padded.append((start, end))

    merged = _merge_intervals(sorted(padded))

    # filter out sub-frame intervals that would produce 0 frames in concat
    filtered = [(s, e) for s, e in merged if (e - s) >= MIN_INTERVAL_DURATION]
    if not filtered:
        raise RuntimeError("All kept segments are shorter than 1 frame — nothing to output")

    return filtered


def _invert_cuts(cuts: list[dict], duration: float) -> list[dict]:
    """Convert a list of cut intervals into keep intervals."""
    keep = []
    cursor = 0.0
    for cut in cuts:
        s = float(cut["start"])
        if s > cursor:
            keep.append({"start": cursor, "end": s})
        cursor = float(cut["end"])
    if cursor < duration:
        keep.append({"start": cursor, "end": duration})
    return keep


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or touching intervals."""
    if not intervals:
        return []
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


# ── FFmpeg execution ──────────────────────────────────────────────────────────

def _get_duration(video: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _build_filter(intervals: list[tuple[float, float]]) -> str:
    parts = []
    concat_inputs = ""
    for i, (start, end) in enumerate(intervals):
        parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs += f"[v{i}][a{i}]"
    n = len(intervals)
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa_raw]")
    # Normalize audio loudness after concatenation (EBU R128)
    parts.append("[outa_raw]loudnorm=I=-16:TP=-1.5:LRA=11[outa]")
    return ";".join(parts)


def _run_ffmpeg_cuts(video: Path, intervals: list[tuple[float, float]], output: Path) -> None:
    filter_str = _build_filter(intervals)
    codec, codec_flags = _get_video_codec()

    base_cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", codec, *codec_flags,
        "-c:a", "aac", "-b:a", "192k",
        str(output),
    ]

    if len(intervals) > FILTER_SCRIPT_THRESHOLD:
        # Write filter to file to avoid OS ARG_MAX limit
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(filter_str)
            script_path = f.name
        cmd = [base_cmd[0], "-y", "-i", str(video),
               "-filter_complex_script", script_path,
               *base_cmd[4:]]
    else:
        cmd = base_cmd[:3] + [base_cmd[3], "-filter_complex", filter_str] + base_cmd[4:]

    print(f"[executor] Running FFmpeg ({len(intervals)} segments)...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed — see output above")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/executor.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)

    ws = Path(sys.argv[1])
    if not ws.exists():
        print(f"Workspace not found: {ws}", file=sys.stderr)
        sys.exit(1)

    execute(ws)
