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


SHORT_TARGET = (1080, 1920)  # 9:16


def _resolve_reframe(video_type: str, w: int, h: int) -> tuple[int, int] | None:
    """Return (target_w, target_h) if the video should be cropped to 9:16, else None.

    Set AUTO_EDIT_NO_REFRAME=1 to skip the crop entirely — keeps the original
    aspect ratio (platforms letterbox it). Useful when the source is landscape
    and center-cropping would upscale too aggressively (e.g. 1080p → 608px wide
    crop stretched to 1080, visibly pixelated).
    """
    if os.environ.get("AUTO_EDIT_NO_REFRAME", "").lower() in ("1", "true", "yes"):
        return None
    if video_type != "short":
        return None
    target_w, target_h = SHORT_TARGET
    target_ratio = target_w / target_h  # 0.5625
    source_ratio = w / h
    if abs(source_ratio - target_ratio) > 0.02:
        return (target_w, target_h)
    return None


def execute(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    video_path = Path(pipeline["video_path"])
    video_type = pipeline.get("type", "short")
    duration = _get_duration(video_path)

    reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
    _validate_plan(reviewed_plan, duration)  # validate before processing
    kept = _build_keep_intervals(reviewed_plan, duration)

    # Snap the first segment's start to the actual audio onset (silencedetect).
    # Without this, the LLM planner often leaves 0.3-1.0s of leading silence
    # before the speaker actually starts — devastating for Reels engagement.
    kept_snapped = snap_start_to_audio_onset(kept, video_path)
    if kept_snapped != kept:
        old_s, _ = kept[0]
        new_s, _ = kept_snapped[0]
        print(f"[executor] Snapped first segment start: {old_s:.2f}s → {new_s:.2f}s (trimmed {new_s-old_s:.2f}s of leading silence)")
        kept = kept_snapped

    if not kept:
        raise RuntimeError("reviewed_plan has no kept_segments — nothing to cut")

    print(f"[executor] Keeping {len(kept)} segments from {duration:.1f}s video")
    for i, (s, e) in enumerate(kept):
        print(f"  [{i+1}] {s:.2f}s → {e:.2f}s  ({e-s:.2f}s)")

    # Detect if short needs aspect ratio conversion
    reframe = None
    if video_type == "short":
        w, h = _get_video_dimensions(video_path)
        reframe = _resolve_reframe(video_type, w, h)
        if reframe:
            print(f"[executor] Reframing {w}x{h} ({w/h:.3f}) → {reframe[0]}x{reframe[1]} (9:16)")
        elif os.environ.get("AUTO_EDIT_NO_REFRAME"):
            print(f"[executor] AUTO_EDIT_NO_REFRAME set — keeping original {w}x{h}")

    output = workspace / "edited_video.mp4"
    _run_ffmpeg_cuts(video_path, kept, output, reframe=reframe)
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

        # A degenerate cut (start>=end) removes nothing — the LLM planner
        # occasionally emits micro-inversions (~0.1s). It's a no-op, not a
        # fatal error: warn and let it be dropped downstream instead of
        # killing the whole pipeline. kept_segments (validated above) is what
        # actually drives the output.
        if start >= end:
            print(f"[executor] Ignoring degenerate cut[{i}] start={start:.3f} >= end={end:.3f} (no-op)")


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


def _detect_audio_onset(
    video: Path,
    segment_start: float,
    segment_end: float,
    noise_db: float = -40.0,
    min_silence_dur: float = 0.1,
) -> float | None:
    """Run ffmpeg silencedetect on [segment_start, segment_end] of the source
    and return the timestamp (in source timeline) where audible content starts.
    Returns None if no leading silence is detected.
    """
    probe_dur = min(3.0, segment_end - segment_start)
    if probe_dur <= 0:
        return None
    cmd = [
        "ffmpeg", "-hide_banner", "-ss", f"{segment_start:.3f}",
        "-t", f"{probe_dur:.3f}", "-i", str(video),
        "-af", f"silencedetect=noise={noise_db}dB:duration={min_silence_dur}",
        "-vn", "-f", "null", os.devnull,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # ffmpeg itself failed (missing binary, unreadable input, etc.);
        # don't pretend silence was just absent — surface it and skip the snap.
        print(f"[executor] silencedetect probe failed (rc={result.returncode}), skipping leading-silence snap")
        return None
    output = result.stderr
    # Look for "silence_start: 0" followed by "silence_end: X" — that's leading silence.
    leading_silence_start = None
    for line in output.splitlines():
        if "silence_start:" in line:
            try:
                val = float(line.split("silence_start:")[1].strip().split()[0])
                if leading_silence_start is None and abs(val) < 0.05:  # silence at very start of probe
                    leading_silence_start = val
            except (ValueError, IndexError):
                continue
        elif "silence_end:" in line and leading_silence_start is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
                # end is relative to probe start (ss); map back to source timeline
                return segment_start + end
            except (ValueError, IndexError):
                return None
    return None


def snap_start_to_audio_onset(
    intervals: list[tuple[float, float]],
    video: Path,
    leading_pad: float = 0.08,
    min_silence: float = 0.2,
) -> list[tuple[float, float]]:
    """If the first kept interval has > min_silence of leading silence (per
    silencedetect on the actual audio), advance its start to
    (onset - leading_pad). Only touches the first segment.
    """
    if not intervals:
        return intervals
    first_start, first_end = intervals[0]
    onset = _detect_audio_onset(video, first_start, first_end)
    if onset is None:
        return intervals
    if (onset - first_start) < min_silence:
        return intervals
    new_start = max(first_start, onset - leading_pad)
    if new_start <= first_start:
        return intervals
    return [(new_start, first_end)] + intervals[1:]


def _invert_cuts(cuts: list[dict], duration: float) -> list[dict]:
    """Convert a list of cut intervals into keep intervals."""
    keep = []
    cursor = 0.0
    for cut in cuts:
        s = float(cut["start"])
        e = float(cut["end"])
        if s >= e:
            continue  # degenerate cut (no-op) — skip so cursor never regresses
        if s > cursor:
            keep.append({"start": cursor, "end": s})
        cursor = e
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


def _get_video_dimensions(video: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def _build_filter(
    intervals: list[tuple[float, float]],
    reframe: tuple[int, int] | None = None,
) -> str:
    parts = []
    concat_inputs = ""
    for i, (start, end) in enumerate(intervals):
        parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs += f"[v{i}][a{i}]"
    n = len(intervals)

    if reframe:
        tw, th = reframe
        # concat → crop to target aspect ratio (center) → scale to target size
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[concatv][outa_raw]")
        parts.append(
            f"[concatv]crop=ih*{tw}/{th}:ih:(iw-ih*{tw}/{th})/2:0,"
            f"scale={tw}:{th}:flags=lanczos[outv]"
        )
    else:
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa_raw]")

    # Normalize audio loudness after concatenation (EBU R128), then force a
    # well-defined stereo channel layout. Without this aformat step, the AAC
    # encoder writes a malformed mp4a/chnl atom (especially when source is mono),
    # which Apple decoders (QuickTime/iPhone) reject silently — file plays
    # video but no audio.
    parts.append(
        "[outa_raw]loudnorm=I=-16:TP=-1.5:LRA=11,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo[outa]"
    )
    return ";".join(parts)


def _run_ffmpeg_cuts(
    video: Path,
    intervals: list[tuple[float, float]],
    output: Path,
    reframe: tuple[int, int] | None = None,
) -> None:
    filter_str = _build_filter(intervals, reframe=reframe)
    codec, codec_flags = _get_video_codec()

    base_cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", codec, *codec_flags,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-brand", "mp42",
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

    _fix_av_duration_mismatch(output)


def _get_stream_duration(video: Path, stream_type: str) -> float:
    """Get duration of a specific stream type ('v:0' or 'a:0')."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", stream_type,
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip().split("\n")[0])


def _fix_av_duration_mismatch(video: Path, tolerance: float = 1.0) -> None:
    """If audio duration exceeds video duration beyond tolerance, trim audio to match."""
    try:
        v_dur = _get_stream_duration(video, "v:0")
        a_dur = _get_stream_duration(video, "a:0")
    except (subprocess.CalledProcessError, ValueError):
        return

    if a_dur <= v_dur + tolerance:
        return

    print(f"[executor] Audio/video duration mismatch: video={v_dur:.1f}s audio={a_dur:.1f}s — fixing...")
    fixed = video.with_suffix(".fixed.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-filter_complex",
        f"[0:a]atrim=end={v_dur:.3f},asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-brand", "mp42",
        str(fixed),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and fixed.exists():
        fixed.replace(video)
        print(f"[executor] Fixed — audio trimmed to {v_dur:.1f}s")
    else:
        fixed.unlink(missing_ok=True)
        print("[executor] Warning: could not fix duration mismatch")


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
