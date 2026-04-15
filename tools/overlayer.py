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


def _repo_root() -> Path:
    root = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _overlay_search_dirs() -> list[Path]:
    """
    Directories to look for overlay MP4s, in order:
    1) AUTO_EDIT_ASSETS_OVERLAYS — single explicit path
    2) <repo>/assets/overlays (canonical)
    3) <repo>/overlays — optional flat folder at repo root (same filenames)
    """
    o = os.environ.get("AUTO_EDIT_ASSETS_OVERLAYS")
    if o:
        return [Path(o).expanduser().resolve()]
    r = _repo_root()
    return [r / "assets" / "overlays", r / "overlays"]


def _find_overlay_file(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.is_file():
            return p
    return None


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

    placed = []
    skip_reasons: list[str] = []
    for ov in overlays:
        asset = _find_overlay_file(ov["file"], search_dirs)
        if asset is None:
            msg = (
                f"{ov['file']}: not found in: "
                + ", ".join(str(d) for d in search_dirs)
                + " (see assets/overlays/README.md; or run: auto-edit sync-overlays)"
            )
            print(f"[overlayer] WARNING: {msg}")
            skip_reasons.append(msg)
            continue

        post_cut_start = _remap(float(ov["original_start"]), kept)
        if post_cut_start is None:
            msg = (
                f"{ov['file']}: timestamp {ov['original_start']}s was removed by cuts "
                "(pick a moment that survives in reviewed_plan kept_segments)"
            )
            print(f"[overlayer] WARNING: {msg}")
            skip_reasons.append(msg)
            continue

        duration = _get_duration(asset)
        placed.append({"asset": asset, "start": post_cut_start, "end": post_cut_start + duration})
        print(f"[overlayer] '{ov['file']}' -> post-cut {post_cut_start:.2f}s-{post_cut_start + duration:.2f}s")

    if skip_reasons:
        print(
            "[overlayer] WARNING: some overlays could not be applied:\n"
            + "\n".join(f"  - {r}" for r in skip_reasons)
            + f"\n  Searched: {', '.join(str(d) for d in search_dirs)}"
        )

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
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def _video_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    w, h = result.stdout.strip().split("x", 1)
    return int(w), int(h)


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
    filter_parts: list[str] = []
    prev = "0:v"
    for i, p in enumerate(placed):
        idx = asset_index[p["asset"]]
        out_label = "outv" if i == len(placed) - 1 else f"ovchain{i}"
        enable = f"between(t,{p['start']:.3f},{p['end']:.3f})"
        filter_parts.append(
            f"[{idx}:v]scale=w={vw}:h={vh}:force_original_aspect_ratio=decrease,"
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
    cmd += [
        "-c:v", codec, *codec_flags,
        str(output),
    ]

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
