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

import re

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


def _flags(ws) -> tuple[bool, bool]:
    """(cold_open, reorder) asked for this workspace (pipeline.json or env)."""
    import os

    pipeline = _read(ws / "pipeline.json") or {}

    def env(name: str) -> bool:
        return os.environ.get(name, "").lower() in ("1", "true", "yes")

    return (
        bool(pipeline.get("cold_open")) or env("AUTO_EDIT_COLD_OPEN"),
        bool(pipeline.get("reorder")) or env("AUTO_EDIT_REORDER"),
    )


# Evaluator feedback that blames the cold open: the next iteration goes without
# one instead of picking (and failing) the same kind of teaser again.
_TEASER_COMPLAINT = re.compile(r"teaser|cold open|cold-open|abertura com (um )?trecho", re.I)


def blamed_by_evaluator(workspace) -> bool:
    from pathlib import Path

    pipeline = _read(Path(workspace) / "pipeline.json") or {}
    feedback = pipeline.get("evaluator_feedback") or ""
    return pipeline.get("iteration", 1) > 1 and bool(_TEASER_COMPLAINT.search(feedback))


def wants_cold_open(workspace) -> bool:
    """Cold open or reordering was asked for and the plan has no sequence yet
    — a hand-made one is never overwritten."""
    from pathlib import Path

    ws = Path(workspace)
    plan = _read(ws / "reviewed_plan.json") or {}
    return any(_flags(ws)) and not plan.get("sequence")


def snap_to_sentences(start: float, end: float, segments: list[dict]) -> tuple[float, float] | None:
    """Widen a teaser to the whole transcript lines it touches, so it never
    starts or ends mid-sentence. Lines are dropped from the end while it is
    longer than TEASER_MAX; None when not even one line fits."""
    lines = []
    for seg in segments or []:
        try:
            s, e = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e > start + 0.05 and s < end - 0.05:
            lines.append((s, e))
    if not lines:
        return start, end
    lines.sort()
    while lines and lines[-1][1] - lines[0][0] > TEASER_MAX:
        lines.pop()
    if not lines:
        return None
    return lines[0][0], lines[-1][1]


def normalize_blocks(blocks, kept: list[Interval]) -> list[dict]:
    """The agent's blocks, in its order, turned into a partition of the video.

    Boundaries from the agent are approximate. Sorted by start, each block is
    stretched to meet the next one (no gaps, no overlap), the first starts at
    0 and the last runs past the end — so `apply`'s "cover everything kept,
    never overlap" rules hold by construction and nothing kept gets lost to a
    sloppy boundary. The playback order the agent chose is kept.
    """
    items = []
    for i, b in enumerate(blocks or []):
        try:
            items.append({"order": i, "start": float(b["start"]), "end": float(b["end"])})
        except (KeyError, TypeError, ValueError):
            return []
    if len(items) < 2:
        return []
    by_time = sorted(items, key=lambda it: it["start"])
    by_time[0]["start"] = 0.0
    for prev, nxt in zip(by_time, by_time[1:]):
        prev["end"] = nxt["start"]
    by_time[-1]["end"] = kept[-1][1] + 60.0 if kept else by_time[-1]["end"]
    ordered = sorted(by_time, key=lambda it: it["order"])
    return [{"start": round(it["start"], 3), "end": round(it["end"], 3)} for it in ordered if it["end"] > it["start"]]


def merge_cold_open(workspace) -> list[str]:
    """Turn the agent's answer into the plan's `sequence`. Returns log notes.

    - teaser (when cold open was asked): played first, again in its place;
      refused inside a cut, in the first 15s kept, or outside the length limits;
    - blocks (when reordering was asked): the new order of the whole video,
      normalized into a partition and used only if it really reorders.
    Writes nothing when neither survives.
    """
    import json
    from pathlib import Path

    ws = Path(workspace)
    want_teaser, want_reorder = _flags(ws)
    answer = _read(ws / COLD_OPEN_FILE) or {}
    if not isinstance(answer, dict):
        return ["resposta do agente não é um objeto — sem cold open/reordenação"]

    plan_path = ws / "reviewed_plan.json"
    plan = _read(plan_path) or {}
    kept = kept_intervals(plan)
    if not kept:
        return ["plano sem trechos mantidos — nada a ordenar"]
    everything = [{"start": 0.0, "end": round(kept[-1][1] + 60.0, 3)}]
    notes: list[str] = []

    teaser_item = None
    if want_teaser and blamed_by_evaluator(ws):
        want_teaser = False
        notes.append("cold open pulado nesta volta: o evaluator reclamou do teaser da anterior")
    teaser = answer.get("teaser") if want_teaser else None
    if want_teaser and not teaser:
        notes.append(f"agente não escolheu cold open: {answer.get('reason') or 'sem motivo'}")
    if teaser:
        try:
            start, end = float(teaser["start"]), float(teaser["end"])
        except (KeyError, TypeError, ValueError):
            notes.append("teaser sem start/end válidos — cold open ignorado")
            start = end = None
        if start is not None:
            transcription = _read(ws / "transcription.json") or {}
            snapped = snap_to_sentences(start, end, transcription.get("segments") or [])
            if snapped is None:
                notes.append("teaser não cabe em frases inteiras de até 15s — cold open ignorado")
                start = end = None
            else:
                start, end = snapped
        if start is not None:
            # A sentence the plan cut through would play as a fragment.
            if _total(_clip(kept, start, end)) < 0.9 * (end - start):
                notes.append(f"teaser {start:.1f}–{end:.1f}s atravessa um corte (frase pela metade) — cold open ignorado")
                start = end = None
        if start is not None:
            before = _total(_clip(kept, 0.0, start))
            if before < MIN_KEPT_BEFORE_TEASER:
                notes.append(f"teaser em {start:.1f}s está na abertura ({before:.1f}s depois do início) — cold open ignorado")
            else:
                played, problems = apply(kept, [{"start": start, "end": end, "role": "teaser"}, *everything])
                if problems or played == kept:
                    notes += problems or ["teaser não muda nada — cold open ignorado"]
                else:
                    teaser_item = {"start": round(start, 3), "end": round(end, 3), "role": "teaser"}

    body = everything
    reordered = False
    if want_reorder:
        blocks = normalize_blocks(answer.get("blocks"), kept)
        if not blocks:
            notes.append(f"agente manteve a ordem: {answer.get('order_reason') or 'sem blocos'}")
        else:
            played, problems = apply(kept, blocks)
            if problems:
                notes += [f"reordenação ignorada: {p}" for p in problems]
            elif played == apply(kept, everything)[0]:
                notes.append("blocos na mesma ordem do vídeo — nada a reordenar")
            else:
                body, reordered = blocks, True

    if teaser_item and reordered:
        first = body[0]
        if first["start"] <= teaser_item["start"] and teaser_item["end"] <= first["end"]:
            # The new order already opens on that moment: a teaser would play it
            # twice within seconds.
            notes.append("teaser descartado: a reordenação já abre o vídeo nesse trecho")
            teaser_item = None

    if not teaser_item and not reordered:
        return notes
    plan["sequence"] = ([teaser_item] if teaser_item else []) + body
    if teaser_item:
        plan["cold_open"] = {"start": teaser_item["start"], "end": teaser_item["end"], "reason": teaser.get("reason")}
        notes.append(f"cold open {teaser_item['start']:.1f}–{teaser_item['end']:.1f}s: {teaser.get('reason') or ''}")
    if reordered:
        plan["reorder"] = {"blocks": len(body), "reason": answer.get("order_reason")}
        notes.append(f"reordenado em {len(body)} blocos: {answer.get('order_reason') or ''}")
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return notes


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
