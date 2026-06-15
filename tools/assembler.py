"""
ASSEMBLE stage — narrated mode.
Reads clip_map.json + the voice file, concatenates the chosen B-roll cuts
(muted), lays the voice as the single audio track, reframes to target aspect,
and writes edited_video.mp4 with duration covering the voice.

Usage: python tools/assembler.py <workspace_dir>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from executor import _get_video_codec, SHORT_TARGET  # reuse codec choice

LONG_TARGET = (1920, 1080)


def _flatten_clips(clip_map: dict) -> list[dict]:
    flat: list[dict] = []
    for block in clip_map.get("blocks", []):
        for c in block.get("clips", []):
            flat.append(dict(c))
    for i, c in enumerate(flat):
        c["_idx"] = i
    return flat


def _build_video_filter(clips: list[dict], reframe: tuple[int, int] | None) -> str:
    parts, concat_inputs = [], ""
    for c in clips:
        i = c["_idx"]
        parts.append(
            f"[{i}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},"
            f"setpts=PTS-STARTPTS[v{i}]")
        concat_inputs += f"[v{i}]"
    n = len(clips)
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[catv]")
    if reframe:
        tw, th = reframe
        parts.append(
            f"[catv]crop=ih*{tw}/{th}:ih:(iw-ih*{tw}/{th})/2:0,"
            f"scale={tw}:{th}:flags=lanczos[outv]")
    else:
        parts.append("[catv]null[outv]")
    return ";".join(parts)


def _pad_to_cover(flat: list[dict], vo_duration: float) -> list[dict]:
    """Ensure summed cut duration >= voice duration by extending the last cut's
    out point. Prevents -shortest from truncating the voice / a black tail."""
    total = sum(c["out"] - c["in"] for c in flat)
    deficit = vo_duration - total
    if deficit > 0.01 and flat:
        flat[-1]["out"] = round(flat[-1]["out"] + deficit, 3)
    return flat


def assemble(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    clip_map = json.loads((workspace / "clip_map.json").read_text())
    clips_dir = Path(pipeline["clips_dir"])
    voice = Path(pipeline["voice_path"])
    video_type = pipeline.get("type", "narrated")

    flat = _flatten_clips(clip_map)
    if not flat:
        raise RuntimeError("clip_map has no clips")

    vo_duration = float(json.loads((workspace / "vo_alignment.json").read_text())["vo_duration"])
    flat = _pad_to_cover(flat, vo_duration)

    reframe = SHORT_TARGET if video_type != "long" else LONG_TARGET

    inputs: list[str] = []
    for c in flat:
        inputs += ["-i", str(clips_dir / c["file"])]
    voice_idx = len(flat)
    inputs += ["-i", str(voice)]

    vfilter = _build_video_filter(flat, reframe)
    afilter = (f"[{voice_idx}:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
               "aformat=sample_fmts=fltp:channel_layouts=stereo[outa]")
    filter_complex = f"{vfilter};{afilter}"

    codec, codec_flags = _get_video_codec()
    output = workspace / "edited_video.mp4"
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", filter_complex,
           "-map", "[outv]", "-map", "[outa]",
           "-c:v", codec, *codec_flags,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-shortest",
           "-movflags", "+faststart", "-brand", "mp42", str(output)]
    print(f"[assemble] {len(flat)} cuts -> {output.name} (reframe {reframe})")
    if subprocess.run(cmd).returncode != 0:
        raise RuntimeError("FFmpeg failed during assemble")
    print(f"[assemble] Done -> {output}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/assembler.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    assemble(Path(sys.argv[1]))
