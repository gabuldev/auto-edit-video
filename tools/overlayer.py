"""
OVERLAYER stage
Reads overlay_plan.json, remaps original timestamps to post-cut timeline,
applies chroma key + overlay using FFmpeg.
Input:  workspace/edited_video.mp4
Output: workspace/overlaid_video.mp4 (or skips if no overlays planned)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auto_edit import overlay_assets, probe  # noqa: E402  -- needs repo root on sys.path


def _overlay_search_dirs() -> list[Path]:
    """Folders to look for overlay MP4s (see overlay_assets.overlay_search_dirs).

    1) AUTO_EDIT_ASSETS_OVERLAYS — single explicit path
    2) <repo>/assets/overlays (canonical)
    3) <repo>/overlays — optional flat folder at repo root (same filenames)
    """
    return overlay_assets.overlay_search_dirs()


def _find_overlay_file(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.is_file():
            return p
    return None


def _overlays_optional() -> bool:
    """Whether a missing overlay asset is a warning rather than a hard error.

    Default: a planned overlay whose .mp4 can't be found fails the stage — the
    whole point of the overlay is that it appears, and silently shipping the
    video without it is how the problem went unnoticed. Set
    AUTO_EDIT_OVERLAYS_OPTIONAL=1 to skip missing overlays and render anyway.
    """
    return os.environ.get("AUTO_EDIT_OVERLAYS_OPTIONAL", "").lower() in ("1", "true", "yes")


def _missing_assets_message(missing: list[str], search_dirs: list[Path]) -> str:
    files = "\n".join(f"    - {n}" for n in missing)
    dirs = "\n".join(f"    - {d}" for d in search_dirs)
    return (
        "overlay asset(s) not found:\n"
        f"{files}\n"
        "  searched in:\n"
        f"{dirs}\n"
        "  Fix: put the .mp4 file(s) in one of those folders, or point\n"
        "  AUTO_EDIT_ASSETS_OVERLAYS at the folder that has them, e.g.\n"
        "    export AUTO_EDIT_ASSETS_OVERLAYS=/path/to/your/overlays\n"
        "  To render the video WITHOUT these overlays instead of failing,\n"
        "  set AUTO_EDIT_OVERLAYS_OPTIONAL=1."
    )


def _resolve_overlays(
    overlays: list[dict],
    search_dirs: list[Path],
    kept: list[tuple[float, float]],
) -> tuple[list[tuple[dict, Path, float]], list[str], list[str]]:
    """Split planned overlays into (found, missing_asset, removed_by_cut).

    - found: ``(overlay, asset_path, post_cut_start)`` tuples ready to place.
    - missing_asset: file names not present in any search dir (a setup error).
    - removed_by_cut: trigger timestamps that fell inside a removed section.
    """
    found: list[tuple[dict, Path, float]] = []
    missing: list[str] = []
    removed: list[str] = []
    for ov in overlays:
        name = ov["file"]
        asset = _find_overlay_file(name, search_dirs)
        if asset is None:
            missing.append(name)
            continue
        post_cut_start = _remap(float(ov["original_start"]), kept)
        if post_cut_start is None:
            removed.append(name)
            continue
        found.append((ov, asset, post_cut_start))
    return found, missing, removed


def _require_assets_present(missing: list[str], search_dirs: list[Path]) -> None:
    """Raise on any missing overlay asset, unless overlays are opted-out."""
    if not missing:
        return
    msg = _missing_assets_message(missing, search_dirs)
    if _overlays_optional():
        print(f"[overlayer] WARNING (AUTO_EDIT_OVERLAYS_OPTIONAL): {msg}")
        return
    raise FileNotFoundError(msg)


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
    return "libx264", ["-crf", "23", "-preset", "fast"]


CHROMA_COLOR = "0x00FF00"
CHROMA_SIMILARITY = "0.15"
CHROMA_BLEND = "0.05"


def overlay(workspace: Path) -> None:
    plan = json.loads((workspace / "overlay_plan.json").read_text())
    overlays = plan.get("overlays", [])

    if not overlays:
        print("[overlayer] No overlays planned — skipping.")
        return

    search_dirs = _overlay_search_dirs()
    print(f"[overlayer] Overlay search dirs: {', '.join(str(d) for d in search_dirs)}")

    pipeline = json.loads((workspace / "pipeline.json").read_text())
    reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
    kept = _build_kept_intervals(reviewed_plan, pipeline)

    found, missing, removed = _resolve_overlays(overlays, search_dirs, kept)

    # A missing asset is a setup error, not a content miss: fail loudly instead
    # of silently shipping a video without the overlay the planner asked for.
    # (Opt out with AUTO_EDIT_OVERLAYS_OPTIONAL=1.)
    _require_assets_present(missing, search_dirs)

    for name in removed:
        print(
            f"[overlayer] WARNING: {name}: its trigger timestamp was removed by "
            "cuts — overlay skipped (pick a moment inside a kept segment)."
        )

    placed = []
    for ov, asset, post_cut_start in found:
        duration = _get_duration(asset)
        placed.append({"asset": asset, "start": post_cut_start, "end": post_cut_start + duration})
        print(f"[overlayer] '{ov['file']}' -> post-cut {post_cut_start:.2f}s-{post_cut_start + duration:.2f}s")

    input_video = workspace / "edited_video.mp4"
    output_video = workspace / "overlaid_video.mp4"
    if placed:
        _run_ffmpeg_overlay(input_video, placed, output_video)
    else:
        import shutil
        shutil.copy2(input_video, output_video)
        print("[overlayer] No overlays applied — copied edited video as-is")
    print(f"[overlayer] Done -> {output_video}")


# ── Interval helpers ──────────────────────────────────────────────────────────

def _build_kept_intervals(reviewed_plan: dict, pipeline: dict) -> list[tuple[float, float]]:
    """Reconstruct kept intervals from reviewed_plan (same logic as executor)."""
    from tools.executor import _build_keep_intervals, _get_duration as _vid_duration
    video_path = Path(pipeline["video_path"])
    duration = _vid_duration(video_path)
    return _build_keep_intervals(reviewed_plan, duration)


def _remap(original_ts: float, kept: list[tuple[float, float]]) -> float | None:
    """Map an original-video timestamp to a post-cut timestamp. Returns None if in a cut."""
    accumulated = 0.0
    for start, end in kept:
        if original_ts < start:
            return None  # falls in a removed section
        if original_ts <= end:
            return accumulated + (original_ts - start)
        accumulated += end - start
    return None


# ── FFmpeg ────────────────────────────────────────────────────────────────────

def _get_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _has_audio_stream(path: Path) -> bool:
    return probe.has_audio_stream(path)


def _video_fps(path: Path) -> str | None:
    """Nominal frame rate of the video stream, as the "30000/1001" fraction."""
    return probe.video_fps(path)


def _video_size(path: Path) -> tuple[int, int]:
    return probe.video_size(path)


def _run_ffmpeg_overlay(
    video: Path,
    placed: list[dict],
    output: Path,
) -> None:
    # Build input args: main video + one input per unique asset
    assets = list({p["asset"] for p in placed})
    asset_index = {a: i + 1 for i, a in enumerate(assets)}

    input_args = ["-i", str(video)]
    for asset in assets:
        input_args += ["-i", str(asset)]

    vw, vh = _video_size(video)
    print(f"[overlayer] Main video {vw}x{vh} — scaling each overlay to fit frame before chromakey")

    # Scale each overlay to the main video frame (letterbox pad), then chromakey, then overlay.
    # Plain overlay=0:0 without scaling hides 1080p assets in a corner of a 4K edit.
    # The concat'd edit is slightly VFR, so `overlay` resolves the output to a
    # doubled timebase and the encoder emits every frame as if it were 60fps --
    # video runs at 2x while audio stays put. Pin both sides to the edit's own
    # frame rate instead.
    fps = _video_fps(video)
    filter_parts: list[str] = []
    prev = "0:v"
    if fps:
        filter_parts.append(f"[0:v]fps={fps}[base]")
        prev = "base"
    for i, p in enumerate(placed):
        idx = asset_index[p["asset"]]
        out_label = "outv" if i == len(placed) - 1 else f"ovchain{i}"
        enable = f"between(t,{p['start']:.3f},{p['end']:.3f})"
        filter_parts.append(
            f"[{idx}:v]" + (f"fps={fps}," if fps else "")
            + f"scale=w={vw}:h={vh}:force_original_aspect_ratio=decrease,"
            f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2,setsar=1[ov_s{i}]"
        )
        filter_parts.append(
            f"[ov_s{i}]chromakey=color={CHROMA_COLOR}:similarity={CHROMA_SIMILARITY}:blend={CHROMA_BLEND}[ck{i}]"
        )
        filter_parts.append(
            f"[{prev}][ck{i}]overlay=x=0:y=0:enable='{enable}'[{out_label}]"
        )
        prev = out_label

    filter_str = ";".join(filter_parts)
    codec, codec_flags = _get_video_codec()

    cmd: list[str] = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_str,
        "-map", "[outv]",
    ]
    if _has_audio_stream(video):
        cmd += ["-map", "0:a", "-c:a", "copy"]
    cmd += ["-c:v", codec, *codec_flags]
    if fps:
        # Constant frame rate on the way out, so the muxed duration matches audio.
        cmd += ["-r", fps, "-fps_mode", "cfr"]
    cmd += [str(output)]

    print(f"[overlayer] Running FFmpeg ({len(placed)} overlays)...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed during overlay — see output above")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/overlayer.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)

    ws = Path(sys.argv[1])
    if not ws.exists():
        print(f"Workspace not found: {ws}", file=sys.stderr)
        sys.exit(1)

    overlay(ws)
