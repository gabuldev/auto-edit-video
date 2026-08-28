"""Shorts derivados de um vídeo long já editado.

Um short derivado é um pipeline `short` normal cujo vídeo original é o
`edited_video.mp4` do long e cuja transcrição é o
`post_cut_transcription.json` do long. Os dois vivem no mesmo timeline
pós-corte, então executor, captioner, metadata e thumbnailer rodam sem
alteração.
"""
from __future__ import annotations

CLIPS_PLAN_NAME = "clips_plan.json"
DEFAULT_MAX_DURATION = 90.0
MIN_DURATION = 5.0


class ShortsError(RuntimeError):
    """Erro de uso do comando `auto-edit shorts`."""


def validate_clips(
    clips: list[dict],
    source_duration: float,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> tuple[list[dict], list[str]]:
    """Separa os clipes utilizáveis dos rejeitados.

    Um clipe ruim não derruba os outros: ele vira uma linha em `rejected`
    com o índice que o usuário vê na tabela (base 1) e o motivo.
    """
    valid: list[dict] = []
    rejected: list[str] = []

    for i, raw in enumerate(clips, start=1):
        try:
            start = float(raw.get("start"))
            end = float(raw.get("end"))
        except (TypeError, ValueError):
            rejected.append(f"{i}: start/end não são números")
            continue

        if end <= start:
            rejected.append(f"{i}: end ({end:.2f}s) não é maior que start ({start:.2f}s)")
            continue
        if start < 0 or end > source_duration:
            rejected.append(
                f"{i}: janela {start:.2f}s-{end:.2f}s fora do vídeo (0-{source_duration:.2f}s)"
            )
            continue

        duration = end - start
        if duration > max_duration:
            rejected.append(f"{i}: {duration:.1f}s passa do máximo de {max_duration:.0f}s")
            continue
        if duration < MIN_DURATION:
            rejected.append(f"{i}: {duration:.1f}s abaixo do mínimo de {MIN_DURATION:.0f}s")
            continue

        valid.append({**raw, "start": start, "end": end})

    return valid, rejected


def parse_pick(raw: str, count: int) -> list[int]:
    """Converte "1,3" em índices base 0, ordenados e sem duplicatas."""
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        raise ShortsError("--pick vazio. Informe os números da tabela, ex: --pick 1,3")

    picked: set[int] = set()
    for token in tokens:
        try:
            number = int(token)
        except ValueError:
            raise ShortsError(f"--pick: '{token}' não é um número") from None
        if number < 1 or number > count:
            raise ShortsError(f"--pick: {number} fora da faixa. Válidos: 1-{count}")
        picked.add(number - 1)

    return sorted(picked)


def _word_bounds(word: dict) -> tuple[float, float] | None:
    try:
        return float(word["start"]), float(word["end"])
    except (KeyError, TypeError, ValueError):
        return None


def snap_clip_to_words(
    start: float, end: float, words: list[dict]
) -> tuple[float, float]:
    """Encaixa a janela do clipe em fronteiras de palavra.

    O agente coloca limites alguns milissegundos dentro da palavra falada, o
    que corta a sílaba na entrada ou na saída do short. Puxamos o início pra
    frente até o começo de uma palavra e o fim pra trás até o fim de uma
    palavra — nunca alargando a janela.
    """
    inside = [
        bounds
        for bounds in (_word_bounds(w) for w in words)
        if bounds is not None and bounds[0] >= start and bounds[1] <= end
    ]
    if not inside:
        return start, end

    return inside[0][0], inside[-1][1]
