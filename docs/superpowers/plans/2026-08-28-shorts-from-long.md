# Shorts derivados de um long — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar `auto-edit shorts <video>`, que propõe trechos do vídeo long já editado e transforma os escolhidos em shorts completos.

**Architecture:** Um short derivado é um pipeline `short` normal cujo `video_path` é o `edited_video.mp4` do long e cuja `transcription.json` é o `post_cut_transcription.json` do long — ambos no mesmo timeline. O comando novo gera um `clips_plan.json` via agente, e para cada clipe escolhido monta um workspace derivado e chama `ralph.sh` a partir do stage `execute`. Executor, captioner, metadata e thumbnailer não mudam.

**Tech Stack:** Python 3.11+, Typer, pytest, bash (ralph.sh), FFmpeg.

**Spec:** `docs/superpowers/specs/2026-08-27-shorts-from-long-design.md`

## Global Constraints

- Python >= 3.11. Type hints com `from __future__ import annotations`.
- Testes: `.venv/bin/python -m pytest tests/ -v`. Nenhum teste novo pode invocar FFmpeg nem um LLM.
- Lint: `.venv/bin/python -m ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`.
- Validar bash: `bash -n ralph.sh`.
- Nunca commitar direto na `main`. O trabalho todo sai na branch `feat/shorts-from-long`, que já existe e já tem a spec commitada.
- Mensagens ao usuário em português, sem acentuação obrigatória em código; texto de UI pode ter acento.
- Duração máxima default de um clipe: `90.0` segundos. Mínima: `5.0` segundos.
- Nome do arquivo do plano de clipes: `clips_plan.json`, sempre no workspace do long.

## Desvio consciente da spec

A spec diz que o plano sintético passa por `auto_edit.snap`. Na implementação isso vira uma função local (`snap_clip_to_words`, Task 2). Motivo: `snap.snap_plan` opera sobre a lista de `cuts` e reconstrói `kept_segments` a partir dela; com um plano de um único trecho mantido e `cuts` vazio, a reconstrução devolveria o vídeo inteiro. A função local resolve o problema real (não cortar no meio de uma palavra) de forma determinística e testável.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `auto_edit/shorts.py` (novo) | Toda a lógica sem I/O de rede: validar clipes, parsear `--pick`, encaixar fronteiras em palavras, semear o workspace derivado, resolver caminhos |
| `agents/clipper.md` (novo) | Prompt do agente que escolhe os candidatos |
| `auto_edit/runner.py` (modificar) | Ramo `clip` em `build_prompt` |
| `ralph.sh` (modificar) | Entrada `--agent` que roda um agente avulso sem tocar em `pipeline.json` |
| `auto_edit/cli.py` (modificar) | Comando `shorts` |
| `tests/test_shorts.py` (novo) | Testes de tudo em `auto_edit/shorts.py` |
| `tests/test_runner_prompt.py` (modificar) | Teste do ramo `clip` |
| `CLAUDE.md` (modificar) | Documentar o comando |

**O reframe 9:16 não precisa de código novo.** `tools/executor.py:_resolve_reframe` já converte pra 1080x1920 sempre que `type == "short"` e a proporção da fonte difere de 0.5625 — o que é exatamente o caso de um long 16:9. Nenhuma task mexe nisso.

---

### Task 1: Validação de clipes e parsing do `--pick`

**Files:**
- Create: `auto_edit/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `ShortsError(RuntimeError)`
  - `CLIPS_PLAN_NAME: str = "clips_plan.json"`
  - `DEFAULT_MAX_DURATION: float = 90.0`
  - `MIN_DURATION: float = 5.0`
  - `validate_clips(clips: list[dict], source_duration: float, max_duration: float = DEFAULT_MAX_DURATION) -> tuple[list[dict], list[str]]` — devolve `(clipes_validos, motivos_de_rejeicao)`. Cada clipe válido sai com `start` e `end` como `float`. Os motivos vêm formatados com o índice humano (base 1).
  - `parse_pick(raw: str, count: int) -> list[int]` — converte `"1,3"` em `[0, 2]` (índices base 0), ordenados e sem duplicatas. Levanta `ShortsError` em entrada inválida.

- [ ] **Step 1: Escrever os testes que falham**

```python
"""Tests for auto_edit/shorts.py."""
import pytest

from auto_edit.shorts import (
    DEFAULT_MAX_DURATION,
    ShortsError,
    parse_pick,
    validate_clips,
)


def clip(start, end, hook="gancho"):
    return {"start": start, "end": end, "hook": hook, "reason": "r", "score": 7}


class TestValidateClips:
    def test_keeps_a_well_formed_clip(self):
        valid, rejected = validate_clips([clip(10.0, 40.0)], source_duration=378.0)
        assert len(valid) == 1
        assert rejected == []
        assert valid[0]["start"] == 10.0

    def test_rejects_end_before_start(self):
        valid, rejected = validate_clips([clip(40.0, 10.0)], source_duration=378.0)
        assert valid == []
        assert "1:" in rejected[0]

    def test_rejects_clip_past_the_end_of_the_video(self):
        valid, rejected = validate_clips([clip(360.0, 400.0)], source_duration=378.0)
        assert valid == []

    def test_rejects_clip_longer_than_the_cap(self):
        valid, rejected = validate_clips(
            [clip(0.0, 120.0)], source_duration=378.0, max_duration=DEFAULT_MAX_DURATION
        )
        assert valid == []
        assert "90" in rejected[0]

    def test_rejects_clip_shorter_than_the_floor(self):
        valid, rejected = validate_clips([clip(10.0, 12.0)], source_duration=378.0)
        assert valid == []

    def test_rejects_non_numeric_boundaries(self):
        valid, rejected = validate_clips(
            [{"start": "abc", "end": 40.0, "hook": "h"}], source_duration=378.0
        )
        assert valid == []
        assert rejected

    def test_one_bad_clip_does_not_drop_the_good_ones(self):
        valid, rejected = validate_clips(
            [clip(10.0, 40.0), clip(40.0, 10.0), clip(50.0, 90.0)],
            source_duration=378.0,
        )
        assert len(valid) == 2
        assert len(rejected) == 1

    def test_empty_list_is_empty_not_an_error(self):
        assert validate_clips([], source_duration=378.0) == ([], [])


class TestParsePick:
    def test_single_index(self):
        assert parse_pick("1", count=3) == [0]

    def test_comma_separated_is_sorted_and_deduped(self):
        assert parse_pick("3,1,3", count=3) == [0, 2]

    def test_tolerates_spaces(self):
        assert parse_pick(" 1 , 2 ", count=3) == [0, 1]

    def test_zero_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("0", count=3)

    def test_index_past_the_end_is_rejected_and_lists_the_valid_range(self):
        with pytest.raises(ShortsError, match="1-3"):
            parse_pick("9", count=3)

    def test_non_numeric_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("a", count=3)

    def test_empty_string_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("", count=3)
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'auto_edit.shorts'`

- [ ] **Step 3: Implementar o mínimo**

```python
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
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -v`
Expected: PASS (15 testes)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/shorts.py tests/test_shorts.py
git commit -m "feat: validacao de clipes e parsing do --pick pros shorts derivados"
```

---

### Task 2: Encaixar as fronteiras do clipe em limites de palavra

**Files:**
- Modify: `auto_edit/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: Task 1 (`auto_edit/shorts.py` já existe).
- Produces:
  - `snap_clip_to_words(start: float, end: float, words: list[dict]) -> tuple[float, float]` — move `start` para o início da primeira palavra que começa em `start` ou depois, e `end` para o fim da última palavra que termina em `end` ou antes. Sem palavras dentro da janela, devolve `(start, end)` inalterado. Cada palavra é um dict com `start` e `end` em segundos, como no `post_cut_transcription.json`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_shorts.py`:

```python
from auto_edit.shorts import snap_clip_to_words

WORDS = [
    {"word": "Galera,", "start": 0.0, "end": 0.62},
    {"word": "a", "start": 0.68, "end": 0.86},
    {"word": "saga", "start": 0.86, "end": 1.26},
    {"word": "continua.", "start": 2.44, "end": 3.10},
    {"word": "Entao", "start": 4.00, "end": 4.40},
]


class TestSnapClipToWords:
    def test_start_moves_forward_to_the_next_word_onset(self):
        start, _ = snap_clip_to_words(0.70, 3.10, WORDS)
        assert start == 0.86

    def test_end_moves_back_to_the_previous_word_tail(self):
        _, end = snap_clip_to_words(0.0, 2.90, WORDS)
        assert end == 1.26

    def test_boundaries_already_on_word_edges_are_untouched(self):
        assert snap_clip_to_words(0.86, 3.10, WORDS) == (0.86, 3.10)

    def test_window_with_no_words_is_left_alone(self):
        assert snap_clip_to_words(10.0, 20.0, WORDS) == (10.0, 20.0)

    def test_empty_word_list_is_left_alone(self):
        assert snap_clip_to_words(1.0, 2.0, []) == (1.0, 2.0)

    def test_words_with_bad_timestamps_are_ignored(self):
        words = [{"word": "x", "start": None, "end": 1.0}, *WORDS]
        assert snap_clip_to_words(0.70, 3.10, words)[0] == 0.86
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -k Snap -v`
Expected: FAIL com `ImportError: cannot import name 'snap_clip_to_words'`

- [ ] **Step 3: Implementar o mínimo**

Acrescente a `auto_edit/shorts.py`:

```python
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
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -v`
Expected: PASS (21 testes)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/shorts.py tests/test_shorts.py
git commit -m "feat: encaixa fronteiras do clipe em limites de palavra"
```

---

### Task 3: Resolver caminhos e semear o workspace derivado

**Files:**
- Modify: `auto_edit/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: Task 1, Task 2.
- Produces:
  - `long_source_video(long_ws: Path) -> Path` — `<long_ws>/edited_video.mp4`. Levanta `ShortsError` se não existir, mandando rodar `auto-edit resume <video> --from execute`.
  - `require_finished_long(long_ws: Path) -> dict` — carrega o `pipeline.json` do long. Levanta `ShortsError` se o arquivo não existir, se `type != "long"`, ou se `current_stage != "done"`.
  - `seed_short_workspace(long_ws: Path, long_pipeline: dict, clip: dict, index: int) -> Path` — cria `<long_ws>.parent/<stem>_short<index>/` com `pipeline.json`, `transcription.json` e `reviewed_plan.json`, e devolve o caminho. `index` é base 1.

O `pipeline.json` derivado tem `type: "short"`, `video_path` apontando pro `edited_video.mp4` do long, `video_name` igual a `<stem_do_long>_short<index>`, `current_stage: "execute"`, e os stages `extract`, `plan`, `review`, `overlay`, `evaluate` com `status: "skip"`. `video_name` **precisa** ser explícito: `pipeline.init` o derivaria de `video_path.stem`, o que daria `edited_video` pra todo short e faria um sobrescrever o outro no `output/`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_shorts.py`:

```python
import json
from pathlib import Path

from auto_edit.shorts import (
    long_source_video,
    require_finished_long,
    seed_short_workspace,
)

LONG_PIPELINE = {
    "video_path": "/videos/DJI_0128.MP4",
    "video_name": "DJI_0128",
    "type": "long",
    "context": "resolvi o problema do bmcu",
    "language": "pt",
    "whisper_model": "small",
    "current_stage": "done",
    "stages": {},
}

POST_CUT = {
    "duration": 378.75,
    "segments": [],
    "words": [{"word": "Galera,", "start": 0.0, "end": 0.62}],
}


def make_long_ws(tmp_path: Path, pipeline=None, with_video=True) -> Path:
    ws = tmp_path / "workspace" / "DJI_0128"
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps(pipeline or LONG_PIPELINE))
    (ws / "post_cut_transcription.json").write_text(json.dumps(POST_CUT))
    if with_video:
        (ws / "edited_video.mp4").write_bytes(b"fake")
    return ws


class TestRequireFinishedLong:
    def test_returns_the_pipeline_when_the_long_is_done(self, tmp_path):
        ws = make_long_ws(tmp_path)
        assert require_finished_long(ws)["video_name"] == "DJI_0128"

    def test_missing_pipeline_json_points_at_the_long_command(self, tmp_path):
        ws = tmp_path / "workspace" / "nada"
        ws.mkdir(parents=True)
        with pytest.raises(ShortsError, match="auto-edit long"):
            require_finished_long(ws)

    def test_unfinished_pipeline_names_the_current_stage(self, tmp_path):
        ws = make_long_ws(tmp_path, {**LONG_PIPELINE, "current_stage": "execute"})
        with pytest.raises(ShortsError, match="execute"):
            require_finished_long(ws)

    def test_a_short_workspace_is_refused(self, tmp_path):
        ws = make_long_ws(tmp_path, {**LONG_PIPELINE, "type": "short"})
        with pytest.raises(ShortsError, match="long"):
            require_finished_long(ws)


class TestLongSourceVideo:
    def test_returns_the_edited_video(self, tmp_path):
        ws = make_long_ws(tmp_path)
        assert long_source_video(ws).name == "edited_video.mp4"

    def test_missing_edited_video_points_at_resume(self, tmp_path):
        ws = make_long_ws(tmp_path, with_video=False)
        with pytest.raises(ShortsError, match="--from execute"):
            long_source_video(ws)


class TestSeedShortWorkspace:
    def seed(self, tmp_path, index=1, start=10.0, end=40.0):
        long_ws = make_long_ws(tmp_path)
        clip = {"start": start, "end": end, "hook": "a impressora parava"}
        return long_ws, seed_short_workspace(long_ws, LONG_PIPELINE, clip, index)

    def test_creates_a_sibling_workspace_named_after_the_clip(self, tmp_path):
        long_ws, ws = self.seed(tmp_path, index=2)
        assert ws.name == "DJI_0128_short2"
        assert ws.parent == long_ws.parent

    def test_video_name_is_unique_per_clip(self, tmp_path):
        _, ws = self.seed(tmp_path, index=3)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["video_name"] == "DJI_0128_short3"

    def test_source_is_the_edited_long(self, tmp_path):
        long_ws, ws = self.seed(tmp_path)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["video_path"] == str((long_ws / "edited_video.mp4").resolve())

    def test_type_is_short_and_starts_at_execute(self, tmp_path):
        _, ws = self.seed(tmp_path)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["type"] == "short"
        assert pipeline["current_stage"] == "execute"

    def test_agent_stages_are_skipped(self, tmp_path):
        _, ws = self.seed(tmp_path)
        stages = json.loads((ws / "pipeline.json").read_text())["stages"]
        for stage in ("extract", "plan", "review", "overlay", "evaluate"):
            assert stages[stage]["status"] == "skip", stage
        for stage in ("execute", "caption", "metadata", "thumbnail"):
            assert stages[stage]["status"] == "pending", stage

    def test_transcription_is_the_long_post_cut(self, tmp_path):
        _, ws = self.seed(tmp_path)
        assert json.loads((ws / "transcription.json").read_text()) == POST_CUT

    def test_reviewed_plan_keeps_only_the_clip_window(self, tmp_path):
        _, ws = self.seed(tmp_path, start=10.0, end=40.0)
        plan = json.loads((ws / "reviewed_plan.json").read_text())
        assert plan["approved"] is True
        assert plan["cuts"] == []
        assert len(plan["kept_segments"]) == 1
        assert plan["kept_segments"][0]["start"] == 10.0
        assert plan["kept_segments"][0]["end"] == 40.0

    def test_clip_window_is_snapped_to_word_boundaries(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        (long_ws / "post_cut_transcription.json").write_text(json.dumps({
            "duration": 378.75,
            "segments": [],
            "words": [
                {"word": "a", "start": 10.5, "end": 10.9},
                {"word": "b", "start": 11.0, "end": 39.0},
            ],
        }))
        ws = seed_short_workspace(
            long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 1
        )
        kept = json.loads((ws / "reviewed_plan.json").read_text())["kept_segments"][0]
        assert (kept["start"], kept["end"]) == (10.5, 39.0)

    def test_context_carries_the_long_context_and_the_hook(self, tmp_path):
        _, ws = self.seed(tmp_path)
        context = json.loads((ws / "pipeline.json").read_text())["context"]
        assert "bmcu" in context
        assert "a impressora parava" in context

    def test_reseeding_replaces_the_previous_plan(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        seed_short_workspace(long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 1)
        ws = seed_short_workspace(long_ws, LONG_PIPELINE, {"start": 50.0, "end": 80.0, "hook": "h"}, 1)
        kept = json.loads((ws / "reviewed_plan.json").read_text())["kept_segments"][0]
        assert kept["start"] == 50.0
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -k "Require or Source or Seed" -v`
Expected: FAIL com `ImportError: cannot import name 'long_source_video'`

- [ ] **Step 3: Implementar o mínimo**

Acrescente a `auto_edit/shorts.py` (o `import json` e o `from pathlib import Path` vão no topo do arquivo, junto do `from __future__ import annotations`):

```python
import json
from datetime import datetime, timezone
from pathlib import Path

SOURCE_VIDEO_NAME = "edited_video.mp4"
POST_CUT_NAME = "post_cut_transcription.json"

# Stages que não fazem sentido num workspace derivado. `evaluate` entra na
# lista porque `pipeline.loop_back` volta pro stage `plan` incondicionalmente,
# mesmo com ele marcado `skip` — num derivado isso re-planejaria a partir da
# transcrição inteira do long e destruiria a janela do clipe.
SKIPPED_STAGES = ("extract", "plan", "review", "overlay", "evaluate")
ACTIVE_STAGES = ("execute", "caption", "metadata", "thumbnail")


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
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -v`
Expected: PASS (36 testes)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/shorts.py tests/test_shorts.py
git commit -m "feat: semeia o workspace de um short derivado do long"
```

---

### Task 4: Prompt do clipper e o ramo `clip` do build_prompt

**Files:**
- Create: `agents/clipper.md`
- Modify: `auto_edit/runner.py` (função `build_prompt`)
- Test: `tests/test_runner_prompt.py`

**Interfaces:**
- Consumes: nada de Tasks anteriores.
- Produces: `build_prompt("clip", workspace, Path("agents/clipper.md"))` devolve um prompt contendo o texto do `clipper.md`, o contexto do vídeo, a duração da fonte e a transcrição pós-corte compactada.

- [ ] **Step 1: Escrever o teste que falha**

Abra `tests/test_runner_prompt.py` e acrescente o teste abaixo. Confira que o arquivo já importa `json` e `build_prompt` — se não importar, acrescente `import json` e `from auto_edit.runner import build_prompt` no topo.

```python
def test_clip_prompt_carries_the_post_cut_transcription(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({
        "video_path": "/v/DJI.MP4",
        "video_name": "DJI",
        "type": "long",
        "context": "review do bmcu",
        "current_stage": "done",
        "stages": {},
    }))
    (ws / "post_cut_transcription.json").write_text(json.dumps({
        "duration": 378.75,
        "segments": [{"start": 0.0, "end": 2.8, "text": "a saga continua"}],
        "words": [{"word": "saga", "start": 1.0, "end": 1.4}],
    }))
    prompt_file = tmp_path / "clipper.md"
    prompt_file.write_text("# Clipper Agent\n")

    prompt = build_prompt("clip", ws, prompt_file)

    assert "# Clipper Agent" in prompt
    assert "review do bmcu" in prompt
    assert "378.75" in prompt
    assert "a saga continua" in prompt
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/bin/python -m pytest tests/test_runner_prompt.py -k clip -v`
Expected: FAIL — o prompt sai sem a transcrição, porque `build_prompt` não conhece o stage `clip`

- [ ] **Step 3: Escrever o prompt do agente**

Crie `agents/clipper.md`:

```markdown
# Clipper Agent

Você é um editor de social media. Recebe a transcrição de um vídeo long **já editado** (timestamps em segundos, no timeline do vídeo editado) e escolhe os trechos que funcionariam sozinhos como Reels/Shorts.

Você **não** corta nada. Sua saída é uma lista de candidatos que um humano vai revisar.

## O que faz um bom candidato

- **Auto-contido**: faz sentido pra quem nunca viu o vídeo longo. Nada que dependa de "como eu falei ali atrás".
- **Gancho nos primeiros 3 segundos**: a primeira frase precisa dar um motivo pra continuar assistindo.
- **Uma ideia só**: um problema e sua solução, uma demonstração, uma opinião forte. Não um resumo do vídeo inteiro.
- **Fecha**: termina numa conclusão ou numa virada, não no meio de um raciocínio.

## Duração

Alvo de 20 a 60 segundos. Nunca passe de 90 segundos. Trechos abaixo de 5 segundos são inúteis.

## Quantos

Entre 0 e 5. **Zero é uma resposta legítima**: se o vídeo não tem nenhum momento que se sustente sozinho, devolva a lista vazia com um `notes` explicando. Não invente candidatos pra preencher cota.

Candidatos podem se sobrepor — o humano escolhe um dos dois.

## Fronteiras

Use os timestamps das palavras. Comece no início de uma palavra, termine no fim de uma palavra. Não corte no meio de uma frase.

## Saída

Responda **somente** com JSON válido, sem cercas de código, neste formato:

```json
{
  "source_duration": 378.75,
  "notes": "por que estes trechos, ou por que nenhum",
  "clips": [
    {
      "start": 0.0,
      "end": 42.3,
      "hook": "a frase de abertura do trecho, como ela é falada",
      "reason": "por que este trecho se sustenta sozinho",
      "score": 8,
      "self_contained": true
    }
  ]
}
```

`score` vai de 0 a 10 e serve pra ordenar os candidatos. `hook` é a frase de abertura real, não uma paráfrase — ela vira o contexto do short e alimenta o gerador de título.
```

- [ ] **Step 4: Adicionar o ramo `clip` em `build_prompt`**

Em `auto_edit/runner.py`, dentro de `build_prompt`, acrescente um ramo `elif stage == "clip":` junto dos outros ramos por stage:

```python
    elif stage == "clip":
        post_cut = _read_json(workspace / "post_cut_transcription.json")
        sections += [
            "\n## Video Information",
            f"- Context: {context or '(no context provided)'}",
            f"- Source duration: {post_cut.get('duration')}s (vídeo já editado)",
            "\n## Post-Cut Transcription",
            _compact_json(_slim_for_plan(post_cut)),
        ]
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_runner_prompt.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agents/clipper.md auto_edit/runner.py tests/test_runner_prompt.py
git commit -m "feat: prompt do clipper e ramo clip no build_prompt"
```

---

### Task 5: Entrada `--agent` no ralph.sh

**Files:**
- Modify: `ralph.sh`

**Interfaces:**
- Consumes: Task 4 (`agents/clipper.md`, ramo `clip` do `build_prompt`).
- Produces: `bash ralph.sh --agent <workspace> <stage> <output_file> <prompt_file>` roda um agente avulso e escreve o JSON validado em `<output_file>`, **sem** tocar em `pipeline.json`. Sai com código 0 em sucesso.

O `run_agent` existente marca o stage como `running` e chama `advance_stage` no fim — as duas coisas quebrariam no workspace do long, que não tem um stage `clip`. Por isso a entrada nova reusa só `_call_llm`.

- [ ] **Step 1: Adicionar a entrada, antes do laço principal**

Em `ralph.sh`, logo depois da definição de `run_agent` (por volta da linha 162), acrescente:

```bash
# Roda um agente avulso, fora da máquina de estados do pipeline.
# Usado por `auto-edit shorts`, que precisa do LLM mas não tem um stage
# correspondente em pipeline.json.
run_standalone_agent() {
    local stage="$1"
    local output_file="$2"
    local prompt_file="$3"

    log "Running standalone agent: $stage"

    local tmp_prompt="$WORKSPACE/.prompt_${stage}.txt"
    local tmp_output="$WORKSPACE/.output_${stage}.txt"

    $PYTHON "$SCRIPT_DIR/auto_edit/runner.py" build-prompt \
        "$stage" "$WORKSPACE" "$prompt_file" > "$tmp_prompt"

    _call_llm "$tmp_prompt" "$tmp_output" "$stage" "$output_file"

    rm -f "$tmp_prompt" "$tmp_output"
}
```

- [ ] **Step 2: Despachar a flag no topo do script**

O `WORKSPACE` hoje vem de `$1`. Troque o bloco de argumentos no topo (por volta da linha 19) por:

```bash
STANDALONE_STAGE=""
STANDALONE_OUTPUT=""
STANDALONE_PROMPT=""
if [ "${1:-}" = "--agent" ]; then
    WORKSPACE="${2:?Usage: ralph.sh --agent <workspace> <stage> <output_file> <prompt_file>}"
    STANDALONE_STAGE="${3:?missing stage}"
    STANDALONE_OUTPUT="${4:?missing output file}"
    STANDALONE_PROMPT="${5:?missing prompt file}"
else
    WORKSPACE="${1:?Usage: ralph.sh <workspace_dir>}"
fi
```

E logo antes do laço principal de stages, acrescente:

```bash
if [ -n "$STANDALONE_STAGE" ]; then
    run_standalone_agent "$STANDALONE_STAGE" "$STANDALONE_OUTPUT" "$STANDALONE_PROMPT"
    exit 0
fi
```

- [ ] **Step 3: Validar a sintaxe do bash**

Run: `bash -n ralph.sh`
Expected: sem saída (sintaxe ok)

- [ ] **Step 4: Confirmar que o modo normal não regrediu**

Run: `bash ralph.sh 2>&1 | head -3`
Expected: a mensagem de uso `Usage: ralph.sh <workspace_dir>`, não um erro de sintaxe

- [ ] **Step 5: Commit**

```bash
git add ralph.sh
git commit -m "feat: entrada --agent no ralph.sh pra rodar um agente avulso"
```

---

### Task 6: Comando `auto-edit shorts`

**Files:**
- Modify: `auto_edit/cli.py`
- Modify: `auto_edit/shorts.py`
- Modify: `CLAUDE.md`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `load_clips_plan(long_ws: Path, max_duration: float) -> tuple[list[dict], list[str]]` em `auto_edit/shorts.py` — lê o `clips_plan.json`, valida, devolve `(validos, rejeitados)`. Levanta `ShortsError` se o arquivo não existir, mandando rodar sem `--pick` primeiro.
  - `format_clips_table(clips: list[dict]) -> str` em `auto_edit/shorts.py` — a tabela em texto, uma linha por clipe, base 1.
  - Comando `shorts` em `auto_edit/cli.py`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_shorts.py`:

```python
from auto_edit.shorts import format_clips_table, load_clips_plan


class TestLoadClipsPlan:
    def test_reads_and_validates(self, tmp_path):
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "source_duration": 378.75,
            "clips": [
                {"start": 10.0, "end": 40.0, "hook": "h", "reason": "r", "score": 8},
                {"start": 400.0, "end": 430.0, "hook": "x", "reason": "r", "score": 5},
            ],
        }))
        valid, rejected = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert len(valid) == 1
        assert len(rejected) == 1

    def test_missing_plan_points_at_running_without_pick(self, tmp_path):
        ws = make_long_ws(tmp_path)
        with pytest.raises(ShortsError, match="--pick"):
            load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)

    def test_falls_back_to_the_transcription_duration(self, tmp_path):
        # O agente pode omitir source_duration; o post-cut tem a verdade.
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "clips": [{"start": 10.0, "end": 40.0, "hook": "h"}]
        }))
        valid, _ = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert len(valid) == 1


class TestFormatClipsTable:
    def test_numbers_the_clips_from_one(self):
        table = format_clips_table([
            {"start": 10.0, "end": 40.0, "hook": "gancho um", "reason": "r", "score": 8},
            {"start": 50.0, "end": 90.0, "hook": "gancho dois", "reason": "r", "score": 6},
        ])
        assert "1" in table and "2" in table
        assert "gancho um" in table

    def test_shows_the_duration(self):
        table = format_clips_table([
            {"start": 10.0, "end": 40.0, "hook": "h", "reason": "r", "score": 8}
        ])
        assert "30" in table

    def test_empty_list_says_so(self):
        assert "nenhum" in format_clips_table([]).lower()
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -k "LoadClips or FormatClips" -v`
Expected: FAIL com `ImportError: cannot import name 'format_clips_table'`

- [ ] **Step 3: Implementar as duas funções**

Acrescente a `auto_edit/shorts.py`:

```python
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
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_shorts.py -v`
Expected: PASS (42 testes)

- [ ] **Step 5: Escrever o comando na CLI**

Em `auto_edit/cli.py`, acrescente o comando. Siga o padrão dos comandos existentes (`console.print` com markup rich, `typer.Exit(1)` em erro). Ele precisa de `from auto_edit import shorts as sh` no topo, junto dos outros imports de `auto_edit`.

```python
@app.command()
def shorts(
    video: Path = typer.Argument(..., help="O mesmo vídeo que você passou pro `auto-edit long`"),
    pick: Optional[str] = typer.Option(None, "--pick", help="Quais candidatos cortar, ex: 1,3"),
    all_clips: bool = typer.Option(False, "--all", help="Corta todos os candidatos"),
    replan: bool = typer.Option(False, "--replan", help="Roda o clipper de novo por cima do plano atual"),
    max_dur: float = typer.Option(sh.DEFAULT_MAX_DURATION, "--max-dur", help="Duração máxima de um clipe, em segundos"),
    cli: Optional[str] = typer.Option(None, "--cli", help="CLI de agente: claude, cursor, agent"),
    cli_fallback: Optional[str] = typer.Option(None, "--cli-fallback", help="CLI de fallback"),
) -> None:
    """Propõe e corta shorts a partir de um vídeo long já editado."""
    long_ws = get_workspace(video)
    try:
        long_pipeline = sh.require_finished_long(long_ws)
        sh.long_source_video(long_ws)
    except sh.ShortsError as exc:
        console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(1) from None

    plan_path = long_ws / sh.CLIPS_PLAN_NAME
    if replan or not plan_path.exists():
        console.print("[cyan]Procurando candidatos a short...[/cyan]")
        primary, fb = _resolve_llm(cli, cli_fallback)
        env = os.environ.copy()
        env["AUTO_EDIT_REPO_ROOT"] = str(RALPH_SCRIPT.parent.resolve())
        env["PYTHON"] = sys.executable
        env["AUTO_EDIT_LLM"] = primary
        if fb:
            env["AUTO_EDIT_LLM_FALLBACK"] = fb
        else:
            env.pop("AUTO_EDIT_LLM_FALLBACK", None)
        result = subprocess.run(
            [
                "bash", str(RALPH_SCRIPT), "--agent", str(long_ws.resolve()),
                "clip", str(plan_path.resolve()),
                str(RALPH_SCRIPT.parent / "agents" / "clipper.md"),
            ],
            cwd=RALPH_SCRIPT.parent,
            env=env,
        )
        if result.returncode != 0:
            console.print("[red]O clipper falhou.[/red] Veja a saída acima.")
            raise typer.Exit(result.returncode)

    try:
        clips, rejected = sh.load_clips_plan(long_ws, max_duration=max_dur)
    except sh.ShortsError as exc:
        console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(1) from None

    for reason in rejected:
        console.print(f"[yellow]Candidato descartado —[/yellow] {reason}")

    console.print()
    console.print(sh.format_clips_table(clips))
    console.print()

    if not clips:
        raise typer.Exit(0)

    if all_clips:
        indices = list(range(len(clips)))
    elif pick:
        try:
            indices = sh.parse_pick(pick, len(clips))
        except sh.ShortsError as exc:
            console.print(f"[red]Erro:[/red] {exc}")
            raise typer.Exit(1) from None
    else:
        console.print(
            f"Pra cortar: [bold]auto-edit shorts {video} --pick 1[/bold] "
            "(ou --all pra todos)."
        )
        raise typer.Exit(0)

    primary, fb = _resolve_llm(cli, cli_fallback)
    for index in indices:
        clip = clips[index]
        number = index + 1
        console.print(f"\n[bold green]Short {number}[/bold green] — {clip.get('hook', '')}")
        ws = sh.seed_short_workspace(long_ws, long_pipeline, clip, number)
        console.print(f"[cyan]Workspace:[/cyan] {ws}")

        env = os.environ.copy()
        env["AUTO_EDIT_REPO_ROOT"] = str(RALPH_SCRIPT.parent.resolve())
        env["PYTHON"] = sys.executable
        env["AUTO_EDIT_LANGUAGE"] = long_pipeline.get("language", "pt")
        env["AUTO_EDIT_LLM"] = primary
        if fb:
            env["AUTO_EDIT_LLM_FALLBACK"] = fb
        else:
            env.pop("AUTO_EDIT_LLM_FALLBACK", None)

        result = subprocess.run(
            ["bash", str(RALPH_SCRIPT), str(ws.resolve())],
            cwd=RALPH_SCRIPT.parent,
            env=env,
        )
        if result.returncode != 0:
            console.print(f"[red]Short {number} falhou.[/red]")
            raise typer.Exit(result.returncode)

    console.print("\n[bold green]Pronto![/bold green] Shorts em [bold]output/[/bold]")
```

- [ ] **Step 6: Confirmar que o comando aparece e a suíte segue verde**

Run: `.venv/bin/python -m auto_edit shorts --help`
Expected: a ajuda do comando, com `--pick`, `--all`, `--replan`, `--max-dur`

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: todos passando

Run: `.venv/bin/python -m ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`
Expected: `All checks passed!`

- [ ] **Step 7: Documentar em CLAUDE.md**

Na seção "Quick Reference" do `CLAUDE.md`, depois do bloco de `batch`, acrescente:

```bash
# Shorts a partir de um long já editado
auto-edit shorts video.mp4              # propõe candidatos
auto-edit shorts video.mp4 --pick 1,3   # corta os escolhidos
```

E depois da seção "Pipeline", acrescente:

```markdown
### Shorts derivados

`auto-edit shorts <video>` roda depois que o `long` termina. O agente `clipper`
lê a transcrição pós-corte e propõe trechos auto-contidos; você escolhe com
`--pick`. Cada escolhido vira um workspace `<stem>_shortN/` cujo vídeo de
origem é o `edited_video.mp4` do long, e roda o pipeline `short` a partir do
`execute` (sem extract/plan/review/overlay/evaluate).
```

- [ ] **Step 8: Commit**

```bash
git add auto_edit/cli.py auto_edit/shorts.py tests/test_shorts.py CLAUDE.md
git commit -m "feat: comando auto-edit shorts"
```

---

## Verificação final (depois da Task 6)

- [ ] `.venv/bin/python -m pytest tests/ -q` — tudo verde
- [ ] `.venv/bin/python -m ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`
- [ ] `bash -n ralph.sh`
- [ ] Teste de ponta a ponta num long já finalizado: `auto-edit shorts <video>` lista candidatos; `--pick 1` produz `output/<stem>_short1_final.mp4` em 1080x1920 com legendas, e a duração do vídeo bate com a do áudio (a mesma checagem que pegou o bug de câmera lenta: `ffprobe -v error -show_entries stream=codec_type,r_frame_rate,duration -of csv=p=0 <final>`)
- [ ] Abrir PR pra `main` (nunca commitar direto na main)
