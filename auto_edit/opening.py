"""A abertura do vídeo editado: o que é dito nos primeiros segundos e quanto
disso é preâmbulo.

Quem sai cedo sai na abertura. No vídeo "AutoEdit agora tem interface gráfica"
a interface só apareceu aos 0:55, depois de "fala galera", "para quem não me
conhece" e "deixa só virar a câmera" — tempo médio assistido de 1:10.

Isto não decide nada sozinho: só mede. O relatório entra no prompt do
evaluator (que devolve pro `plan` quando a abertura enrola) e no dry-run.
"""
from __future__ import annotations

import re
import unicodedata

WINDOW = 60.0  # seconds of the edited video that count as "the opening"
PREAMBLE_BUDGET = 15.0  # seconds of preamble before the promise/payoff

# Phrases that almost never carry the video's promise. Accent- and
# case-insensitive. A greeting alone is fine; a run of these is the problem.
PREAMBLE = {
    "saudação": [
        r"\bfala (galera|pessoal|gente|turma)\b", r"\b(e ai|oi|ola),? (galera|pessoal|gente)\b",
        r"\bsejam bem[- ]vindos?\b", r"\bhey (guys|everyone)\b", r"\bwhat'?s up\b",
    ],
    "apresentação": [
        r"\bpara quem nao me conhece\b", r"\bpra quem nao me conhece\b", r"\bmeu nome e\b",
        r"\beu sou o\b", r"\bse voce (e novo|ainda nao me conhece)\b", r"\bfor those who don'?t know me\b",
        r"\bmy name is\b",
    ],
    "anúncio do vídeo": [
        r"\bno video de hoje\b", r"\bnesse video (eu )?(vou|vamos|a gente vai)\b",
        r"\bhoje (eu )?(vou|vamos|a gente vai) (falar|mostrar|trazer)\b",
        r"\btem (algumas )?coisas? importantes? que (a gente|eu) (precisa|preciso) falar\b",
        r"\bin today'?s video\b",
    ],
    "bora lá": [r"\b(bora|vamos) la\b", r"\bsem mais delongas\b", r"\blet'?s (get started|dive in|go)\b"],
    "logística de gravação": [
        r"\bdeixa (eu |so )?(virar|ajustar|arrumar|mudar) a camera\b", r"\b(virar|ajustar) a camera\b",
        r"\bdeixa eu (so )?(pegar|abrir|ligar)\b", r"\bperai\b", r"\bum segundo\b",
    ],
    "pedido de inscrição": [r"\bse inscrev", r"\bdeixa (o |aquele |seu )?like\b", r"\bativa o sininho\b", r"\bsubscribe\b"],
}
_COMPILED = {kind: [re.compile(p) for p in pats] for kind, pats in PREAMBLE.items()}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def preamble_kind(text: str) -> str | None:
    folded = _fold(text)
    for kind, patterns in _COMPILED.items():
        if any(p.search(folded) for p in patterns):
            return kind
    return None


def report(transcript: dict, window: float = WINDOW) -> dict:
    """Lines in the first `window` seconds, which of them read as preamble,
    and how many seconds of the opening go to preamble before anything else."""
    lines = []
    for seg in transcript.get("segments") or []:
        try:
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start >= window:
            break
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append({"start": start, "end": min(end, window), "text": text, "preamble": preamble_kind(text)})

    preamble_seconds = sum(ln["end"] - ln["start"] for ln in lines if ln["preamble"])
    # The last preamble line in the window: where the opening really starts.
    last = max((ln["end"] for ln in lines if ln["preamble"]), default=0.0)
    return {
        "window": window,
        "lines": lines,
        "preamble_seconds": round(preamble_seconds, 1),
        "preamble_until": round(last, 1),
        "too_slow": last > PREAMBLE_BUDGET,
    }


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def format_report(rep: dict) -> str:
    """Text block for prompts and the dry-run."""
    if not rep["lines"]:
        return "(nenhuma fala nos primeiros segundos)"
    out = []
    for ln in rep["lines"]:
        flag = f"  ← preâmbulo ({ln['preamble']})" if ln["preamble"] else ""
        out.append(f"[{_mmss(ln['start'])}] {ln['text']}{flag}")
    summary = (
        f"Preâmbulo até {_mmss(rep['preamble_until'])} ({rep['preamble_seconds']:.0f}s marcados nos "
        f"primeiros {rep['window']:.0f}s)."
    )
    if rep["too_slow"]:
        summary += f" Passa do limite de {PREAMBLE_BUDGET:.0f}s antes da promessa do vídeo."
    return "\n".join(out + ["", summary])


def for_workspace(workspace) -> dict | None:
    """The opening of the edited video, or of the planned edit when it was
    not rendered yet (dry-run): planned kept segments applied to the source."""
    import json
    from pathlib import Path

    from auto_edit import postcut

    ws = Path(workspace)
    try:
        return report(json.loads((ws / "post_cut_transcription.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    try:
        transcription = json.loads((ws / "transcription.json").read_text(encoding="utf-8"))
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(plan, dict) or not isinstance(transcription, dict):
        return None
    kept = sorted(
        (float(s["start"]), float(s["end"]))
        for s in plan.get("kept_segments") or []
        if float(s["end"]) > float(s["start"])
    )
    return report(postcut.remap(transcription, kept)) if kept else None


if __name__ == "__main__":
    import sys

    rep = for_workspace(sys.argv[1])
    if rep is not None:
        print("[opening] Abertura do vídeo editado:")
        for line in format_report(rep).splitlines():
            print(f"[opening]   {line}" if line else "[opening]")
