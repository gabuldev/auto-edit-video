"""The intervals an edit keeps, computed from the cut plan alone.

The executor renders them; the evaluate stage (which now runs *before*
rendering) needs the exact same intervals to build the transcript of the cut
it is judging. Pure Python: no FFmpeg here — the one step that needs it, the
executor's onset snap of the first interval, moves a boundary by fractions of
a second and is left to the render.
"""
from __future__ import annotations

import os

from auto_edit import snap

MIN_INTERVAL_DURATION = 1.0 / 30  # 1 frame at 30fps ≈ 0.033s


def build_keep_intervals(
    plan: dict,
    duration: float,
    energy_db: list[float] | None = None,
    resolution: float = 0.0,
) -> list[tuple[float, float]]:
    """
    Convert kept_segments from reviewed_plan.json into (start, end) tuples.
    Applies end-padding (default 0.2s, override AUTO_EDIT_END_PADDING) to each
    segment end (not start) to avoid cutting word tails -- but only as far as
    the audio stays audible, so the pad never reaches into a silence cut.
    Clamps to video duration and merges overlapping intervals.
    """
    end_padding = float(os.environ.get("AUTO_EDIT_END_PADDING", "0.2"))
    threshold = snap.silence_threshold_db(energy_db or [])
    raw = plan.get("kept_segments", [])
    if not raw:
        # Fallback: invert the cuts list
        cuts = sorted(plan.get("cuts", []), key=lambda c: c["start"])
        raw = invert_cuts(cuts, duration)

    padded: list[tuple[float, float]] = []
    for seg in raw:
        start = max(0.0, float(seg["start"]))
        raw_end = float(seg["end"])
        pad = snap.audible_tail(raw_end, end_padding, energy_db or [], resolution, threshold)
        end = min(duration, raw_end + pad)
        if end > start:
            padded.append((start, end))

    merged = merge_intervals(sorted(padded))

    # filter out sub-frame intervals that would produce 0 frames in concat
    filtered = [(s, e) for s, e in merged if (e - s) >= MIN_INTERVAL_DURATION]
    if not filtered:
        raise RuntimeError("All kept segments are shorter than 1 frame — nothing to output")

    return filtered


def invert_cuts(cuts: list[dict], duration: float) -> list[dict]:
    """Convert a list of cut intervals into keep intervals."""
    keep = []
    cursor = 0.0
    for cut in cuts:
        s = float(cut["start"])
        e = float(cut["end"])
        if s >= e:
            continue  # degenerate cut (no-op) — skip so cursor never regresses
        if s > cursor:
            keep.append({"start": cursor, "end": s})
        cursor = e
    if cursor < duration:
        keep.append({"start": cursor, "end": duration})
    return keep


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or touching intervals."""
    if not intervals:
        return []
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged
