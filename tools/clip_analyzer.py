"""
ANALYZE-CLIPS stage — narrated mode.
Samples frames from each B-roll clip and asks a vision model to describe its
content. Result cached in clip_index.json (skips already-indexed clips).

Usage: python tools/clip_analyzer.py <workspace_dir>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
FRAMES_PER_CLIP = 4


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def _frame_timestamps(duration: float, n: int = FRAMES_PER_CLIP) -> list[float]:
    """Evenly spaced sample points strictly inside (0, duration)."""
    if duration <= 0:
        return [0.0]
    step = duration / (n + 1)
    return [round(step * (i + 1), 3) for i in range(n)]


def _get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _extract_frame(video: Path, ts: float, out_png: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "3", str(out_png)],
        capture_output=True, check=True)


def _describe_with_gemini(frames: list[Path], context: str) -> dict:
    """Returns {'desc': str, 'tags': [str]} using Gemini Vision."""
    import google.generativeai as genai  # lazy import
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")
    imgs = [{"mime_type": "image/png", "data": p.read_bytes()} for p in frames]
    prompt = (
        f"Estes são frames de UM clip de B-roll. Contexto do vídeo: {context}. "
        "Descreva em uma frase curta o que aparece, e liste 3-6 tags. "
        'Responda só JSON: {"desc": "...", "tags": ["..."]}'
    )
    resp = model.generate_content([prompt, *imgs])
    text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def analyze(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    clips_dir = Path(pipeline["clips_dir"])
    context = pipeline.get("context", "")
    index_path = workspace / "clip_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}

    clips = sorted(p for p in clips_dir.iterdir() if _is_video(p))
    for clip in clips:
        if clip.name in index:
            continue
        duration = _get_duration(clip)
        with tempfile.TemporaryDirectory() as td:
            frames = []
            for i, ts in enumerate(_frame_timestamps(duration)):
                fp = Path(td) / f"f{i}.png"
                _extract_frame(clip, ts, fp)
                frames.append(fp)
            described = _describe_with_gemini(frames, context)
        index[clip.name] = {"duration": round(duration, 3), **described}
        print(f"[analyze-clips] {clip.name}: {described['desc']}")
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"[analyze-clips] Indexed {len(index)} clips")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/clip_analyzer.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    analyze(Path(sys.argv[1]))
