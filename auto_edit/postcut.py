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

# A partial segment shorter than this with no surviving words is edit residue.
RESIDUE_DURATION = 0.5


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
    """Project words and segments of the source onto the edited timeline.

    `intervals` are in *playback* order. Usually that is chronological, but a
    reordered edit (sequence / cold open) can play a later part first, or the
    same source window twice — so everything is placed interval by interval,
    never by looking a source time up in a single map.
    """
    placed: list[tuple[float, float, float]] = []  # (src start, src end, output start)
    elapsed = 0.0
    for start, end in intervals:
        placed.append((start, end, elapsed))
        elapsed += end - start

    source_words = []
    for w in transcription.get("words") or []:
        try:
            source_words.append((float(w["start"]), float(w["end"]), w))
        except (KeyError, TypeError, ValueError):
            continue

    words = []
    for start, end, out in placed:
        for w_start, w_end, w in source_words:
            # A word survives only if both edges landed in the same kept interval.
            if start - EPS <= w_start and w_end <= end + EPS and w_end >= w_start:
                words.append({
                    **w,
                    "start": round(w_start - start + out, 3),
                    "end": round(w_end - start + out, 3),
                })

    # Pieces of each source segment, in playback order. A segment that a cut
    # went through shows up as one piece per interval it touches.
    pieces: list[dict] = []
    source_segments = transcription.get("segments") or []
    for i_interval, (start, end, out) in enumerate(placed):
        for i_seg, seg in enumerate(source_segments):
            try:
                seg_start, seg_end = float(seg["start"]), float(seg["end"])
            except (KeyError, TypeError, ValueError):
                continue
            lo, hi = max(seg_start, start), min(seg_end, end)
            if hi <= lo:
                continue
            last = pieces[-1] if pieces else None
            if last and last["seg"] == i_seg and last["interval"] == i_interval - 1:
                # Same sentence continuing in the next interval right after:
                # one segment, cut through (what a plain chronological cut gives).
                last.update(interval=i_interval, out_end=hi - start + out, kept=last["kept"] + hi - lo)
                continue
            pieces.append({
                "seg": i_seg,
                "interval": i_interval,
                "out_start": lo - start + out,
                "out_end": hi - start + out,
                "kept": hi - lo,
            })

    segments = []
    for piece in pieces:
        seg = source_segments[piece["seg"]]
        seg_start, seg_end = float(seg["start"]), float(seg["end"])
        new_start, new_end = round(piece["out_start"], 3), round(piece["out_end"], 3)
        segment = {**seg, "start": new_start, "end": new_end}
        if piece["kept"] < (seg_end - seg_start) - EPS:
            # Flag partial survivors so the evaluator does not read a sentence
            # as intact when the edit cut through it -- and rebuild the text
            # from the words that survived, or it would show speech the edit
            # already removed.
            segment["partial"] = True
            surviving = [
                w["word"]
                for w in words
                if new_start - EPS <= float(w["start"]) and float(w["end"]) <= new_end + EPS
            ]
            if surviving:
                segment["text"] = " ".join(x.strip() for x in surviving if x.strip())
            elif new_end - new_start < RESIDUE_DURATION and source_words:
                # Nothing but a sliver of audio is left and no word landed in
                # it: the edit removed this sentence. Keeping it would show the
                # evaluator speech that is not in the video.
                continue
            segment["original_text"] = seg.get("text", "")
        segments.append(segment)

    return {
        "duration": round(elapsed, 3),
        "segments": segments,
        "words": words,
        "source_duration": transcription.get("duration"),
        "derived_from": "transcription.json + applied cut intervals",
    }


def planned(workspace: Path) -> dict | None:
    """The transcript of the cut the plan describes, before anything renders.

    Same intervals the executor will cut (end padding, silence-aware tails,
    the plan's playback sequence), so the evaluator judges the real edit
    without waiting for FFmpeg. Only the executor's onset snap of the first
    interval is missing — a fraction of a second of leading silence.
    """
    from auto_edit import intervals as iv
    from auto_edit import sequence, snap

    try:
        transcription = json.loads((workspace / "transcription.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plan_file = next((workspace / n for n in ("reviewed_plan.json", "cut_plan.json") if (workspace / n).exists()), None)
    if plan_file is None:
        return None
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    duration = float(transcription.get("duration") or 0.0)
    energy, resolution = snap.load_energy_map(workspace)
    kept = iv.build_keep_intervals(plan, duration, energy, resolution)
    if plan.get("sequence"):
        kept, _notes = sequence.apply(kept, plan["sequence"])
    result = remap(transcription, kept)
    result["derived_from"] = "transcription.json + planned cut (before render)"
    (workspace / "post_cut_transcription.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


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
    source_words = transcription.get("words") or []
    survivors = sum(
        1 for w in source_words
        if any(a - EPS <= float(w["start"]) and float(w["end"]) <= b + EPS for a, b in intervals)
    )
    dropped = len(source_words) - survivors
    repeated = len(result["words"]) - survivors  # a teaser plays its words twice
    partial = sum(1 for s in result["segments"] if s.get("partial"))
    print(
        f"[postcut] Post-cut transcript: {result['duration']:.1f}s, "
        f"{len(result['words'])} words ({dropped} removed by the edit"
        + (f", {repeated} repeated by the sequence" if repeated > 0 else "")
        + f"), {len(result['segments'])} segments ({partial} cut through)"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m auto_edit.postcut [--planned] <workspace>", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] == "--planned":
        res = planned(Path(sys.argv[2]))
        if res is None:
            print("[postcut] No plan/transcription — evaluating without a post-cut transcript")
        else:
            print(f"[postcut] Planned cut: {res['duration']:.1f}s, {len(res['words'])} words (before render)")
        sys.exit(0)
    sys.exit(main(Path(sys.argv[1])))
