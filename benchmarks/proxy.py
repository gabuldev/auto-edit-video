"""Proxy transcode for the benchmark.

Two reasons a benchmark run may not use the camera master:

1. The Gemini Files API caps uploads at 2 GiB. A 12-minute 4K HEVC clip off a
   DJI is ~5.5 GB, so the Gemini arm literally cannot see it.
2. Re-encoding 4K 10-bit HEVC on a laptop CPU takes longer than the experiment
   is worth, and both arms would pay it.

So both arms run on the same 1080p H.264 proxy. What we are comparing is where
each planner decides to cut, and that decision does not change because the
pixels are smaller — but the report must say it happened, so nobody reads the
numbers as if they came from the master.

Hardware encode (Intel QuickSync / NVENC / AMF) is used when available; the
libx264 fallback is correct, just slower.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Gemini Files API limit per file.
UPLOAD_CAP_BYTES = 2 * 1024**3

FFMPEG = os.environ.get("AUTO_EDIT_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("AUTO_EDIT_FFPROBE", "ffprobe")


def needs_proxy(video: Path, cap: int = UPLOAD_CAP_BYTES) -> bool:
    return video.stat().st_size > cap


def probe(video: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _lists(kind: str) -> str:
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", f"-{kind}"], capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout


def _has_encoder(name: str) -> bool:
    return f" {name} " in _lists("encoders")


def _has_decoder(name: str) -> bool:
    return f" {name} " in _lists("decoders")


def _codec_of(info: dict) -> str | None:
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            return stream.get("codec_name")
    return None


def build_proxy(
    video: Path,
    out: Path | None = None,
    *,
    height: int = 1080,
    quality: int = 24,
    overwrite: bool = False,
) -> Path:
    """Write (or reuse) a 1080p H.264 proxy next to the source."""
    out = out or video.parent / "proxy" / f"{video.stem}_proxy{height}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        print(f"[proxy] reaproveitando {out.name} ({out.stat().st_size / 1e6:.0f} MB)")
        return out

    info = probe(video)
    source_codec = _codec_of(info)

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-stats", "-y"]
    scale = f"scale=-2:{height}"
    encoder = "libx264"
    encode_opts = ["-preset", "veryfast", "-crf", str(quality)]

    if _has_encoder("h264_qsv"):
        encoder = "h264_qsv"
        encode_opts = ["-global_quality", str(quality), "-look_ahead", "0"]
        # Decode on the GPU too when the source codec has a QSV decoder, and
        # keep the frames there for the scaler — that is where the speedup is.
        if source_codec and _has_decoder(f"{source_codec}_qsv"):
            cmd += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv", "-c:v", f"{source_codec}_qsv"]
            scale = f"scale_qsv=w=-1:h={height}:format=nv12"
    elif _has_encoder("h264_nvenc"):
        encoder = "h264_nvenc"
        encode_opts = ["-cq", str(quality), "-preset", "p4"]

    cmd += [
        "-i", str(video),
        "-vf", scale,
        "-c:v", encoder, *encode_opts,
        "-map", "0:v:0", "-map", "0:a:0",
        # Camera masters carry timecode and telemetry tracks that only confuse
        # the downstream ffprobe/mapping. The proxy is video + audio, nothing else.
        "-dn", "-sn", "-write_tmcd", "0",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]
    print(f"[proxy] {video.name} → {out.name} ({encoder}, {height}p)")
    result = subprocess.run(cmd)
    if result.returncode != 0 or not out.exists():
        raise SystemExit(f"proxy falhou (rc={result.returncode})")
    print(f"[proxy] pronto: {out.stat().st_size / 1e6:.0f} MB")
    return out


def describe(video: Path) -> str:
    """One line for the report: resolution, codec, bitrate, size."""
    info = probe(video)
    fmt = info.get("format", {})
    size = int(fmt.get("size", 0)) / 1e9
    bitrate = int(fmt.get("bit_rate", 0)) / 1e6
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            return (
                f"{stream.get('width')}x{stream.get('height')} {stream.get('codec_name')} "
                f"{stream.get('pix_fmt')}, {bitrate:.1f} Mbps, {size:.2f} GB"
            )
    return f"{bitrate:.1f} Mbps, {size:.2f} GB"
