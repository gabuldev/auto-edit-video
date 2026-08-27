"""ffprobe helpers shared by the CLI and the stage tools.

Always ask ffprobe for JSON. The CSV writer emits one field per *entry* it
found, and a stream carrying side data (DJI cameras attach it to some clips,
but not all) contributes an extra empty field — so `csv=p=0:s=x` returns
`3840x2160x` instead of `3840x2160`, and every naive split/unpack blows up:

    ValueError: invalid literal for int() with base 10: ''

The failure is per-file, so a folder of clips from the same camera can merge
fine for months and then crash on the one clip that happens to carry it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class ProbeError(RuntimeError):
    """ffprobe failed, or returned nothing usable."""


def _run_probe(path: Path | str, select: str, entries: str) -> str:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", select,
        "-show_entries", entries,
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProbeError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    return result.stdout


def parse_streams(payload: str) -> list[dict]:
    """Streams from an ffprobe JSON payload; [] if the payload is unusable."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return []
    streams = data.get("streams")
    return streams if isinstance(streams, list) else []


def parse_size(payload: str) -> tuple[int, int]:
    """(width, height) of the first stream in an ffprobe JSON payload."""
    for stream in parse_streams(payload):
        width, height = stream.get("width"), stream.get("height")
        if width and height:
            return int(width), int(height)
    raise ProbeError("no video stream with width/height in ffprobe output")


def parse_fps(payload: str) -> str | None:
    """Nominal frame rate as the "30000/1001" fraction, or None if unknown."""
    for stream in parse_streams(payload):
        value = stream.get("r_frame_rate")
        if value and value not in ("0/0", "N/A"):
            return str(value)
    return None


def parse_timescale(payload: str) -> int | None:
    """Track timescale (the `time_base` denominator), or None if unknown."""
    for stream in parse_streams(payload):
        value = stream.get("time_base")
        if not value or "/" not in str(value):
            continue
        _, _, denominator = str(value).partition("/")
        try:
            ticks = int(denominator)
        except ValueError:
            continue
        if ticks > 0:
            return ticks
    return None


def video_size(path: Path | str) -> tuple[int, int]:
    """(width, height) of the first video stream."""
    return parse_size(_run_probe(path, "v:0", "stream=width,height"))


def video_fps(path: Path | str) -> str | None:
    """Frame rate of the first video stream, as a fraction string."""
    try:
        return parse_fps(_run_probe(path, "v:0", "stream=r_frame_rate"))
    except ProbeError:
        return None


def video_timescale(path: Path | str) -> int | None:
    """Track timescale of the first video stream, e.g. 90000."""
    try:
        return parse_timescale(_run_probe(path, "v:0", "stream=time_base"))
    except ProbeError:
        return None


def video_specs(path: Path | str) -> tuple[int, int, str | None]:
    """(width, height, fps) of the first video stream, in one ffprobe call."""
    payload = _run_probe(path, "v:0", "stream=width,height,r_frame_rate")
    width, height = parse_size(payload)
    return width, height, parse_fps(payload)


def has_audio_stream(path: Path | str) -> bool:
    """Whether the file carries at least one audio stream."""
    try:
        return bool(parse_streams(_run_probe(path, "a:0", "stream=index")))
    except ProbeError:
        return False
