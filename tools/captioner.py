"""
CAPTIONER stage — Fase 3
Runs Whisper on edited_video.mp4, generates CapCut-style ASS captions, burns them.
Also writes post_cut_transcription.json (used by evaluator agent).
Only runs for type=short pipelines.

Usage: python tools/captioner.py <workspace_dir>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auto_edit import caption_render, caption_style  # noqa: E402  -- needs repo root on sys.path
from auto_edit.caption_render import (  # noqa: E402,F401  -- re-exported for callers/tests
    _ffmpeg_has_subtitles,
    _known_ffmpeg_locations,
)

try:
    import whisper
except ImportError:
    print("ERROR: openai-whisper not installed. Run: uv pip install openai-whisper", file=sys.stderr)
    sys.exit(1)

MAX_WORDS_PER_LINE = 4      # max words shown simultaneously (CapCut style)
WORD_CONFIDENCE_THRESHOLD = 0.3
NO_SPEECH_PROB_THRESHOLD = 0.8

# Reuse/validation of an existing post_cut_transcription.json
POST_CUT_DURATION_TOLERANCE = 2.0   # seconds of allowed drift vs edited video
POST_CUT_MIN_COVERAGE = 0.5         # last word must reach >= this fraction of video


def _is_existing_post_cut_usable(post_cut: dict, edited_duration: float) -> bool:
    """Decide whether a pre-existing post_cut_transcription.json can be trusted
    for the CURRENT edited video.

    Reused for manual corrections and same-run caches, but must reject stale
    leftovers from a prior run on a reused workspace (different cuts → different
    duration), which would otherwise burn desynced captions onto the new video.
    """
    words = post_cut.get("words") or []
    if not words:
        return False
    pc_duration = post_cut.get("duration")
    if pc_duration is None:
        return False
    # Different cuts produce a different total length.
    if abs(float(pc_duration) - edited_duration) > POST_CUT_DURATION_TOLERANCE:
        return False
    # Captions must span most of the video — a large uncovered tail signals a mismatch.
    try:
        last_end = max(float(w.get("end", 0.0)) for w in words)
    except (TypeError, ValueError):
        return False
    if last_end < POST_CUT_MIN_COVERAGE * edited_duration:
        return False
    return True


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


def _build_kept_intervals(
    reviewed_plan: dict,
    duration: float,
    energy_db: list[float] | None = None,
    resolution: float = 0.0,
) -> list[tuple[float, float]]:
    """Build (start, end) kept intervals from reviewed_plan, inverting cuts if needed.
    Applies the same END_PADDING as executor.py so timestamps match the actual edited video."""
    from auto_edit import snap  # same padding rule as the executor

    end_padding = float(os.environ.get("AUTO_EDIT_END_PADDING", "0.2"))
    threshold = snap.silence_threshold_db(energy_db or [])
    segs = reviewed_plan.get("kept_segments", [])
    if not segs:
        # Invert cuts to find kept intervals
        cuts = sorted(reviewed_plan.get("cuts", []), key=lambda c: c["start"])
        segs = []
        prev = 0.0
        for cut in cuts:
            s = float(cut["start"])
            if s > prev:
                segs.append({"start": prev, "end": s})
            prev = float(cut["end"])
        if prev < duration:
            segs.append({"start": prev, "end": duration})

    # Apply end_padding and clamp, matching executor._build_keep_intervals
    padded: list[tuple[float, float]] = []
    for s in segs:
        start = max(0.0, float(s["start"]))
        raw_end = float(s["end"])
        pad = snap.audible_tail(raw_end, end_padding, energy_db or [], resolution, threshold)
        end = min(duration, raw_end + pad)
        if end > start:
            padded.append((start, end))

    # Merge overlapping intervals (same as executor)
    if not padded:
        return []
    padded.sort()
    merged = [padded[0]]
    for s, e in padded[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


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
        # Remap words within the segment too
        seg_words = []
        for sw in seg.get("words", []):
            try:
                sw_start = _remap(float(sw["start"]), kept)
                sw_end = _remap(float(sw["end"]), kept)
            except (KeyError, TypeError, ValueError):
                continue
            if sw_start is not None and sw_end is not None:
                seg_words.append({**sw, "start": sw_start, "end": sw_end})
        remapped_segs.append({
            **seg,
            "start": new_start,
            "end": new_end,
            "words": seg_words,
            "text": " ".join(w["word"] for w in seg_words),
        })

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
        # finalize deletes edited_video.mp4 to reclaim disk, so `resume --from
        # caption` on an already-finished pipeline lands here. The cut itself has
        # to be rebuilt before captions can be burned onto it.
        raise FileNotFoundError(
            f"Nem overlaid_video.mp4 nem edited_video.mp4 existem em {workspace} — "
            "o stage finalize apaga o vídeo cortado depois que o pipeline termina. "
            "Rode `auto-edit resume <video> --from execute` pra reconstruí-lo."
        )

    # Style tokens + old CLI options + per-video adjust
    style = caption_style.resolve(pipeline)
    print(
        f"[captioner] Style: font={style['font']}  position={style['position']}  "
        f"offset={style['offset']}%  size={style['size']}%  highlight={style['highlight']} ({style['highlight_mode']})"
        + ("  hidden" if style["hidden"] else "")
    )

    post_cut_path = workspace / "post_cut_transcription.json"
    edited_duration = _get_duration(edited_video)

    # 1. Build post-cut transcription.
    #    A pre-existing file is only reused if it actually matches the current
    #    edited video (manual correction / same-run cache). A stale file left
    #    over from a PRIOR run on a reused workspace describes different cuts and
    #    would burn badly-desynced captions — regenerate from the current plan.
    existing_post_cut = None
    if post_cut_path.exists():
        try:
            candidate = json.loads(post_cut_path.read_text())
        except json.JSONDecodeError:
            candidate = None
        if candidate and _is_existing_post_cut_usable(candidate, edited_duration):
            existing_post_cut = candidate

    if existing_post_cut is not None:
        print("[captioner] Reusing existing post_cut_transcription.json (matches edited video).")
        post_cut = existing_post_cut
        words = post_cut.get("words", [])
        segments = post_cut.get("segments", [])
    else:
        if post_cut_path.exists():
            print(
                "[captioner] Ignoring stale/inconsistent post_cut_transcription.json "
                f"(does not match edited video duration {edited_duration:.1f}s) — regenerating."
            )
        try:
            reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
            original_transcription = json.loads((workspace / "transcription.json").read_text())
            # Use original video duration for building kept intervals
            # (kept_segments timestamps are in the original timeline, not the edited one)
            original_duration = original_transcription.get("duration", _get_duration(edited_video))
            from auto_edit import snap as _snap
            energy_db, energy_resolution = _snap.load_energy_map(workspace)
            kept = _build_kept_intervals(
                reviewed_plan, original_duration, energy_db, energy_resolution
            )

            orig_words = original_transcription.get("words", [])
            orig_segments = original_transcription.get("segments", [])

            # Must mirror executor's leading-silence snap so caption timestamps
            # stay aligned with the actually-cut video.
            from executor import snap_start_to_audio_onset
            source_video = Path(pipeline["video_path"])
            kept = snap_start_to_audio_onset(kept, source_video)

            words, segments = _remap_words(orig_words, orig_segments, kept)

            post_cut = {
                "duration": edited_duration,
                "words": words,
                "segments": segments,
                "language": original_transcription.get("language", language),
            }
            print(f"[captioner] Remapped {len(words)} words from original transcription (no re-transcription).")
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            # Fallback: re-transcribe with Whisper. Note: Whisper run on a cut +
            # concatenated video tends to drift across cut boundaries, so this is
            # a last resort — the remap path above is preferred whenever possible.
            print(f"[captioner] Remap failed ({exc}), falling back to Whisper re-transcription (model={model_name})...")
            context = pipeline.get("context", "")
            words, segments = _transcribe(edited_video, model_name, language, context)
            post_cut = {
                "duration": edited_duration,
                "words": words,
                "segments": segments,
                "language": language,
            }

        # Save post-cut transcription for the evaluator agent
        post_cut_path.write_text(
            json.dumps(post_cut, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Sanity check: captions should cover most of the video. A large uncovered
    # tail almost always means a timeline mismatch (the desync we guard against).
    if words:
        last_end = max(float(w.get("end", 0.0)) for w in words)
        if last_end < POST_CUT_MIN_COVERAGE * edited_duration:
            print(
                f"[captioner] WARNING: captions end at {last_end:.1f}s but video is "
                f"{edited_duration:.1f}s — last {edited_duration - last_end:.1f}s uncaptioned. "
                "Possible timeline mismatch."
            )

    # 2. Group words into display lines (style["words"] max, gap-aware)
    groups = caption_render.group_words(words, style["words"])
    print(f"[captioner] Generated {len(groups)} caption groups")

    # 3. Generate ASS file, in video pixels
    ass_path = workspace / "captions.ass"
    width, height = caption_render.video_size(edited_video)
    _generate_ass(groups, ass_path, style, width, height)
    print(f"[captioner] ASS written → {ass_path}")

    # 4. Generate SRT file
    srt_path = workspace / "captions.srt"
    _generate_srt(groups, srt_path)
    print(f"[captioner] SRT written → {srt_path}")

    # 5. Burn captions into video (hidden: the cut goes out as is)
    output = workspace / "captioned_video.mp4"
    if style["hidden"]:
        shutil.copyfile(edited_video, output)
        print(f"[captioner] Captions hidden for this video — copied without burning → {output}")
        return
    _burn_captions(edited_video, ass_path, output, style["font"])
    print(f"[captioner] Done → {output}")


# ── Transcription ─────────────────────────────────────────────────────────────

def _transcribe(video: Path, model_name: str, language: str, context: str = "") -> tuple[list[dict], list[dict]]:
    model = whisper.load_model(model_name)
    transcribe_kwargs: dict = dict(
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    if context:
        transcribe_kwargs["initial_prompt"] = f"Termos relevantes: {context}."
        print(f"[captioner] Using initial_prompt from context ({len(context)} chars)")
    result = model.transcribe(str(video), **transcribe_kwargs)
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
    """Groups words into display chunks of max MAX_WORDS_PER_LINE (gap-aware)."""
    return caption_render.group_words(words, MAX_WORDS_PER_LINE)


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

def _generate_ass(groups: list[list[dict]], ass_path: Path, style: dict, width: int, height: int) -> None:
    caption_render.build_ass(groups, style, width, height).save(str(ass_path))


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


def _resolve_caption_ffmpeg() -> str:
    return caption_render.resolve_ffmpeg()


def _burn_captions(video: Path, ass: Path, output: Path, font: str) -> None:
    # cwd = the ASS folder, so the filter only sees relative names
    folder = ass.parent
    ffmpeg = _resolve_caption_ffmpeg()  # before the fonts copy: nothing to clean if it raises
    fonts = caption_render.prepare_fonts(font, folder)
    try:
        cmd = caption_render.burn_command(ffmpeg, video, ass.name, str(fonts), output)
        print("[captioner] Burning captions...")
        result = subprocess.run(cmd, cwd=folder)
    finally:
        shutil.rmtree(folder / fonts, ignore_errors=True)
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
