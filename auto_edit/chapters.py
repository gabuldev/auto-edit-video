"""Capítulos do YouTube (timestamps na descrição) para vídeos long.

O agente `metadata` propõe `chapters: [{start, title}]` em segundos do vídeo
editado. Aqui eles são forçados às regras do YouTube — senão o YouTube
simplesmente não mostra capítulo nenhum, sem erro:

- o primeiro começa em 0:00;
- pelo menos 3 capítulos;
- cada um com pelo menos 10 segundos;
- em ordem crescente.

`python -m auto_edit.chapters <workspace>` normaliza o `metadata.json` no
lugar (roda logo depois do agente, no stage metadata). Nunca falha o stage:
capítulo inválido some, com o motivo no log.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_CHAPTERS = 3
MIN_LENGTH = 10.0
TITLE_MAX = 100
HEADER = "Capítulos:"


def normalize(chapters, duration: float | None = None) -> tuple[list[dict], list[str]]:
    """Capítulos válidos pro YouTube + o que foi descartado e por quê.

    Devolve `[]` quando não sobra o mínimo de 3 — capítulos pela metade não
    aparecem no YouTube, então é melhor não mandar nada.
    """
    notes: list[str] = []
    if not isinstance(chapters, list):
        return [], ["chapters não é uma lista"] if chapters else []

    parsed: list[dict] = []
    for i, raw in enumerate(chapters, start=1):
        try:
            start = float(raw["start"])
            title = " ".join(str(raw["title"]).split())
        except (KeyError, TypeError, ValueError):
            notes.append(f"capítulo {i}: sem start/title válidos")
            continue
        if not title:
            notes.append(f"capítulo {i}: título vazio")
            continue
        if start < 0 or (duration and start >= duration - MIN_LENGTH):
            notes.append(f"capítulo {i} ({title}): começa fora do vídeo")
            continue
        parsed.append({"start": start, "title": title[:TITLE_MAX]})

    parsed.sort(key=lambda c: c["start"])
    if parsed:
        parsed[0]["start"] = 0.0  # o YouTube exige 0:00 no primeiro

    kept: list[dict] = []
    for ch in parsed:
        if kept and ch["start"] - kept[-1]["start"] < MIN_LENGTH:
            notes.append(f"{ch['title']}: menos de {MIN_LENGTH:.0f}s depois do anterior")
            continue
        kept.append({"start": round(ch["start"]), "title": ch["title"]})

    if len(kept) < MIN_CHAPTERS:
        if kept:
            notes.append(f"só {len(kept)} capítulo(s) válidos — o YouTube pede {MIN_CHAPTERS}")
        return [], notes
    return kept, notes


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_block(chapters: list[dict]) -> str:
    """O bloco que vai na descrição: `0:00 Título` por linha."""
    if not chapters:
        return ""
    return "\n".join([HEADER] + [f"{stamp(c['start'])} {c['title']}" for c in chapters])


def description_with_chapters(description: str, chapters: list[dict]) -> str:
    """Descrição + bloco de capítulos (uma vez só, mesmo se chamado de novo)."""
    description = (description or "").rstrip()
    block = format_block(chapters)
    if not block or HEADER in description:
        return description
    return f"{description}\n\n{block}" if description else block


def apply(workspace: Path) -> list[str]:
    """Normaliza `metadata.json["chapters"]` no lugar. Devolve as notas."""
    meta_path = workspace / "metadata.json"
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(metadata, dict) or "chapters" not in metadata:
        return []

    duration = None
    try:
        post_cut = json.loads((workspace / "post_cut_transcription.json").read_text(encoding="utf-8"))
        duration = float(post_cut.get("duration") or 0) or None
    except (OSError, ValueError, TypeError):
        pass

    kept, notes = normalize(metadata.get("chapters"), duration)
    metadata["chapters"] = kept
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return notes


if __name__ == "__main__":
    ws = Path(sys.argv[1])
    for note in apply(ws):
        print(f"[chapters] descartado — {note}")
    try:
        n = len(json.loads((ws / "metadata.json").read_text(encoding="utf-8")).get("chapters") or [])
    except (OSError, ValueError):
        n = 0
    print(f"[chapters] {n} capítulo(s)")
