"""
Minimal overlay check: generates a short base clip + green-screen overlay asset,
then runs the same FFmpeg chroma+overlay chain as tools/overlayer.py.

Does not read workspace JSON or remap cuts — isolates FFmpeg + asset layout.

Usage (from repo root):
  python tools/overlay_smoke_test.py
  python tools/overlay_smoke_test.py -o /tmp/overlay_smoke
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_import_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _run_ffmpeg(cmd: list[str], label: str) -> None:
    print(f"[smoke] {label}: {' '.join(cmd[:4])} …")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"[smoke] FFmpeg failed: {label}")


def run_smoke(out_dir: Path) -> Path:
    for bin_name in ("ffmpeg", "ffprobe"):
        if shutil.which(bin_name) is None:
            raise RuntimeError(
                f"{bin_name} not found on PATH — install FFmpeg or add it to PATH "
                "(smoke test and overlayer both need it)."
            )

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = out_dir / "_smoke_base.mp4"
    asset = out_dir / "_smoke_green_overlay.mp4"
    merged = out_dir / "smoke_overlaid.mp4"

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=0x1a1a2e:s=640x360:r=30",
            "-t", "8",
            "-pix_fmt", "yuv420p",
            str(base),
        ],
        "synthetic base video",
    )

    # Green #00FF00 full frame + opaque white box (visible after chromakey)
    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=0x00FF00:s=320x240:r=30",
            "-t", "3",
            "-vf", "drawbox=x=40:y=40:w=240:h=160:color=white:t=fill",
            "-pix_fmt", "yuv420p",
            str(asset),
        ],
        "synthetic green-screen overlay",
    )

    _ensure_import_path()
    from tools.overlayer import _get_duration, _run_ffmpeg_overlay

    d = _get_duration(asset)
    placed = [{"asset": asset, "start": 2.0, "end": 2.0 + d}]
    _run_ffmpeg_overlay(base, placed, merged)

    print(f"[smoke] OK — open: {merged}")
    print(
        "[smoke] You should see a white rectangle on the dark background "
        "between ~2s and the end of the overlay (chromakey + overlay path works)."
    )
    return merged


def main() -> int:
    p = argparse.ArgumentParser(description="Smoke-test overlay FFmpeg pipeline")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=REPO_ROOT / "output" / "overlay_smoke",
        help="Output directory (default: output/overlay_smoke under repo)",
    )
    args = p.parse_args()
    try:
        run_smoke(args.out)
    except Exception as e:
        print(f"[smoke] ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
