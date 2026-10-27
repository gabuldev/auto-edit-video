"""
OVERLAYER stage
Reads overlay_plan.json and draws each overlay on the edited video:
- the person's own MP4 (green screen, chroma key) when they have one;
- otherwise the animated React overlay (`auto-edit-render overlay`), drawn
  at the video's resolution, only in the overlay's box.
Input:  workspace/edited_video.mp4
Output: workspace/overlaid_video.mp4 (or skips if no overlays planned)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auto_edit import overlay_assets, probe, render, styles  # noqa: E402  -- needs repo root on sys.path


def _overlay_search_dirs() -> list[Path]:
    """Folders to look for overlay MP4s (see overlay_assets.overlay_search_dirs).

    1) AUTO_EDIT_ASSETS_OVERLAYS — single explicit path
    2) <repo>/assets/overlays (canonical)
    3) <repo>/overlays — optional flat folder at repo root (same filenames)
    """
    return overlay_assets.overlay_search_dirs()


# Overlay kind → the person's own MP4 for it (green screen), if they have one.
KIND_FILES = {"lower_third": "lowerthid_gabul.mp4", "cta": "ctas.mp4"}
SOURCES = ("auto", "react", "mp4")


def _kind(ov: dict) -> str | None:
    """`overlay` from the plan, or the kind an older plan's `file` stands for."""
    kind = ov.get("overlay")
    if kind in KIND_FILES:
        return kind
    return {f: k for k, f in KIND_FILES.items()}.get(ov.get("file"))


def _source() -> str:
    """AUTO_EDIT_OVERLAY_SOURCE: `auto` (own MP4 if there is one, else React),
    `react` (always React) or `mp4` (only MP4s, the old behaviour)."""
    value = os.environ.get("AUTO_EDIT_OVERLAY_SOURCE", "").strip().lower()
    return value if value in SOURCES else "auto"


def _find_overlay_file(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.is_file():
            return p
    return None


def _overlays_strict() -> bool:
    """Whether a missing overlay asset should fail the stage instead of warning.

    Default: no. Overlay .mp4s are per-person assets that live outside the repo
    (``assets/`` is not versioned), so a fresh install legitimately has none.
    A planned overlay whose file can't be found is skipped with a warning and
    the edit still ships — losing an overlay is not worth throwing away the
    whole render. Set AUTO_EDIT_OVERLAYS_STRICT=1 to fail instead, e.g. in CI
    where a missing asset means the setup is wrong.
    """
    return os.environ.get("AUTO_EDIT_OVERLAYS_STRICT", "").lower() in ("1", "true", "yes")


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
        "    export AUTO_EDIT_ASSETS_OVERLAYS=/path/to/your/overlays"
    )


def _post_cut_start(ov: dict, kept: "list[tuple[float, float]] | None") -> float | None:
    """Where the overlay starts on the edit. `start` is already on it (the
    agent read the post-cut transcript); an older plan's `original_start` is
    remapped through the kept segments. None → removed by the cuts."""
    if ov.get("start") is not None:
        try:
            start = float(ov["start"])
        except (TypeError, ValueError):
            return None
        return start if start >= 0 else None
    if ov.get("original_start") is None or kept is None:
        return None
    return _remap(float(ov["original_start"]), kept)


def _resolve_overlays(
    overlays: list[dict],
    search_dirs: list[Path],
    kept: "list[tuple[float, float]] | None",
    source: str = "auto",
) -> tuple[list[tuple[dict, str | None, Path | None, float]], list[str], list[str]]:
    """Split planned overlays into (found, missing, removed_by_cut).

    - found: ``(overlay, kind, asset, post_cut_start)``; ``asset`` None means
      draw it with React.
    - missing: overlays with no MP4 where React can't stand in (a custom
      `file`, or AUTO_EDIT_OVERLAY_SOURCE=mp4).
    - removed_by_cut: overlays whose moment isn't in the edit.
    """
    found: list[tuple[dict, str | None, Path | None, float]] = []
    missing: list[str] = []
    removed: list[str] = []
    for ov in overlays:
        kind = _kind(ov)
        name = ov.get("file") or KIND_FILES.get(kind or "") or str(ov.get("overlay"))
        asset = None if source == "react" or name is None else _find_overlay_file(name, search_dirs)
        if asset is None and (kind is None or source == "mp4"):
            missing.append(name)
            continue
        post_cut_start = _post_cut_start(ov, kept)
        if post_cut_start is None:
            removed.append(name)
            continue
        found.append((ov, kind, asset, post_cut_start))
    return found, missing, removed


# Últimos segundos do vídeo: é onde o YouTube põe a tela final (próximo vídeo
# + inscrever-se). Overlay ali briga com ela — o CTA de inscrição duplica o
# botão. Só vale pra vídeo com tamanho pra ter tela final (>= 25s).
END_SCREEN_SEC = 20.0
END_SCREEN_MIN_VIDEO = 25.0


def _outside_end_screen(found: list, duration: float) -> tuple[list, list]:
    """Split resolved overlays into (kept, dropped): dropped start inside
    the end-screen zone."""
    if duration < END_SCREEN_MIN_VIDEO:
        return found, []
    zone = duration - END_SCREEN_SEC
    kept = [f for f in found if f[3] < zone]
    dropped = [f for f in found if f[3] >= zone]
    return kept, dropped


def _check_assets_present(missing: list[str], search_dirs: list[Path]) -> None:
    """Warn about missing overlay assets — or raise, under AUTO_EDIT_OVERLAYS_STRICT."""
    if not missing:
        return
    msg = _missing_assets_message(missing, search_dirs)
    if _overlays_strict():
        raise FileNotFoundError(msg)
    print(f"[overlayer] WARNING: {msg}")
    print("[overlayer] Rendering without them. Set AUTO_EDIT_OVERLAYS_STRICT=1 to fail instead.")


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

    source = _source()
    search_dirs = _overlay_search_dirs()
    print(f"[overlayer] Overlay search dirs: {', '.join(str(d) for d in search_dirs)} (source: {source})")

    kept = None
    if any(ov.get("start") is None for ov in overlays):  # an older plan, on the original timeline
        pipeline = json.loads((workspace / "pipeline.json").read_text())
        reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
        kept = _build_kept_intervals(reviewed_plan, pipeline)

    found, missing, removed = _resolve_overlays(overlays, search_dirs, kept, source)

    for name in removed:
        print(
            f"[overlayer] WARNING: {name}: its moment is not in the edit — overlay "
            "skipped (pick a moment inside a kept segment)."
        )

    input_video = workspace / "edited_video.mp4"
    output_video = workspace / "overlaid_video.mp4"
    found, in_end_screen = _outside_end_screen(found, _get_duration(input_video))
    for ov, kind, _asset, start in in_end_screen:
        print(
            f"[overlayer] '{ov.get('file') or kind}' at {start:.2f}s skipped: last "
            f"{END_SCREEN_SEC:.0f}s are the YouTube end screen."
        )
    with tempfile.TemporaryDirectory(prefix="auto-edit-overlay-") as tmp:
        rendered: dict[str, dict | None] = {}
        placed = []
        for ov, kind, asset, post_cut_start in found:
            label = ov.get("file") or kind
            if asset is not None:
                duration = _get_duration(asset)
                placed.append({"asset": asset, "start": post_cut_start, "end": post_cut_start + duration})
            else:
                if kind not in rendered:  # every CTA is the same animation: draw it once
                    rendered[kind] = _render_react(kind, input_video, Path(tmp) / kind)
                r = rendered[kind]
                if r is None:
                    missing.append(label)
                    continue
                duration = r["duration"]
                placed.append({
                    "frames": r["frames_file"], "x": r["x"], "y": r["y"],
                    "start": post_cut_start, "end": post_cut_start + duration,
                })
            via = "MP4" if asset is not None else "React"
            print(f"[overlayer] '{label}' ({via}) -> {post_cut_start:.2f}s-{post_cut_start + duration:.2f}s")

        # A missing overlay is a setup problem, but not a fatal one: warn and
        # render without it (AUTO_EDIT_OVERLAYS_STRICT=1 makes it fail).
        _check_assets_present(missing, search_dirs)

        if placed:
            _run_ffmpeg_overlay(input_video, placed, output_video)
        else:
            import shutil
            shutil.copy2(input_video, output_video)
            print("[overlayer] No overlays applied — copied edited video as-is")
    print(f"[overlayer] Done -> {output_video}")


def _fps_number(fps: str | None) -> float:
    try:
        return float(Fraction(fps)) if fps else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _render_react(kind: str, video: Path, out_dir: Path) -> dict | None:
    """Draw one overlay animation with the React renderer, at the video's
    resolution. None (and why) when it can't."""
    cmd = render.command()
    if cmd is None:
        print(f"[overlayer] {kind}: no renderer (auto-edit-render) to draw it")
        return None
    brand = render.brand()
    if kind == "lower_third" and not brand["name"]:
        print("[overlayer] lower_third: no name to show — set it in Settings (Marca) or connect YouTube")
        return None
    style = styles.active()
    try:
        fonts = styles.overlay_fonts(style["tokens"])
    except styles.StyleError as exc:
        print(f"[overlayer] {kind}: {exc}")
        return None
    vw, vh = _video_size(video)
    spec = {
        "kind": kind, "video_width": vw, "video_height": vh, "fps": _fps_number(_video_fps(video)),
        "style": style["tokens"], "brand": brand, "fonts": fonts,
    }
    print(f"[overlayer] {kind}: style '{style['name']}'")
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_file = out_dir / "spec.json"
    spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    try:
        res = subprocess.run([*cmd, "overlay", str(spec_file), str(out_dir)],
                             capture_output=True, text=True, timeout=render.TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[overlayer] {kind}: renderer failed ({exc})")
        return None
    frames_file = out_dir / "frames.txt"
    if res.returncode != 0 or not frames_file.is_file():
        print(f"[overlayer] {kind}: renderer failed: {(res.stderr or res.stdout).strip()[-300:]}")
        return None
    try:
        result = json.loads((out_dir / "overlay.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[overlayer] {kind}: renderer gave no placement ({exc})")
        return None
    return {**result, "frames_file": frames_file}


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
    """Composite every placed overlay. Each is its own input, shifted to its
    start (setpts) — without the shift the overlay's own clock starts at 0, so
    anything placed past its length only ever showed its last (empty) frame.

    - ``{"asset", "start", "end"}``: a green-screen MP4, scaled to the frame
      and chroma-keyed.
    - ``{"frames", "x", "y", "start", "end"}``: React frames (an ffmpeg concat
      list of transparent PNGs), placed at x, y.
    """
    input_args = ["-i", str(video)]
    for p in placed:
        if "frames" in p:
            input_args += ["-f", "concat", "-safe", "0", "-i", str(p["frames"])]
        else:
            input_args += ["-i", str(p["asset"])]

    vw, vh = _video_size(video)
    print(f"[overlayer] Main video {vw}x{vh}")

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
        idx = i + 1
        out_label = "outv" if i == len(placed) - 1 else f"ovchain{i}"
        shift = f"setpts=PTS-STARTPTS+{p['start']:.3f}/TB"
        enable = f"between(t,{p['start']:.3f},{p['end']:.3f})"
        if "frames" in p:
            filter_parts.append(f"[{idx}:v]format=rgba,{shift}[ck{i}]")
            pos = f"x={p['x']}:y={p['y']}"
        else:
            # Scale to the main frame first (letterbox pad): plain overlay=0:0
            # hides a 1080p asset in a corner of a 4K edit.
            filter_parts.append(
                f"[{idx}:v]" + (f"fps={fps}," if fps else "")
                + f"scale=w={vw}:h={vh}:force_original_aspect_ratio=decrease,"
                f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2,setsar=1[ov_s{i}]"
            )
            filter_parts.append(
                f"[ov_s{i}]chromakey=color={CHROMA_COLOR}:similarity={CHROMA_SIMILARITY}:blend={CHROMA_BLEND},{shift}[ck{i}]"
            )
            pos = "x=0:y=0"
        filter_parts.append(
            f"[{prev}][ck{i}]overlay={pos}:eof_action=pass:enable='{enable}'[{out_label}]"
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
    cmd += ["-c:v", codec, *codec_flags, "-pix_fmt", "yuv420p"]  # 8-bit: see executor.PIX_FMT
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
