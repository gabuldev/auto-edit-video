"""Objective metrics for comparing two cut plans of the same recording.

Everything here is measured against the same `transcription.json` (word-level
timestamps + the energy map), so the numbers describe the plans, not the tools
that produced them. No judgment calls: "which cut is better" is for the
evaluator agent and for watching the two files. This answers the questions that
have a right answer — how much speech got clipped mid-word, how much dead air
survived, how much the two arms agree.

Used by run_bench.py; also runnable on its own:
    python benchmarks/metrics.py <transcription.json> ours=<plan> gemini=<plan>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auto_edit import snap  # noqa: E402  (path set above)

Interval = tuple[float, float]


def intervals(plan: dict, key: str = "kept_segments") -> list[Interval]:
    out: list[Interval] = []
    for seg in plan.get(key) or []:
        try:
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            out.append((start, end))
    return sorted(out)


def total(spans: list[Interval]) -> float:
    return sum(end - start for start, end in spans)


def overlap(a: list[Interval], b: list[Interval]) -> float:
    """Seconds covered by both interval sets."""
    shared, i, j = 0.0, 0, 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if hi > lo:
            shared += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return shared


def words_clipped(words: list[dict], cuts: list[Interval]) -> int:
    """Words a cut boundary lands strictly inside — audible mid-word chops.

    This is the defect the `snap` pass exists to repair, so measuring it before
    and after snapping says how much mechanical help each planner needed.
    """
    clipped = 0
    for word in words:
        try:
            w_start, w_end = float(word["start"]), float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        for c_start, c_end in cuts:
            if c_start > w_end or c_end < w_start:
                continue
            inside_start = w_start + snap.EPS < c_start < w_end - snap.EPS
            inside_end = w_start + snap.EPS < c_end < w_end - snap.EPS
            if inside_start or inside_end:
                clipped += 1
                break
    return clipped


def words_kept(words: list[dict], kept: list[Interval]) -> int:
    count = 0
    for word in words:
        try:
            mid = (float(word["start"]) + float(word["end"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if any(start <= mid <= end for start, end in kept):
            count += 1
    return count


def silence_left(kept: list[Interval], energy: list[float], resolution: float, threshold: float) -> float:
    """Seconds of the final cut that sit at or below this recording's silence floor."""
    if not energy or resolution <= 0:
        return 0.0
    quiet = 0.0
    for start, end in kept:
        first = max(0, int(start / resolution))
        last = min(len(energy) - 1, int((end - snap.EPS) / resolution))
        for index in range(first, last + 1):
            if energy[index] <= threshold:
                quiet += resolution
    return round(quiet, 2)


def describe(plan: dict, transcription: dict, energy: list[float], resolution: float) -> dict:
    duration = float(transcription.get("duration") or 0.0)
    words = transcription.get("words") or []
    threshold = snap.silence_threshold_db(energy) if energy else 0.0

    kept = intervals(plan, "kept_segments")
    cuts = intervals(plan, "cuts")
    final = total(kept)
    cut_lengths = sorted(end - start for start, end in cuts)

    return {
        "final_duration": round(final, 2),
        "removed": round(duration - final, 2),
        "removed_pct": round(100 * (duration - final) / duration, 1) if duration else 0.0,
        "cuts": len(cuts),
        "kept_segments": len(kept),
        "median_cut": round(cut_lengths[len(cut_lengths) // 2], 2) if cut_lengths else 0.0,
        "longest_cut": round(cut_lengths[-1], 2) if cut_lengths else 0.0,
        "dropped_blocks": len(plan.get("dropped_blocks") or []),
        "words_kept": words_kept(words, kept),
        "words_total": len(words),
        "words_clipped": words_clipped(words, cuts),
        "silence_left": silence_left(kept, energy, resolution, threshold),
        "silence_threshold_db": round(threshold, 1),
    }


def compare(transcription_path: Path, plans: dict[str, Path]) -> dict:
    transcription = json.loads(transcription_path.read_text(encoding="utf-8"))
    energy, resolution = snap.load_energy_map(transcription_path.parent)

    loaded = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in plans.items()}
    report = {
        "duration": round(float(transcription.get("duration") or 0.0), 2),
        "arms": {name: describe(plan, transcription, energy, resolution) for name, plan in loaded.items()},
    }

    names = list(loaded)
    if len(names) == 2:
        a, b = (intervals(loaded[n]) for n in names)
        shared = overlap(a, b)
        union = total(a) + total(b) - shared
        report["agreement"] = {
            "pair": names,
            "kept_overlap": round(shared, 2),
            "iou": round(shared / union, 3) if union else 0.0,
            "only_in_" + names[0]: round(total(a) - shared, 2),
            "only_in_" + names[1]: round(total(b) - shared, 2),
        }
    return report


def render(report: dict) -> str:
    """Markdown table — what goes into the benchmark write-up."""
    arms = report["arms"]
    names = list(arms)
    rows = [
        ("duração final", "final_duration", "s"),
        ("removido", "removed", "s"),
        ("removido", "removed_pct", "%"),
        ("cortes", "cuts", ""),
        ("trechos mantidos", "kept_segments", ""),
        ("corte mediano", "median_cut", "s"),
        ("maior corte", "longest_cut", "s"),
        ("blocos descartados", "dropped_blocks", ""),
        ("palavras mantidas", "words_kept", ""),
        ("palavras cortadas ao meio", "words_clipped", ""),
        ("silêncio no corte final", "silence_left", "s"),
    ]
    lines = [
        f"Bruto: **{report['duration']}s**",
        "",
        "| métrica | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for label, key, unit in rows:
        values = " | ".join(f"{arms[n][key]}{unit}" for n in names)
        lines.append(f"| {label} | {values} |")

    if "agreement" in report:
        agree = report["agreement"]
        lines += [
            "",
            f"**Concordância:** IoU {agree['iou']} — {agree['kept_overlap']}s mantidos pelos dois, "
            f"{agree['only_in_' + names[0]]}s só em {names[0]}, "
            f"{agree['only_in_' + names[1]]}s só em {names[1]}.",
        ]
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: metrics.py <transcription.json> name=<plan.json> [name=<plan.json>]", file=sys.stderr)
        raise SystemExit(1)
    transcription = Path(sys.argv[1])
    plans = {}
    for arg in sys.argv[2:]:
        name, _, path = arg.partition("=")
        plans[name] = Path(path)
    report = compare(transcription, plans)
    print(render(report))
    print("\n" + json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
