"""Legenda (.srt) de vídeo long, a partir da transcrição pós-corte.

O short já sai com legenda queimada (captioner, blocos curtos estilo CapCut).
O long não tem nenhuma — e uma faixa de legenda no YouTube ajuda quem assiste
sem som e a busca. Aqui as palavras viram legendas no formato de sempre:
até 2 linhas de ~42 caracteres, até ~6s cada, quebrando em pausa e pontuação.
O tempo das palavras é o do vídeo editado, então bate com o publicado.
"""
from __future__ import annotations

import json
from pathlib import Path

LINE_CHARS = 42
MAX_CHARS = LINE_CHARS * 2 - 6  # slack: words rarely split into two exact halves
MAX_SECONDS = 6.0
PAUSE = 0.7  # a gap this long between words starts a new caption
MIN_SECONDS = 1.0  # short captions are held a bit longer when there's room


def _words(transcript: dict) -> list[tuple[float, float, str]]:
    out = []
    for w in transcript.get("words") or []:
        try:
            start, end, text = float(w["start"]), float(w["end"]), str(w["word"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and end >= start:
            out.append((start, end, text))
    return sorted(out)


def group(transcript: dict) -> list[dict]:
    """Captions as [{start, end, text}] with the text already split in lines."""
    captions: list[dict] = []
    current: list[tuple[float, float, str]] = []

    def flush() -> None:
        if current:
            captions.append({
                "start": current[0][0],
                "end": current[-1][1],
                "text": _wrap(" ".join(t for _, _, t in current)),
            })
            current.clear()

    for word in _words(transcript):
        if current:
            text = " ".join(t for _, _, t in current)
            gap = word[0] - current[-1][1]
            too_long = len(text) + 1 + len(word[2]) > MAX_CHARS
            too_slow = word[1] - current[0][0] > MAX_SECONDS
            sentence_end = text[-1] in ".?!" and len(text) > LINE_CHARS / 2
            if gap > PAUSE or too_long or too_slow or sentence_end:
                flush()
        current.append(word)
    flush()

    # Hold a short caption on screen a little longer, never into the next one.
    for cap, nxt in zip(captions, captions[1:] + [None]):
        if cap["end"] - cap["start"] < MIN_SECONDS:
            limit = nxt["start"] - 0.05 if nxt else cap["start"] + MIN_SECONDS
            cap["end"] = max(cap["end"], min(cap["start"] + MIN_SECONDS, limit))
    return captions


def _wrap(text: str) -> str:
    """Two lines when the caption doesn't fit in one, split where the longer
    line is shortest (balanced, and never one line when two are needed)."""
    if len(text) <= LINE_CHARS:
        return text
    words = text.split()
    best, best_len = text, len(text)
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        longest = max(len(a), len(b))
        if longest < best_len:
            best, best_len = f"{a}\n{b}", longest
    return best


def _stamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(captions: list[dict]) -> str:
    blocks = [
        f"{i}\n{_stamp(c['start'])} --> {_stamp(c['end'])}\n{c['text']}\n"
        for i, c in enumerate(captions, start=1)
    ]
    return "\n".join(blocks)


def write_for_workspace(workspace: Path, dest: Path) -> Path | None:
    """`dest` from the workspace's post-cut transcript; None when there is none."""
    try:
        transcript = json.loads((Path(workspace) / "post_cut_transcription.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    captions = group(transcript)
    if not captions:
        return None
    dest.write_text(to_srt(captions), encoding="utf-8")
    return dest
