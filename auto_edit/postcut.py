"""Build the transcript of the *edited* video.

The evaluate stage is supposed to judge the finished cut. Without this file it
silently falls back to the original transcript (auto_edit/runner.py), so it
grades the raw footage — approving edits it never saw and returning feedback
with timestamps that do not exist in the output.

Rather than paying for a second Whisper pass, the post-cut transcript is
derived: every word kept by the executor is remapped onto the final timeline.
Text and timing are then exact for anything the evaluator can reason about.

Run as: python -m auto_edit.postcut <workspace>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EPS = 0.001


def load_intervals(workspace: Path, duration: float) -> list[tuple[float, float]]:
    """The intervals FFmpeg actually kept, or the planned ones as a fallback."""
    applied = workspace / "applied_intervals.json"
    if applied.exists():
        data = json.loads(applied.read_text(encoding="utf-8"))
        return [
            (float(i["start"]), float(i["end"]))
            for i in data.get("intervals", [])
            if float(i["end"]) > float(i["start"])
        ]

    # Older workspaces (executed before applied_intervals.json existed): rebuild
    # from the plan, mirroring the executor's end-padding.
    plan_file = workspace / "reviewed_plan.json"
    if not plan_file.exists():
        return []
    padding = float(os.environ.get("AUTO_EDIT_END_PADDING", "0.2"))
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    intervals = []
    for seg in plan.get("kept_segments") or []:
        try:
            start, end = float(seg["start"]), min(duration, float(seg["end"]) + padding)
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            intervals.append((start, end))
    return sorted(intervals)


def remap(transcription: dict, intervals: list[tuple[float, float]]) -> dict:
    """Project words and segments of the source onto the edited timeline."""
    offsets: list[tuple[float, float, float]] = []  # (start, end, shift)
    elapsed = 0.0
    for start, end in intervals:
        offsets.append((start, end, elapsed - start))
        elapsed += end - start

    def project(t: float) -> float | None:
        for start, end, shift in offsets:
            if start - EPS <= t <= end + EPS:
                return round(t + shift, 3)
        return None

    words = []
    for w in transcription.get("words") or []:
        try:
            start, end = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # A word survives only if both edges landed in the same kept interval.
        new_start, new_end = project(start), project(end)
        if new_start is None or new_end is None or new_end < new_start:
            continue
        words.append({**w, "start": new_start, "end": new_end})

    segments = []
    for seg in transcription.get("segments") or []:
        try:
            seg_start, seg_end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        inside = [
            (max(seg_start, s), min(seg_end, e)) for s, e in intervals if min(seg_end, e) > max(seg_start, s)
        ]
        if not inside:
            continue
        kept_span = sum(e - s for s, e in inside)
        new_start, new_end = project(inside[0][0]), project(inside[-1][1])
        if new_start is None or new_end is None:
            continue
        segment = {**seg, "start": new_start, "end": new_end}
        if kept_span < (seg_end - seg_start) - EPS:
            # Flag partial survivors so the evaluator does not read a sentence
            # as intact when the edit cut through it.
            segment["partial"] = True
        segments.append(segment)

    return {
        "duration": round(elapsed, 3),
        "segments": segments,
        "words": words,
        "source_duration": transcription.get("duration"),
        "derived_from": "transcription.json + applied cut intervals",
    }


def main(workspace: Path) -> int:
    transcription_file = workspace / "transcription.json"
    if not transcription_file.exists():
        print(f"[postcut] No {transcription_file.name} — skipping")
        return 0

    transcription = json.loads(transcription_file.read_text(encoding="utf-8"))
    duration = float(transcription.get("duration") or 0.0)
    intervals = load_intervals(workspace, duration)
    if not intervals:
        print("[postcut] No cut intervals found — skipping")
        return 0

    result = remap(transcription, intervals)
    (workspace / "post_cut_transcription.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dropped = len(transcription.get("words") or []) - len(result["words"])
    partial = sum(1 for s in result["segments"] if s.get("partial"))
    print(
        f"[postcut] Post-cut transcript: {result['duration']:.1f}s, "
        f"{len(result['words'])} words ({dropped} removed by the edit), "
        f"{len(result['segments'])} segments ({partial} cut through)"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m auto_edit.postcut <workspace>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
