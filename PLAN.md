# Plano de Robustez do Pipeline de Edição

## Contexto

Melhorias de robustez no pipeline de edição de vídeo `auto-edit-video`, organizadas em 4 fases independentes e executáveis em sessões separadas.

---

## Phase 0: Referências de Código (leitura obrigatória antes de cada fase)

Antes de implementar qualquer fase, o agente executor **deve ler** os arquivos listados naquela fase. As assinaturas e implementações abaixo são a fonte da verdade para edição cirúrgica.

### Assinaturas críticas já mapeadas

**executor.py**
- `_build_keep_intervals(plan, duration)` → lines 44–63
- `_build_filter(intervals)` → lines 107–116
- `_run_ffmpeg_cuts(video, intervals, output)` → lines 119–147
- Codec: `h264_videotoolbox` em `_run_ffmpeg_cuts` (line 125)
- Constante: `END_PADDING` (line 18), `FILTER_SCRIPT_THRESHOLD = 100` (line 19)

**captioner.py**
- `caption(workspace)` → line 51
- `_transcribe(video, model_name, language)` → line 100
- `_group_words(words)` → line 138
- Re-transcription call: inside `caption()`, calls `_transcribe(edited_video, ...)` then saves `post_cut_transcription.json` (lines ~60–81)

**overlayer.py**
- `_remap(original_ts, kept)` → lines 117–126 (lógica de remapeamento de timestamps)
- `_build_kept_intervals(reviewed_plan, pipeline)` → line 109
- Codec: `h264_videotoolbox` em `_run_ffmpeg_overlay` (line 212)

**pipeline.py**
- `set_stage_status(workspace, stage, status)` → lines 73–94
- `save(workspace, pipeline)` → line 67
- Stage `"failed"` path: sets `failed_at` timestamp but **não salva stderr** (line 90)

**ralph.sh**
- LLM call: `claude -p "$(cat "$prompt_file")" >"$output_file" 2>&1` (lines 160–164)
- Cursor call: `_run_cursor_print "$prompt_file" "$output_file"` (line 169)
- `_call_llm()` loop sem timeout → lines 176–212
- `fail_stage()` helper → line 96

---

## Phase 1 — executor.py: Validação de Schema + Filtro de Intervalos Vazios

**Escopo:** `tools/executor.py`

**Problema 1 — Sem validação do cut plan:**
O executor confia cegamente no JSON do LLM. Se `kept_segments` tiver bounds inválidos (ex: `end > duration`, `start < 0`, `start >= end`), o FFmpeg crasha sem mensagem clara.

**Problema 2 — Intervalos < 1 frame quebram concat:**
O filtro `concat=n=N:v=1:a=1` requer exatamente N inputs com frames. Um intervalo de < 33ms (1 frame a 30fps) produz 0 frames e o concat falha silenciosamente.

### Tarefas

**1.1 — Adicionar `_validate_plan()` antes de `_build_keep_intervals()`**

Ler: `tools/executor.py` lines 22–63 (função `execute` e `_build_keep_intervals`)

Implementar função de validação **após** o load do `reviewed_plan.json` e **antes** de chamar `_build_keep_intervals()`:

```python
def _validate_plan(plan: dict, duration: float) -> None:
    """Raise ValueError with a clear message if the cut plan has invalid bounds."""
    segments = plan.get("kept_segments", [])
    cuts = plan.get("cuts", [])

    if not segments and not cuts:
        raise ValueError("reviewed_plan.json has neither kept_segments nor cuts")

    for i, seg in enumerate(segments):
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"kept_segments[{i}] missing/invalid start or end: {e}") from e

        if start < 0:
            raise ValueError(f"kept_segments[{i}] start={start} is negative")
        if end > duration + 1.0:  # 1s tolerance for rounding
            raise ValueError(
                f"kept_segments[{i}] end={end:.3f} exceeds video duration {duration:.3f}"
            )
        if start >= end:
            raise ValueError(
                f"kept_segments[{i}] start={start:.3f} >= end={end:.3f} (empty interval)"
            )

    for i, cut in enumerate(cuts):
        try:
            start = float(cut["start"])
            end = float(cut["end"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"cuts[{i}] missing/invalid start or end: {e}") from e

        if start >= end:
            raise ValueError(f"cuts[{i}] start={start:.3f} >= end={end:.3f}")
```

Inserir chamada em `execute()` logo após carregar `reviewed_plan`:

```python
duration = _get_duration(video)
_validate_plan(reviewed_plan, duration)           # <-- nova linha
intervals = _build_keep_intervals(reviewed_plan, duration)
```

**1.2 — Filtrar intervalos muito curtos em `_build_keep_intervals()`**

Após o `_merge_intervals()`, adicionar filtro antes do return:

```python
MIN_INTERVAL_DURATION = 1.0 / 30  # 1 frame at 30fps ≈ 0.033s

# filter out sub-frame intervals that would produce 0 frames in concat
filtered = [(s, e) for s, e in merged if (e - s) >= MIN_INTERVAL_DURATION]
if not filtered:
    raise RuntimeError("All kept segments are shorter than 1 frame — nothing to output")

return filtered
```

Adicionar constante `MIN_INTERVAL_DURATION = 1.0 / 30` no topo do arquivo junto com `END_PADDING`.

### Verificação

```bash
# Teste: passar um JSON com end > duration
echo '{"kept_segments": [{"start": 0, "end": 9999, "summary": "test"}]}' \
  > workspace/test_video/reviewed_plan.json
python tools/executor.py workspace/test_video
# Deve imprimir: ValueError: kept_segments[0] end=9999 exceeds...

# Teste: intervalo vazio
echo '{"kept_segments": [{"start": 5.0, "end": 5.01, "summary": "tiny"}]}' \
  > workspace/test_video/reviewed_plan.json
python tools/executor.py workspace/test_video
# Deve imprimir: RuntimeError: All kept segments are shorter than 1 frame
```

### Anti-patterns

- NÃO usar `assert` — usar `raise ValueError`/`RuntimeError` com mensagens descritivas
- NÃO modificar `_build_filter()` — a filtragem acontece em `_build_keep_intervals()`
- NÃO alterar `END_PADDING` behavior — o filtro de duração mínima se aplica APÓS o padding

---

## Phase 2 — executor.py + overlayer.py: Cadeia de Fallback de Codec

**Escopo:** `tools/executor.py`, `tools/overlayer.py`

**Problema:**
`h264_videotoolbox` é exclusivo do macOS (Apple VideoToolbox). Em Linux/Windows o pipeline falha com erro obscuro do FFmpeg. Ambos os arquivos usam o codec hardcoded.

### Tarefas

**2.1 — Criar `_get_video_codec()` em executor.py**

Adicionar função que testa disponibilidade dos codecs em ordem de preferência:

```python
_CODEC_PREFERENCE = [
    ("h264_videotoolbox", ["-q:v", "50"]),
    ("libx264",           ["-crf", "23", "-preset", "fast"]),
    ("libx265",           ["-crf", "28", "-preset", "fast"]),
]

def _get_video_codec() -> tuple[str, list[str]]:
    """Return (codec_name, extra_flags) for the best available H.264/H.265 encoder."""
    for codec, flags in _CODEC_PREFERENCE:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True
        )
        if codec in result.stdout:
            return codec, flags
    # Fallback to default (let FFmpeg choose)
    return "libx264", ["-crf", "23", "-preset", "fast"]
```

**2.2 — Usar `_get_video_codec()` em `_run_ffmpeg_cuts()`**

Substituir as linhas hardcoded:
```python
# ANTES (line 125):
"-c:v", "h264_videotoolbox", "-q:v", "50",

# DEPOIS:
codec, codec_flags = _get_video_codec()
...
"-c:v", codec, *codec_flags,
```

Construção do comando deve usar `*codec_flags` para unpacking dos flags variáveis.

**2.3 — Replicar em overlayer.py**

O `overlayer.py` tem o mesmo codec hardcoded em `_run_ffmpeg_overlay()` (line 212):
```python
"-c:v", "h264_videotoolbox", "-q:v", "50",
```

Duas opções:
- **Preferido**: Copiar `_CODEC_PREFERENCE` e `_get_video_codec()` para `overlayer.py` (os arquivos são self-contained por design)
- Alternativa: mover para um `tools/ffmpeg_utils.py` compartilhado (somente se já houver mais de 2 arquivos usando)

Como só são 2 arquivos, **copiar a função** preserva o design self-contained atual.

### Verificação

```bash
# Verificar que o codec detectado é logado
python tools/executor.py workspace/algum_video/
# Deve incluir na saída FFmpeg: "encoder: h264_videotoolbox" ou "encoder: libx264"

# Simular fallback: renomear temporariamente o codec no _CODEC_PREFERENCE e verificar que cai para libx264
```

### Anti-patterns

- NÃO fazer subprocess para cada frame — `_get_video_codec()` é chamado uma vez por execução
- NÃO usar `shell=True` no subprocess de detecção
- NÃO remover `-q:v 50` do `h264_videotoolbox` — é necessário para qualidade aceitável nesse encoder

---

## Phase 3 — ralph.sh + pipeline.py: Timeout LLM + Persistência de Erros

**Escopo:** `ralph.sh`, `auto_edit/pipeline.py`

Dois problemas relacionados à infraestrutura do pipeline:

**Problema A — Sem timeout nos agentes LLM:**
`claude -p "$(cat prompt)"` pode travar indefinidamente. O pipeline inteiro fica bloqueado sem feedback.

**Problema B — Erros se perdem:**
Quando `fail_stage()` é chamado, o `set_stage_status(stage, "failed")` só salva `failed_at`. O stderr do LLM ou da ferramenta Python vai para o terminal mas não é persistido no `pipeline.json`.

### Tarefas

**3.1 — Adicionar timeout na chamada LLM em ralph.sh**

Localizar `_run_llm_print_backend()` (lines 154–174) e envolver a chamada com `timeout`:

```bash
# ANTES:
claude -p "$(cat "$prompt_file")" >"$output_file" 2>&1

# DEPOIS:
LLM_TIMEOUT="${AUTO_EDIT_LLM_TIMEOUT:-600}"  # default 10 minutos
timeout "$LLM_TIMEOUT" claude -p "$(cat "$prompt_file")" >"$output_file" 2>&1
```

Adicionar `LLM_TIMEOUT` como variável configurável no topo do script (próximo às outras variáveis de ambiente, ~line 35):

```bash
LLM_TIMEOUT="${AUTO_EDIT_LLM_TIMEOUT:-600}"
```

Tratar o exit code 124 do `timeout` (significa que o processo foi killed):

```bash
_run_llm_print_backend() {
    local backend="$1" prompt_file="$2" output_file="$3"
    local exit_code
    case "$backend" in
        claude)
            if [ -n "${AUTO_EDIT_CLAUDE_MODEL:-}" ]; then
                timeout "$LLM_TIMEOUT" claude --model "$AUTO_EDIT_CLAUDE_MODEL" \
                    -p "$(cat "$prompt_file")" >"$output_file" 2>&1
            else
                timeout "$LLM_TIMEOUT" claude -p "$(cat "$prompt_file")" >"$output_file" 2>&1
            fi
            exit_code=$?
            if [ "$exit_code" -eq 124 ]; then
                log "ERROR: LLM '$backend' timed out after ${LLM_TIMEOUT}s"
                return 1
            fi
            return "$exit_code"
            ;;
        cursor)
            timeout "$LLM_TIMEOUT" sh -c '_run_cursor_print "$@"' _ "$prompt_file" "$output_file"
            ;;
    esac
}
```

**3.2 — Persistir erro no pipeline.json via pipeline.py**

Modificar `set_stage_status()` em `pipeline.py` para aceitar campo `error_message` opcional:

```python
def set_stage_status(workspace: Path, stage: str, status: str, error: str | None = None) -> dict:
    pipeline = load(workspace)
    pipeline["stages"][stage]["status"] = status

    if status == "complete":
        pipeline["stages"][stage]["completed_at"] = _now()
        # ... advance logic (sem mudança) ...

    elif status == "failed":
        pipeline["stages"][stage]["failed_at"] = _now()
        if error:
            pipeline["stages"][stage]["error"] = error[:2000]  # cap at 2000 chars

    save(workspace, pipeline)
    return pipeline
```

**3.3 — Capturar stderr dos tools Python em ralph.sh e persistir**

A função `run_python_tool()` (line 108) atualmente não captura stderr. Modificar para:

```bash
run_python_tool() {
    local stage="$1" script="$2"
    log "Running tool: $stage"
    python "$WORKSPACE/pipeline.py" set-stage-status "$WORKSPACE" "$stage" running

    local tool_output
    tool_output=$("$PYTHON" "$script" "$WORKSPACE" 2>&1)
    local exit_code=$?

    if [ "$exit_code" -ne 0 ]; then
        # Persist error in pipeline.json
        "$PYTHON" -c "
import sys, json
from pathlib import Path
ws = Path('$WORKSPACE')
p = json.loads((ws / 'pipeline.json').read_text())
p['stages']['$stage']['error'] = sys.argv[1][:2000]
p['stages']['$stage']['status'] = 'failed'
p['stages']['$stage']['failed_at'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
(ws / 'pipeline.json').write_text(json.dumps(p, indent=2))
" "$tool_output"
        fail_stage "$stage" "$tool_output"
    fi

    advance_stage "$stage"
}
```

Nota: a persistência pode ser feita chamando diretamente `auto_edit.pipeline` com o novo parâmetro `--error`:

```bash
"$PYTHON" -m auto_edit.pipeline failed "$WORKSPACE" "$stage" "$tool_output"
```

Isso requer adicionar o subcommand `failed` ao CLI de `pipeline.py` (linha ~230).

### Verificação

```bash
# Testar timeout: definir AUTO_EDIT_LLM_TIMEOUT=5 (5 segundos)
AUTO_EDIT_LLM_TIMEOUT=5 ./ralph.sh workspace/test_video/
# Deve logar: [ralph] ERROR: LLM 'claude' timed out after 5s

# Testar persistência: provocar falha no executor (JSON inválido)
# Depois verificar pipeline.json:
cat workspace/test_video/pipeline.json | python -m json.tool | grep -A3 '"execute"'
# Deve mostrar: "error": "..." com mensagem
```

### Anti-patterns

- NÃO usar `timeout` do GNU coreutils para cursor (é um wrapper Python) — usar `timeout` no shell externo
- NÃO truncar o erro para menos de 1000 chars — mensagens de stack trace precisam de espaço
- NÃO modificar a assinatura pública de `save()` — manter `error` como kwarg opcional

---

## Phase 4 — captioner.py: Eliminar Re-transcrição com Whisper

**Escopo:** `tools/captioner.py`, lendo lógica de `tools/overlayer.py`

**Problema:**
O `captioner.py` re-transcreve o vídeo editado com Whisper para obter timestamps pós-corte. Isso:
- Demora (Whisper no vídeo inteiro novamente)
- Duplica trabalho — o `overlayer.py` já resolve esse problema via `_remap()`

**Solução:**
Reutilizar a transcrição original (`transcription.json`) e remapear os timestamps usando os intervalos de corte (`kept_segments` do `reviewed_plan.json`), exatamente como `overlayer.py` faz.

### Tarefas

**4.1 — Copiar `_remap()` para captioner.py**

A função é self-contained e simples. Copiar verbatim de `overlayer.py` lines 117–126:

```python
def _remap(original_ts: float, kept: list[tuple[float, float]]) -> float | None:
    """Map an original-video timestamp to a post-cut timestamp. Returns None if in a cut."""
    accumulated = 0.0
    for start, end in kept:
        if original_ts < start:
            return None  # falls in a removed section
        if original_ts <= end:
            return accumulated + (original_ts - start)
        accumulated += end - start
    return None
```

**4.2 — Adicionar `_build_kept_intervals()` em captioner.py**

Mesma lógica de `overlayer.py` line 109:

```python
def _build_kept_intervals(reviewed_plan: dict, duration: float) -> list[tuple[float, float]]:
    """Build (start, end) kept intervals from reviewed_plan, inverting cuts if needed."""
    segs = reviewed_plan.get("kept_segments", [])
    if segs:
        return [(float(s["start"]), float(s["end"])) for s in segs]
    # Invert cuts
    cuts = sorted(reviewed_plan.get("cuts", []), key=lambda c: c["start"])
    intervals = []
    prev = 0.0
    for cut in cuts:
        s = float(cut["start"])
        if s > prev:
            intervals.append((prev, s))
        prev = float(cut["end"])
    if prev < duration:
        intervals.append((prev, duration))
    return intervals
```

**4.3 — Adicionar `_remap_words()` para transformar a transcrição original**

```python
def _remap_words(
    words: list[dict],
    segments: list[dict],
    kept: list[tuple[float, float]],
) -> tuple[list[dict], list[dict]]:
    """
    Remap word and segment timestamps from original video to post-cut timeline.
    Words/segments that fall entirely within cut regions are dropped.
    Words that straddle a cut boundary are dropped (conservative).
    """
    remapped_words = []
    for word in words:
        new_start = _remap(float(word["start"]), kept)
        new_end = _remap(float(word["end"]), kept)
        if new_start is None or new_end is None:
            continue  # word is in a cut region
        remapped_words.append({**word, "start": new_start, "end": new_end})

    remapped_segs = []
    for seg in segments:
        new_start = _remap(float(seg["start"]), kept)
        new_end = _remap(float(seg["end"]), kept)
        if new_start is None or new_end is None:
            continue
        remapped_segs.append({**seg, "start": new_start, "end": new_end})

    return remapped_words, remapped_segs
```

**4.4 — Modificar `caption()` para usar remapeamento em vez de re-transcrição**

Localizar o bloco em `caption()` (lines ~60–81) que chama `_transcribe(edited_video, ...)` e substituir:

```python
# ANTES (resumido):
words, segments = _transcribe(edited_video, model_name, language)
post_cut = {"words": words, "segments": segments, ...}
(workspace / "post_cut_transcription.json").write_text(...)

# DEPOIS:
reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
original_transcription = json.loads((workspace / "transcription.json").read_text())
duration = _get_duration(edited_video)
kept = _build_kept_intervals(reviewed_plan, duration)

orig_words = original_transcription.get("words", [])
orig_segments = original_transcription.get("segments", [])
words, segments = _remap_words(orig_words, orig_segments, kept)

post_cut = {
    "duration": duration,
    "words": words,
    "segments": segments,
    "language": original_transcription.get("language", language),
}
(workspace / "post_cut_transcription.json").write_text(
    json.dumps(post_cut, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
```

A função `_transcribe()` pode ser mantida no arquivo (ainda é usada como fallback ou pode ser removida se confirmado desnecessário).

**4.5 — Fallback: se `reviewed_plan.json` ausente, manter comportamento original**

Envolver a lógica nova em try/except para não quebrar casos edge:

```python
try:
    reviewed_plan = json.loads((workspace / "reviewed_plan.json").read_text())
    # ... remap logic ...
except (FileNotFoundError, KeyError, json.JSONDecodeError):
    # Fallback: re-transcribe (old behavior)
    words, segments = _transcribe(edited_video, model_name, language)
    # ... save post_cut_transcription.json ...
```

### Verificação

```bash
# Processar um vídeo completo e verificar que o stage "caption" não roda Whisper novamente
# (não deve aparecer "Loading Whisper model" no log do captioner)

# Verificar que post_cut_transcription.json tem timestamps corretos:
cat workspace/video/post_cut_transcription.json | python -c "
import json, sys
data = json.load(sys.stdin)
words = data['words']
print(f'Total words: {len(words)}')
print(f'First word: {words[0][\"word\"]} at {words[0][\"start\"]:.3f}s')
print(f'Duration: {data[\"duration\"]:.3f}s')
"
# First word deve ter start ≈ 0.0 (o vídeo editado começa do início)
```

### Anti-patterns

- NÃO remover `_transcribe()` do arquivo sem confirmar que nenhum outro código chama
- NÃO assumir que todos os words têm `start`/`end` — filtrar dicts sem esses campos
- NÃO usar os timestamps do `kept_segments` diretamente sem compensar pelo `END_PADDING` — os intervalos em `reviewed_plan` são pré-padding; o `_build_kept_intervals` deve usar os bounds originais para remapeamento (diferente do `executor.py` que aplica padding)

---

## Ordem de Execução Recomendada

| Fase | Dependências | Risco | Estimativa |
|------|-------------|-------|------------|
| Phase 1 | Nenhuma | Baixo | Pequena |
| Phase 2 | Nenhuma | Baixo | Pequena |
| Phase 3 | Nenhuma | Médio (modifica ralph.sh) | Média |
| Phase 4 | Phase 1 (usa intervalos) | Médio | Média |

Fases 1 e 2 podem ser executadas em qualquer ordem ou paralelamente.
Phase 4 deve ser após Phase 1 (a validação do plan garante que os intervalos usados para remapping são válidos).

---

## Verificação Final (Após todas as fases)

```bash
# Processar um vídeo curto de ponta a ponta e verificar:
auto-edit short assets/test_video.mp4

# Checar pipeline.json do workspace:
cat workspace/test_video/pipeline.json | python -m json.tool

# Deve ter:
# - stages.execute.status = "complete" (sem crash por schema)
# - stages.caption.status = "complete" (sem re-transcrição Whisper)
# - Nenhum stage com status "failed" sem campo "error"

# Em macOS: verificar codec usado
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name \
  output/test_video_final.mp4
# Deve retornar: h264 (via h264_videotoolbox ou libx264)
```
