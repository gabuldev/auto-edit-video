"""Ordem de reprodução de um edit: cold open e reordenação de trechos.

O plano de cortes diz **o que fica** (`kept_segments`, sempre cronológico —
snap, revisão e a tela de cortes trabalham assim). O campo opcional
`sequence` diz **em que ordem tocar**:

    "sequence": [
      {"start": 98.0, "end": 104.5, "role": "teaser"},   # cold open
      {"start": 0.0,  "end": 60.0},                      # bloco 1
      {"start": 120.0, "end": 569.0},                    # bloco 3 antes do 2
      {"start": 60.0, "end": 120.0}
    ]

Cada item é uma janela no tempo do vídeo ORIGINAL. O que toca de cada janela
é a interseção com os intervalos que o executor realmente manteve (já com
padding e snap), então a sequência nunca ressuscita algo que foi cortado e
sobrevive a pequenos ajustes de borda.

Regras (fora delas a sequência é ignorada e o vídeo sai cronológico, com o
motivo no log — nunca perde conteúdo):

- os blocos (`role` ausente ou "block") cobrem tudo que foi mantido, sem se
  sobrepor: reordenar não pode sumir nem duplicar trecho;
- teasers são extras: tocam onde estiverem na lista e o trecho toca de novo no
  lugar dele. Cada um entre 2 e 15s, e no máximo 20s somados.
"""
from __future__ import annotations

TOLERANCE = 0.05  # seconds of kept audio a block may miss (rounding / padding)
MIN_PIECE = 1 / 30  # anything shorter than a frame is not worth a cut
TEASER_MIN = 2.0
TEASER_MAX = 15.0
TEASERS_TOTAL_MAX = 20.0

Interval = tuple[float, float]


def _clip(intervals: list[Interval], start: float, end: float) -> list[Interval]:
    """The parts of the kept intervals inside [start, end], chronological."""
    out = []
    for s, e in intervals:
        lo, hi = max(s, start), min(e, end)
        if hi - lo >= MIN_PIECE:
            out.append((lo, hi))
    return out


def _total(intervals: list[Interval]) -> float:
    return sum(e - s for s, e in intervals)


def _merge_adjacent(intervals: list[Interval]) -> list[Interval]:
    """Join pieces that continue each other in the source (one cut fewer)."""
    merged: list[Interval] = []
    for s, e in intervals:
        if merged and abs(merged[-1][1] - s) < 1e-6:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def apply(intervals: list[Interval], sequence) -> tuple[list[Interval], list[str]]:
    """Reorder the kept intervals per `sequence`. Returns (playback order, notes).

    No sequence → intervals unchanged. Invalid sequence → intervals unchanged
    plus the reason in `notes`.
    """
    if not sequence:
        return list(intervals), []
    if not isinstance(sequence, list):
        return list(intervals), ["sequence não é uma lista — ordem cronológica mantida"]

    items = []
    for i, raw in enumerate(sequence, start=1):
        try:
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            return list(intervals), [f"sequence[{i}] sem start/end válidos — ordem cronológica mantida"]
        role = (raw.get("role") or "block") if isinstance(raw, dict) else "block"
        if role not in ("block", "teaser"):
            return list(intervals), [f"sequence[{i}] role '{role}' desconhecido — ordem cronológica mantida"]
        if end <= start:
            return list(intervals), [f"sequence[{i}] termina antes de começar — ordem cronológica mantida"]
        items.append({"start": start, "end": end, "role": role, "pieces": _clip(intervals, start, end)})

    blocks = [it for it in items if it["role"] == "block"]
    teasers = [it for it in items if it["role"] == "teaser"]

    # Blocks must not overlap: that would play the same speech twice.
    spans = sorted((it["start"], it["end"]) for it in blocks)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        if s2 < e1 - TOLERANCE:
            return list(intervals), [
                f"blocos se sobrepõem ({s1:.1f}–{e1:.1f}s e {s2:.1f}–{e2:.1f}s) — ordem cronológica mantida"
            ]

    # Blocks must cover everything kept: reordering can't drop content.
    covered = _total([p for it in blocks for p in it["pieces"]])
    kept = _total(intervals)
    if covered < kept - TOLERANCE * max(1, len(intervals)):
        return list(intervals), [
            f"os blocos cobrem {covered:.1f}s de {kept:.1f}s mantidos — ordem cronológica mantida"
        ]

    notes: list[str] = []
    total_teaser = 0.0
    for it in teasers:
        length = _total(it["pieces"])
        label = f"teaser {it['start']:.1f}–{it['end']:.1f}s"
        if length < TEASER_MIN or length > TEASER_MAX:
            notes.append(f"{label} ignorado: {length:.1f}s (precisa de {TEASER_MIN:.0f}–{TEASER_MAX:.0f}s mantidos)")
            it["pieces"] = []
        elif total_teaser + length > TEASERS_TOTAL_MAX:
            notes.append(f"{label} ignorado: teasers passariam de {TEASERS_TOTAL_MAX:.0f}s")
            it["pieces"] = []
        else:
            total_teaser += length

    playback = _merge_adjacent([p for it in items for p in it["pieces"]])
    return playback, notes


def describe(playback: list[Interval]) -> str:
    """One line per played interval, for the executor log."""
    return "\n".join(f"  [{i + 1}] {s:.2f}s → {e:.2f}s  ({e - s:.2f}s)" for i, (s, e) in enumerate(playback))


# ── Cold open (agent → plan) ──────────────────────────────────────────────────

COLD_OPEN_FILE = "cold_open.json"
# A teaser from the opening seconds is not a cold open: it already plays first.
MIN_KEPT_BEFORE_TEASER = 15.0


def _read(path):
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def kept_intervals(plan: dict) -> list[Interval]:
    out = []
    for seg in plan.get("kept_segments") or []:
        try:
            s, e = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e > s:
            out.append((s, e))
    return sorted(out)


def wants_cold_open(workspace) -> bool:
    """Cold open was asked for (pipeline.json or AUTO_EDIT_COLD_OPEN) and the
    plan has no sequence yet — a hand-made one is never overwritten."""
    import os
    from pathlib import Path

    ws = Path(workspace)
    pipeline = _read(ws / "pipeline.json") or {}
    asked = bool(pipeline.get("cold_open")) or os.environ.get("AUTO_EDIT_COLD_OPEN", "").lower() in ("1", "true", "yes")
    plan = _read(ws / "reviewed_plan.json") or {}
    return asked and not plan.get("sequence")


def merge_cold_open(workspace) -> list[str]:
    """Turn the agent's teaser into the plan's `sequence`. Returns log notes.

    Writes nothing when the agent skipped, or when the teaser would not
    survive `apply` (inside a cut, too short/long) or sits in the opening.
    """
    import json
    from pathlib import Path

    ws = Path(workspace)
    answer = _read(ws / COLD_OPEN_FILE) or {}
    teaser = answer.get("teaser") if isinstance(answer, dict) else None
    if not teaser:
        return [f"agente não escolheu cold open: {answer.get('reason') or 'sem motivo'}"]

    plan_path = ws / "reviewed_plan.json"
    plan = _read(plan_path) or {}
    kept = kept_intervals(plan)
    if not kept:
        return ["plano sem trechos mantidos — cold open ignorado"]
    try:
        start, end = float(teaser["start"]), float(teaser["end"])
    except (KeyError, TypeError, ValueError):
        return ["teaser sem start/end válidos — cold open ignorado"]

    before = _total(_clip(kept, 0.0, start))
    if before < MIN_KEPT_BEFORE_TEASER:
        return [f"teaser em {start:.1f}s está na abertura ({before:.1f}s depois do início) — cold open ignorado"]

    candidate = [
        {"start": round(start, 3), "end": round(end, 3), "role": "teaser"},
        # Everything else, in order. The slack covers the executor's end padding;
        # what plays is still clipped to what was kept.
        {"start": 0.0, "end": round(kept[-1][1] + 60.0, 3)},
    ]
    played, notes = apply(kept, candidate)
    if notes or played == kept:
        return notes or ["teaser não muda nada — cold open ignorado"]

    plan["sequence"] = candidate
    plan["cold_open"] = {"start": start, "end": end, "reason": teaser.get("reason")}
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return [f"cold open {start:.1f}–{end:.1f}s ({_total(_clip(kept, start, end)):.1f}s): {teaser.get('reason') or ''}"]


if __name__ == "__main__":
    import sys

    cmd, ws_arg = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("", "")
    if cmd == "wants-cold-open":
        sys.exit(0 if wants_cold_open(ws_arg) else 1)
    if cmd == "cold-open":
        for note in merge_cold_open(ws_arg):
            print(f"[cold-open] {note}")
        sys.exit(0)
    print("usage: python -m auto_edit.sequence wants-cold-open|cold-open <workspace>", file=sys.stderr)
    sys.exit(2)
