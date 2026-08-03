"""Repair cut-plan boundaries after the review stage.

The planner/reviewer agents work from transcript timestamps and reliably make
three mechanical mistakes that prompt rules did not fix:

1. A boundary lands a few milliseconds inside a spoken word, clipping it.
2. The splice repeats a phrase ("eu indico, ⟹ eu indico para vocês") because
   the cut removed the first half of a restart but not the duplicate.
3. The splice starts on an orphaned fragment ("…não tem problema. ⟹ que,
   galera…") because the cut ate the head of the sentence.

Each is corrected here, deterministically. Boundaries only ever move so that
less speech is destroyed, except when removing a literal duplicate. Cuts that
collapse to nothing are dropped and kept_segments is rebuilt from what survives.

Run as: python -m auto_edit.snap <workspace>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Boundaries closer than this to a word edge are treated as touching it.
EPS = 0.001

# Longest phrase repetition we look for across a splice.
MAX_REPEAT_WORDS = 6

# Words that cannot open a sentence on their own: if the audio right after a cut
# starts with one, the cut swallowed the head of the clause.
ORPHAN_OPENERS = {
    "que", "porque", "porém", "mas", "e", "ou", "então", "aí", "só", "pois",
    "pra", "para", "de", "do", "da", "dos", "das", "em", "no", "na", "com",
    "como", "quando", "se", "qual", "quais", "cujo", "cuja", "onde",
}

# A boundary this close to a transcript segment's edge is pulled onto it.
SEGMENT_EDGE_GUARD = 0.6

# How far back a boundary may move to rescue an orphaned fragment. Beyond this
# the cut is left alone -- reviving several seconds of audio to fix grammar
# would undo the edit the agent intended.
MAX_ORPHAN_REWIND = 2.5

# A "silence" cut over audio louder than this is not silence: the word list just
# failed to report the speech there. Real room tone in these recordings sits
# around -45dB and below; speech sits around -15dB.
SILENCE_MAX_DB = -32.0

# When a cut gutted the head of a sentence, this much of its tail may be
# swallowed too so no dangling fragment survives ("...comentei ⟹ aqui,").
# Beyond it the leftover is real content the agent meant to keep.
MAX_SEGMENT_RESIDUE = 1.5


def _word_at(words: list[dict], t: float) -> dict | None:
    """The word strictly containing t, if any."""
    for w in words:
        try:
            start, end = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start + EPS < t < end - EPS:
            return {"start": start, "end": end, "word": w.get("word", "")}
    return None


def _protect_segment_edges(
    start: float, end: float, segments: list[dict]
) -> tuple[float, float, str | None]:
    """Keep boundaries off the first/last instant of a transcript segment.

    Whisper's word list drops a word now and then ("Só que, galera" arrives as
    "que, galera") while the segment text still has it. Without this, a cut
    lands a few dozen ms inside a word the word list never reported.
    """
    note = None
    for seg in segments:
        try:
            seg_start, seg_end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if seg_start < end <= seg_start + SEGMENT_EDGE_GUARD:
            note = (seg.get("text") or "").strip()[:40]
            end = seg_start
        if seg_end - SEGMENT_EDGE_GUARD <= start < seg_end:
            note = (seg.get("text") or "").strip()[-40:]
            start = seg_end
    return start, end, note


def trim_loud_silences(
    cuts: list[dict], energy_db: list[float], resolution: float
) -> tuple[list[dict], list[str]]:
    """Drop or shrink "silence" cuts that sit over audible speech.

    Whisper's word list drops a word every so often. When it does, the planner
    sees a gap between consecutive words and calls it a hesitation -- so the cut
    deletes the very word the word list forgot ("eu tenho esse ⟹ aqui", the
    word "windows" gone). The energy map settles it: real room tone here is
    around -45dB, speech around -15dB. Anything a "silence" cut covers that is
    louder than SILENCE_MAX_DB is speech and must survive.
    """
    if not energy_db or resolution <= 0:
        return cuts, []

    kept: list[dict] = []
    notes: list[str] = []

    for cut in cuts:
        if (cut.get("type") or "silence") != "silence":
            kept.append(cut)
            continue

        start, end = float(cut["start"]), float(cut["end"])
        first = max(0, int(start / resolution))
        last = min(len(energy_db) - 1, int((end - EPS) / resolution))
        if last < first:
            kept.append(cut)
            continue

        quiet = [i for i in range(first, last + 1) if energy_db[i] <= SILENCE_MAX_DB]
        if not quiet:
            notes.append(
                f"dropped silence cut {start:.2f}-{end:.2f}s: audio there peaks at "
                f"{max(energy_db[first:last + 1]):.1f}dB — that is speech, not silence"
            )
            continue

        new_start = max(start, quiet[0] * resolution)
        new_end = min(end, (quiet[-1] + 1) * resolution)
        if new_end - new_start <= EPS:
            notes.append(
                f"dropped silence cut {start:.2f}-{end:.2f}s: nothing quiet left after "
                f"trimming audible audio"
            )
            continue

        if (new_start, new_end) != (start, end):
            notes.append(
                f"trimmed silence cut {start:.2f}-{end:.2f}s → "
                f"{new_start:.2f}-{new_end:.2f}s (edges were over audible speech)"
            )
        kept.append({**cut, "start": new_start, "end": new_end})

    return kept, notes


def swallow_segment_residue(
    cuts: list[dict], segments: list[dict]
) -> tuple[list[dict], list[str]]:
    """Finish off a sentence the cut already gutted.

    When the speaker restarts a line, the cut removes the botched take -- but if
    its end lands a word short of the sentence, that last word survives alone
    ("...que eu comentei ⟹ aqui,") and shows up as a caption nobody said. If the
    cut already swallowed the head of that sentence, extend it over the scrap.

    Only ever applies when the cut starts at or before the segment, so an intact
    sentence is never bitten into.
    """
    adjusted: list[dict] = []
    notes: list[str] = []

    for cut in cuts:
        start, end = float(cut["start"]), float(cut["end"])
        for seg in segments:
            try:
                seg_start, seg_end = float(seg["start"]), float(seg["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if start > seg_start + EPS:
                continue  # the cut did not take this sentence's head
            if not (seg_start < end < seg_end - EPS):
                continue
            if seg_end - end > MAX_SEGMENT_RESIDUE:
                continue  # too much left to be a scrap
            notes.append(
                f"extended cut {start:.2f}-{end:.2f}s → {start:.2f}-{seg_end:.2f}s "
                f"(left a {seg_end - end:.2f}s fragment of “{(seg.get('text') or '').strip()[-30:]}”)"
            )
            end = seg_end
            break
        adjusted.append({**cut, "start": start, "end": end})

    return _merge_overlaps(adjusted), notes


def snap_cuts(
    cuts: list[dict],
    words: list[dict],
    duration: float,
    segments: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    """Shrink each cut until both boundaries sit in a gap between words."""
    snapped: list[dict] = []
    notes: list[str] = []

    for cut in cuts:
        try:
            start, end = float(cut["start"]), float(cut["end"])
        except (KeyError, TypeError, ValueError):
            notes.append(f"dropped malformed cut: {cut!r}")
            continue

        original = (start, end)

        # A boundary inside a word moves so the whole word survives.
        head = _word_at(words, start)
        if head is not None:
            start = head["end"]
        tail = _word_at(words, end)
        if tail is not None:
            end = tail["start"]

        start, end, segment_note = _protect_segment_edges(start, end, segments or [])
        if segment_note:
            notes.append(
                f"cut {start:.2f}-{end:.2f}s pulled off a segment edge "
                f"(word list was missing a word in “{segment_note}”)"
            )

        start = max(0.0, start)
        end = min(duration, end)

        if end - start <= EPS:
            notes.append(
                f"dropped cut {original[0]:.2f}-{original[1]:.2f}s "
                f"({cut.get('type', '?')}): nothing left after snapping to word gaps"
            )
            continue

        if (start, end) != original:
            words_touched = " / ".join(
                w["word"].strip() for w in (head, tail) if w and w["word"].strip()
            )
            notes.append(
                f"snapped cut {original[0]:.2f}-{original[1]:.2f}s → {start:.2f}-{end:.2f}s"
                + (f" (was clipping: {words_touched})" if words_touched else "")
            )

        snapped.append({**cut, "start": start, "end": end})

    return _merge_overlaps(snapped), notes


def _normalize(word: str) -> str:
    return re.sub(r"[^\wÀ-ÿ]", "", word or "").casefold()


def _is_orphan_opener(word: str) -> bool:
    """A lowercase connective can't open a sentence — so the cut ate its head.

    Whisper capitalizes sentence starts, so "Só que…" is a legitimate opening
    while "…problema. que, galera" is wreckage left by a cut.
    """
    stripped = re.sub(r"^[^\wÀ-ÿ]+", "", word or "")
    if not stripped or stripped[:1].isupper():
        return False
    return _normalize(stripped) in ORPHAN_OPENERS


def _words_before(words: list[dict], t: float, limit: int) -> list[dict]:
    return [w for w in words if float(w["end"]) <= t + EPS][-limit:]


def _words_after(words: list[dict], t: float, limit: int) -> list[dict]:
    return [w for w in words if float(w["start"]) >= t - EPS][:limit]


def dedupe_splices(cuts: list[dict], words: list[dict]) -> tuple[list[dict], list[str]]:
    """Extend a cut when the same phrase sits on both sides of its splice.

    The agent cuts the first half of a restart and leaves the duplicate behind.
    Whatever is repeated verbatim was already said, so removing the second copy
    destroys no information.
    """
    result: list[dict] = []
    notes: list[str] = []

    for cut in cuts:
        end = float(cut["end"])
        before = [_normalize(w["word"]) for w in _words_before(words, float(cut["start"]), MAX_REPEAT_WORDS)]
        after_words = _words_after(words, end, MAX_REPEAT_WORDS)
        after = [_normalize(w["word"]) for w in after_words]

        for size in range(min(len(before), len(after)), 1, -1):
            if before[-size:] == after[:size]:
                phrase = " ".join(w["word"].strip() for w in after_words[:size])
                new_end = float(after_words[size - 1]["end"])
                notes.append(
                    f"extended cut {cut['start']:.2f}-{end:.2f}s → {cut['start']:.2f}-{new_end:.2f}s "
                    f"(splice repeated: “{phrase}”)"
                )
                end = new_end
                break

        result.append({**cut, "end": end})

    return result, notes


def unorphan_splices(cuts: list[dict], words: list[dict]) -> tuple[list[dict], list[str]]:
    """Pull a boundary back when the splice would open on a dangling fragment.

    "…não tem problema. ⟹ que, galera, eu atualizei…" means the cut ate the
    "Só". Rewinding the cut's end restores the head of the clause; if the head
    is too far back, the cut is left as the agent planned it.
    """
    result: list[dict] = []
    notes: list[str] = []

    for cut in cuts:
        start, end = float(cut["start"]), float(cut["end"])
        after = _words_after(words, end, 1)
        before = _words_before(words, start, 1)
        # Only wreckage counts: "…aqui, ⟹ que não deu certo" is one continuous
        # sentence spanning a silence trim. It becomes an orphan only when the
        # previous sentence already closed.
        sentence_closed = bool(before) and (before[-1].get("word") or "").rstrip().endswith((".", "?", "!", "…"))
        if not after or not sentence_closed or not _is_orphan_opener(after[0]["word"]):
            result.append(dict(cut))
            continue

        # Walk back through the words the cut removed until one can open a
        # sentence -- that is the head the splice is missing.
        removed = [w for w in words if float(w["start"]) >= start - EPS and float(w["end"]) <= end + EPS]
        head = None
        for w in reversed(removed):
            head = w
            if not _is_orphan_opener(w["word"]):
                break
        if head is None:
            # The cut removed no words at all (pure silence) -- the fragment was
            # already dangling in the source, not something this cut created.
            result.append(dict(cut))
            continue
        if end - float(head["start"]) > MAX_ORPHAN_REWIND:
            notes.append(
                f"left cut {start:.2f}-{end:.2f}s as planned "
                f"(splice opens on “{after[0]['word'].strip()}”, head too far back to rescue)"
            )
            result.append(dict(cut))
            continue

        new_end = float(head["start"])
        if new_end - start <= EPS:
            result.append(dict(cut))
            continue
        notes.append(
            f"rewound cut {start:.2f}-{end:.2f}s → {start:.2f}-{new_end:.2f}s "
            f"(splice opened on orphaned “{after[0]['word'].strip()}”)"
        )
        result.append({**cut, "end": new_end})

    return result, notes


def _merge_overlaps(cuts: list[dict]) -> list[dict]:
    """Merge cuts that overlap or touch, keeping the first one's metadata."""
    ordered = sorted(cuts, key=lambda c: c["start"])
    merged: list[dict] = []
    for cut in ordered:
        if merged and cut["start"] <= merged[-1]["end"] + EPS:
            prev = merged[-1]
            if cut["end"] > prev["end"]:
                prev["end"] = cut["end"]
                prev["reason"] = f"{prev.get('reason', '')} + {cut.get('reason', '')}".strip(" +")
            continue
        merged.append(dict(cut))
    return merged


def rebuild_kept(
    cuts: list[dict], duration: float, previous: list[dict] | None = None
) -> list[dict]:
    """kept_segments = the timeline minus the cuts, carrying summaries over."""
    kept: list[dict] = []
    cursor = 0.0
    for cut in sorted(cuts, key=lambda c: c["start"]):
        if cut["start"] - cursor > EPS:
            kept.append({"start": cursor, "end": cut["start"]})
        cursor = max(cursor, cut["end"])
    if duration - cursor > EPS:
        kept.append({"start": cursor, "end": duration})

    for seg in kept:
        summary = _best_summary(seg, previous or [])
        if summary:
            seg["summary"] = summary
    return kept


def _best_summary(segment: dict, previous: list[dict]) -> str | None:
    """Summary of whichever old segment overlaps this one the most."""
    best, best_overlap = None, 0.0
    for old in previous:
        try:
            overlap = min(segment["end"], float(old["end"])) - max(
                segment["start"], float(old["start"])
            )
        except (KeyError, TypeError, ValueError):
            continue
        if overlap > best_overlap and old.get("summary"):
            best, best_overlap = old["summary"], overlap
    return best


def snap_plan(
    plan: dict,
    words: list[dict],
    duration: float,
    segments: list[dict] | None = None,
    energy_db: list[float] | None = None,
    resolution: float = 0.0,
) -> tuple[dict, list[str]]:
    # Reject fake silences first: a cut over speech must not get "snapped" to a
    # word gap that only exists because the word list is incomplete.
    cuts, notes = trim_loud_silences(plan.get("cuts") or [], energy_db or [], resolution)

    cuts, snap_notes = snap_cuts(cuts, words, duration, segments)
    notes += snap_notes

    # Grammar repairs run on boundaries that already sit in word gaps.
    cuts, orphan_notes = unorphan_splices(cuts, words)
    cuts, repeat_notes = dedupe_splices(cuts, words)
    cuts, residue_notes = swallow_segment_residue(cuts, segments or [])
    notes += orphan_notes + repeat_notes + residue_notes

    cuts = _merge_overlaps(cuts)

    result = dict(plan)
    result["cuts"] = cuts
    result["kept_segments"] = rebuild_kept(cuts, duration, plan.get("kept_segments"))
    return result, notes


def main(workspace: Path) -> int:
    plan_file = workspace / "reviewed_plan.json"
    transcription_file = workspace / "transcription.json"
    if not plan_file.exists() or not transcription_file.exists():
        print(f"[snap] Nothing to do (missing {plan_file.name} or {transcription_file.name})")
        return 0

    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    transcription = json.loads(transcription_file.read_text(encoding="utf-8"))
    words = transcription.get("words") or []
    segments = transcription.get("segments") or []
    duration = float(transcription.get("duration") or 0.0)

    if not words or duration <= 0:
        print("[snap] No word timestamps — leaving the plan untouched")
        return 0

    snapped, notes = snap_plan(
        plan,
        words,
        duration,
        segments,
        transcription.get("energy_db") or [],
        float(transcription.get("resolution_seconds") or 0.0),
    )

    for note in notes:
        print(f"[snap] {note}")
    if not notes:
        print("[snap] All cut boundaries already sat in word gaps")

    if snapped != plan:
        (workspace / "reviewed_plan.pre_snap.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        plan_file.write_text(
            json.dumps(snapped, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"[snap] Wrote {len(snapped['cuts'])} cuts / "
            f"{len(snapped['kept_segments'])} kept segments (original: reviewed_plan.pre_snap.json)"
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m auto_edit.snap <workspace>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
