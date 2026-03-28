"""
CAPTIONER stage — Fase 3
Runs Whisper on edited_video.mp4, generates CapCut-style ASS captions, burns them.
Also writes post_cut_transcription.json (used by evaluator agent).
Only runs for type=short pipelines.

Usage: python tools/captioner.py <workspace_dir>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    import whisper
except ImportError:
    print("ERROR: openai-whisper not installed. Run: uv pip install openai-whisper", file=sys.stderr)
    sys.exit(1)

try:
    import pysubs2
except ImportError:
    print("ERROR: pysubs2 not installed. Run: uv pip install pysubs2", file=sys.stderr)
    sys.exit(1)

MAX_WORDS_PER_LINE = 4      # max words shown simultaneously (CapCut style)
MAX_GAP_FOR_GROUP = 0.6     # seconds — gap larger than this starts a new group
WORD_CONFIDENCE_THRESHOLD = 0.3
NO_SPEECH_PROB_THRESHOLD = 0.8

# ── Default caption style ─────────────────────────────────────────────────────
# Colors in ASS format: &HBBGGRR& (blue-green-red, reversed from RGB)
# Override via pipeline.json["caption_style"] or CLI --highlight-* flags

DEFAULTS = {
    "color_highlight": "&H0045FF&",  # orange  (#FF4500 in RGB)
    "color_text":      "&HFFFFFF&",  # white
    "color_outline":   "&H000000&",  # black
    "border_normal":   1.5,
    "border_highlight": 2.5,         # was 5.0 — reduced to avoid grotesque look
    "blur_highlight":   0.8,         # was 2.0 — softer
    "font_name":       "Montserrat",
    "font_size":       14,
    "font_bold":       True,
    "margin_v":        95,           # distance from bottom (pixels)
}


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


def _build_kept_intervals(reviewed_plan: dict, duration: float) -> list[tuple[float, float]]:
    """Build (start, end) kept intervals from reviewed_plan, inverting cuts if needed."""
    segs = reviewed_plan.get("kept_segments", [])
    if segs:
        return [(float(s["start"]), float(s["end"])) for s in segs]
    # Invert cuts to find kept intervals
    cuts = sorted(reviewed_plan.get("cuts", []), key=lambda c: c["start"])
    intervals: list[tuple[float, float]] = []
    prev = 0.0
    for cut in cuts:
        s = float(cut["start"])
        if s > prev:
            intervals.append((prev, s))
        prev = float(cut["end"])
    if prev < duration:
        intervals.append((prev, duration))
    return intervals


def _remap_words(
    words: list[dict],
    segments: list[dict],
    kept: list[tuple[float, float]],
) -> tuple[list[dict], list[dict]]:
    """
    Remap word and segment timestamps from original video to post-cut timeline.
    Words/segments that fall in cut regions are dropped.
    """
    remapped_words = []
    for word in words:
        try:
            new_start = _remap(float(word["start"]), kept)
            new_end = _remap(float(word["end"]), kept)
        except (KeyError, TypeError, ValueError):
            continue
        if new_start is None or new_end is None:
            continue
        remapped_words.append({**word, "start": new_start, "end": new_end})

    remapped_segs = []
    for seg in segments:
        try:
            new_start = _remap(float(seg["start"]), kept)
            new_end = _remap(float(seg["end"]), kept)
        except (KeyError, TypeError, ValueError):
            continue
        if new_start is None or new_end is None:
            continue
        remapped_segs.append({**seg, "start": new_start, "end": new_end})

    return remapped_words, remapped_segs


def caption(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    if pipeline.get("type") != "short":
        print("[captioner] Skipping — not a short video")
        return

    model_name = pipeline.get("whisper_model", "base")
    language = pipeline.get("language", "pt")

    # Accept overlaid_video.mp4 (post-overlay) or edited_video.mp4 (pre-overlay)
    edited_video = workspace / "overlaid_video.mp4"
    if not edited_video.exists():
        edited_video = workspace / "edited_video.mp4"
    if not edited_video.exists():
        raise FileNotFoundError(f"Neither overlaid_video.mp4 nor edited_video.mp4 found in {workspace}")

    # Merge pipeline caption_style over defaults
    style = {**DEFAULTS, **pipeline.get("caption_style", {})}
    print(f"[captioner] Style: highlight_border={style['border_highlight']}  blur={style['blur_highlight']}  color={style['color_highlight']}")

    post_cut_path = workspace / "post_cut_transcription.json"

    # 1. Build post-cut transcription — use existing file if already present (e.g. manually corrected)
    if post_cut_path.exists():
        print("[captioner] Using existing post_cut_transcription.json (manually corrected or cached).")
        post_cut = json.loads(post_cut_path.read_text())
        words = post_cut.get("words", [])
        segments = post_cut.get("segments", [])
    else:
        try:
            reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
            original_transcription = json.loads((workspace / "transcription.json").read_text())
            duration = _get_duration(edited_video)
            kept = _build_kept_intervals(reviewed_plan, duration)

            orig_words = original_transcription.get("words", [])
            orig_segments = original_transcription.get("segments", [])
            words, segments = _remap_words(orig_words, orig_segments, kept)

            post_cut = {
                "duration": duration,
                "words": words,
                "segments": segments,
                "language": original_transcription.get("language", language),
            }
            print(f"[captioner] Remapped {len(words)} words from original transcription (no re-transcription).")
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            # Fallback: re-transcribe with Whisper (original behavior)
            print(f"[captioner] Remap failed ({exc}), falling back to Whisper re-transcription (model={model_name})...")
            words, segments = _transcribe(edited_video, model_name, language)
            post_cut = {
                "duration": _get_duration(edited_video),
                "words": words,
                "segments": segments,
                "language": language,
            }

        # Save post-cut transcription for the evaluator agent
        post_cut_path.write_text(
            json.dumps(post_cut, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # 2. Group words into display lines (max 4 words, gap-aware)
    groups = _group_words(words)
    print(f"[captioner] Generated {len(groups)} caption groups")

    # 3. Generate ASS file
    ass_path = workspace / "captions.ass"
    _generate_ass(groups, ass_path, style)
    print(f"[captioner] ASS written → {ass_path}")

    # 4. Generate SRT file
    srt_path = workspace / "captions.srt"
    _generate_srt(groups, srt_path)
    print(f"[captioner] SRT written → {srt_path}")

    # 5. Burn captions into video
    output = workspace / "captioned_video.mp4"
    _burn_captions(edited_video, ass_path, output)
    print(f"[captioner] Done → {output}")


# ── Transcription ─────────────────────────────────────────────────────────────

def _transcribe(video: Path, model_name: str, language: str) -> tuple[list[dict], list[dict]]:
    model = whisper.load_model(model_name)
    result = model.transcribe(
        str(video),
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    words: list[dict] = []
    segments: list[dict] = []

    for seg in result["segments"]:
        if seg.get("no_speech_prob", 0.0) > NO_SPEECH_PROB_THRESHOLD:
            continue
        seg_words: list[dict] = []
        for w in seg.get("words", []):
            if w.get("probability", 1.0) < WORD_CONFIDENCE_THRESHOLD:
                continue
            entry = {
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "confidence": round(w.get("probability", 1.0), 3),
            }
            words.append(entry)
            seg_words.append(entry)
        if seg_words:
            segments.append({
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": seg["text"].strip(),
                "words": seg_words,
            })
    return words, segments


# ── Word grouping ─────────────────────────────────────────────────────────────

def _group_words(words: list[dict]) -> list[list[dict]]:
    """
    Groups words into display chunks of max MAX_WORDS_PER_LINE.
    Starts a new group on large gaps or when max words reached.
    """
    if not words:
        return []

    groups: list[list[dict]] = []
    current: list[dict] = [words[0]]

    for w in words[1:]:
        gap = w["start"] - current[-1]["end"]
        if len(current) >= MAX_WORDS_PER_LINE or gap > MAX_GAP_FOR_GROUP:
            groups.append(current)
            current = [w]
        else:
            current.append(w)

    if current:
        groups.append(current)

    return groups


# ── SRT generation ────────────────────────────────────────────────────────────


def _generate_srt(groups: list[list[dict]], srt_path: Path) -> None:
    """Generate SRT subtitle file from word groups."""
    lines = []
    for i, group in enumerate(groups, 1):
        if not group:
            continue
        start = group[0]["start"]
        end = group[-1]["end"]
        text = " ".join(w["word"] for w in group)

        lines.append(str(i))
        lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        lines.append(text)
        lines.append("")  # blank line separator

    srt_path.write_text("\n".join(lines), encoding="utf-8")


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── ASS generation ────────────────────────────────────────────────────────────

def _generate_ass(groups: list[list[dict]], ass_path: Path, style: dict) -> None:
    subs = pysubs2.SSAFile()

    ass_style = pysubs2.SSAStyle()
    ass_style.fontname = style["font_name"]
    ass_style.fontsize = style["font_size"]
    ass_style.bold = style["font_bold"]
    ass_style.primarycolor = pysubs2.Color(255, 255, 255)
    ass_style.outlinecolor = pysubs2.Color(0, 0, 0)
    ass_style.outline = style["border_normal"]
    ass_style.shadow = 0
    ass_style.alignment = 2     # bottom center
    ass_style.marginv = style["margin_v"]
    subs.styles["Default"] = ass_style

    HIGHLIGHT_TAG = (
        rf"{{\1c{style['color_text']}}}"
        rf"{{\3c{style['color_highlight']}}}"
        rf"{{\bord{style['border_highlight']}}}"
        rf"{{\blur{style['blur_highlight']}}}"
    )
    NORMAL_TAG = (
        rf"{{\1c{style['color_text']}}}"
        rf"{{\3c{style['color_outline']}}}"
        rf"{{\bord{style['border_normal']}}}"
        rf"{{\blur0}}"
    )

    def ms(t: float) -> int:
        return int(t * 1000)

    for group in groups:
        display = [w["word"].strip().upper() for w in group]

        for j, word_obj in enumerate(group):
            w_start = ms(word_obj["start"])
            # Extend to next word start if gap is small, else use word end
            if j < len(group) - 1:
                next_start = ms(group[j + 1]["start"])
                w_end = next_start if (next_start - ms(word_obj["end"])) < 500 else ms(word_obj["end"])
            else:
                w_end = ms(word_obj["end"])

            parts = []
            for k, txt in enumerate(display):
                if k == j:
                    parts.append(f"{HIGHLIGHT_TAG}{txt}{NORMAL_TAG}")
                else:
                    parts.append(txt)

            subs.events.append(
                pysubs2.SSAEvent(
                    start=w_start,
                    end=w_end,
                    text=" ".join(parts),
                    style="Default",
                )
            )

    subs.save(str(ass_path))


# ── Caption burning ───────────────────────────────────────────────────────────

def _get_duration(video: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _burn_captions(video: Path, ass: Path, output: Path) -> None:
    # ASS path must use forward slashes and be absolute
    ass_norm = str(ass.resolve()).replace("\\", "/")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", f"subtitles='{ass_norm}'",
        "-c:a", "copy",
        str(output),
    ]
    print("[captioner] Burning captions...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed during caption burning")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/captioner.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)

    ws = Path(sys.argv[1])
    if not ws.exists():
        print(f"Workspace not found: {ws}", file=sys.stderr)
        sys.exit(1)

    caption(ws)
