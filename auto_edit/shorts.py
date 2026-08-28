"""Shorts derivados de um vídeo long já editado.

Um short derivado é um pipeline `short` normal cujo vídeo original é o
`edited_video.mp4` do long e cuja transcrição é o
`post_cut_transcription.json` do long. Os dois vivem no mesmo timeline
pós-corte, então executor, captioner, metadata e thumbnailer rodam sem
alteração.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CLIPS_PLAN_NAME = "clips_plan.json"
DEFAULT_MAX_DURATION = 90.0
MIN_DURATION = 5.0
SOURCE_VIDEO_NAME = "edited_video.mp4"
POST_CUT_NAME = "post_cut_transcription.json"

# Stages que não fazem sentido num workspace derivado. `evaluate` entra na
# lista porque `pipeline.loop_back` volta pro stage `plan` incondicionalmente,
# mesmo com ele marcado `skip` — num derivado isso re-planejaria a partir da
# transcrição inteira do long e destruiria a janela do clipe.
SKIPPED_STAGES = ("extract", "plan", "review", "overlay", "evaluate")
ACTIVE_STAGES = ("execute", "caption", "metadata", "thumbnail")


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


def require_finished_long(long_ws: Path) -> dict:
    """Carrega o pipeline.json do long, exigindo que ele tenha terminado."""
    path = long_ws / "pipeline.json"
    if not path.exists():
        raise ShortsError(
            f"Nenhum workspace de long em {long_ws}. "
            "Rode `auto-edit long <video>` primeiro."
        )

    pipeline = json.loads(path.read_text(encoding="utf-8"))
    if pipeline.get("type") != "long":
        raise ShortsError(
            f"O workspace {long_ws.name} é do tipo '{pipeline.get('type')}'. "
            "`auto-edit shorts` só deriva de um vídeo long."
        )
    if pipeline.get("current_stage") != "done":
        raise ShortsError(
            f"O pipeline do long não terminou (stage atual: {pipeline.get('current_stage')}). "
            "Termine o long antes de extrair shorts."
        )
    return pipeline


def long_source_video(long_ws: Path) -> Path:
    """O vídeo de onde os shorts são cortados.

    É o `edited_video.mp4`, e não o `output/<stem>_final.mp4`: o final carrega
    o cover frame no início (~67ms), o que dessincronizaria todas as legendas.
    """
    path = long_ws / SOURCE_VIDEO_NAME
    if not path.exists():
        raise ShortsError(
            f"{SOURCE_VIDEO_NAME} não existe em {long_ws}. "
            "Rode `auto-edit resume <video> --from execute` pra reconstruí-lo."
        )
    return path


def seed_short_workspace(
    long_ws: Path, long_pipeline: dict, clip: dict, index: int
) -> Path:
    """Monta o workspace de um short derivado e devolve o caminho.

    O diretório é criado na mão, sem passar por `workspace.init_workspace`:
    aquelas funções derivam o nome do stem do arquivo de vídeo, que aqui é
    sempre `edited_video`, e os shorts colidiriam entre si.
    """
    post_cut = json.loads(
        (long_ws / POST_CUT_NAME).read_text(encoding="utf-8")
    )
    start, end = snap_clip_to_words(
        float(clip["start"]), float(clip["end"]), post_cut.get("words") or []
    )

    stem = long_pipeline["video_name"]
    name = f"{stem}_short{index}"
    ws = long_ws.parent / name
    ws.mkdir(parents=True, exist_ok=True)

    stages = {s: {"status": "skip"} for s in SKIPPED_STAGES}
    stages.update({s: {"status": "pending"} for s in ACTIVE_STAGES})

    hook = clip.get("hook", "")
    context = long_pipeline.get("context", "")
    pipeline = {
        "video_path": str(long_source_video(long_ws).resolve()),
        "video_name": name,
        "type": "short",
        "context": f"{context} — trecho: {hook}".strip(" —"),
        "whisper_model": long_pipeline.get("whisper_model", "small"),
        "language": long_pipeline.get("language", "pt"),
        "iteration": 1,
        "max_iterations": 1,
        "current_stage": "execute",
        "evaluator_feedback": None,
        "caption_style": long_pipeline.get("caption_style", {}),
        "plan_id": None,
        "stages": stages,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "derived_from": str(long_ws.resolve()),
    }
    (ws / "pipeline.json").write_text(
        json.dumps(pipeline, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ws / "transcription.json").write_text(
        json.dumps(post_cut, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ws / "reviewed_plan.json").write_text(
        json.dumps(
            {
                "cuts": [],
                "kept_segments": [{"start": start, "end": end, "summary": hook}],
                "approved": True,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ws


def load_clips_plan(
    long_ws: Path, max_duration: float = DEFAULT_MAX_DURATION
) -> tuple[list[dict], list[str]]:
    """Lê e valida o clips_plan.json do workspace do long."""
    path = long_ws / CLIPS_PLAN_NAME
    if not path.exists():
        raise ShortsError(
            f"Nenhum {CLIPS_PLAN_NAME} em {long_ws}. "
            "Rode `auto-edit shorts <video>` sem --pick pra gerar os candidatos."
        )

    plan = json.loads(path.read_text(encoding="utf-8"))
    duration = plan.get("source_duration")
    if not duration:
        post_cut = json.loads(
            (long_ws / POST_CUT_NAME).read_text(encoding="utf-8")
        )
        duration = float(post_cut.get("duration") or 0.0)

    return validate_clips(plan.get("clips") or [], float(duration), max_duration)


def _mmss(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def format_clips_table(clips: list[dict]) -> str:
    """Tabela de candidatos, numerada a partir de 1 — os números do --pick."""
    if not clips:
        return "Nenhum candidato a short neste vídeo."

    lines = [f"{'#':<3} {'JANELA':<16} {'DUR':>6}  {'NOTA':>4}  GANCHO"]
    for i, clip in enumerate(clips, start=1):
        start, end = float(clip["start"]), float(clip["end"])
        window = f"{_mmss(start)}-{_mmss(end)}"
        lines.append(
            f"{i:<3} {window:<16} {end - start:>5.0f}s  {clip.get('score', '-'):>4}  "
            f"{clip.get('hook', '')}"
        )
    return "\n".join(lines)
