"""
ALIGN-BLOCKS stage — narrated mode.
Maps each script block's narration text onto the recorded-voice transcription
to recover the real start/end of every block in the voice timeline.

Usage: python tools/block_aligner.py <workspace_dir>
"""
from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _align_blocks(words: list[dict], blocks: list[dict], vo_duration: float) -> list[dict]:
    """Greedy forward alignment: walk the word stream once, assigning a
    contiguous run of words to each block by best fuzzy match of its narration.
    Blocks are made contiguous so the assembled B-roll never leaves a gap."""
    norm_words = [_normalize(w["word"]) for w in words]
    out: list[dict] = []
    cursor = 0
    n = len(words)

    for block in blocks:
        target = _normalize(block["narration"]).split()
        if not target or cursor >= n:
            start = words[cursor]["start"] if cursor < n else vo_duration
            out.append({"id": block["id"], "vo_start": start, "vo_end": start})
            continue

        target_len = len(target)
        best_end = min(cursor + target_len, n)
        best_score = -1.0
        lo = cursor + max(1, target_len - 2)
        hi = min(n, cursor + target_len + 3)
        for end in range(lo, hi + 1):
            window = " ".join(norm_words[cursor:end])
            score = SequenceMatcher(None, window, " ".join(target)).ratio()
            if score > best_score:
                best_score = score
                best_end = end

        vo_start = words[cursor]["start"]
        vo_end = words[best_end - 1]["end"] if best_end > cursor else vo_start
        out.append({"id": block["id"], "vo_start": round(vo_start, 3),
                    "vo_end": round(vo_end, 3)})
        cursor = best_end

    # Strict contiguity: every block's vo_end must equal the next block's
    # vo_start, and the last block's vo_end must equal vo_duration.
    # No threshold — any gap (including intentional pauses) would leave the
    # voice timeline uncovered and cause visual drift downstream.
    for i in range(len(out) - 1):
        out[i]["vo_end"] = out[i + 1]["vo_start"]
    if out:
        out[-1]["vo_end"] = round(vo_duration, 3)

    # Clamp so no block has a negative/inverted span (e.g. more blocks than voice).
    prev_start = 0.0
    for b in out:
        b["vo_start"] = round(min(max(b["vo_start"], prev_start), vo_duration), 3)
        b["vo_end"] = round(min(max(b["vo_end"], b["vo_start"]), vo_duration), 3)
        prev_start = b["vo_start"]

    return out


def align(workspace: Path) -> None:
    transcription = json.loads((workspace / "transcription.json").read_text())
    script = json.loads((workspace / "script.json").read_text())
    words = transcription.get("words", [])
    vo_duration = float(transcription.get("duration", words[-1]["end"] if words else 0.0))
    blocks = _align_blocks(words, script.get("blocks", []), vo_duration)
    (workspace / "vo_alignment.json").write_text(
        json.dumps({"vo_duration": vo_duration, "blocks": blocks},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[align-blocks] Aligned {len(blocks)} blocks over {vo_duration:.1f}s of voice")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/block_aligner.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    align(Path(sys.argv[1]))
