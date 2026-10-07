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
