# auto-edit-video

Pipeline de edição automatizada de vídeo usando IA. Transcreve, planeja cortes, executa, adiciona legendas e gera metadata — tudo via CLI.

## Quick Reference

```bash
# Editar short (vertical, com legendas)
auto-edit short video.mp4 --context "review de produto tech"

# Editar long (horizontal, sem legendas, com overlays)
auto-edit long video.mp4 --context "tutorial de Python"

# Batch (vários vídeos)
auto-edit batch upload/ --type short --context "vlogs de viagem"

# Shorts a partir de um long já editado
auto-edit shorts video.mp4              # propõe candidatos
auto-edit shorts video.mp4 --pick 1,3   # corta os escolhidos

# Status / Resume / Doctor
auto-edit status video.mp4
auto-edit resume video.mp4 --from plan
auto-edit doctor

# Plan (planejamento de conteúdo — semanal/mensal)
auto-edit plan new -w next -c "..." -s "..."
auto-edit plan show           # default: semana atual
auto-edit plan status         # progresso vs datas
auto-edit plan ingest --run   # parear pastas com slots e editar tudo
```

## Pipeline

```
extract → plan → review → execute → overlay → caption → evaluate → metadata → done
Whisper   Claude  Claude   FFmpeg   FFmpeg    FFmpeg    Claude     Claude
```

- **short**: pula overlay, faz caption (legendas estilo CapCut) — planner = `agents/planner.md` (limpeza)
- **long**: faz overlay, pula caption — planner = `agents/planner_long.md` (curadoria editorial: descarta blocos temáticos, define duração pela densidade do conteúdo, reporta `dropped_blocks`)

O resumo da curadoria aparece em `auto-edit status <video>` e no `--dry-run`.

Se o evaluator rejeitar, o pipeline volta ao `plan` com feedback (até 3 iterações).

### Shorts derivados

`auto-edit shorts <video>` roda depois que o `long` termina. O agente `clipper`
lê a transcrição pós-corte e propõe trechos auto-contidos; você escolhe com
`--pick`. Cada escolhido vira um workspace `<stem>_shortN/` cujo vídeo de
origem é o `edited_video.mp4` do long, e roda o pipeline `short` a partir do
`execute` (sem extract/plan/review/overlay/evaluate).

Um candidato é descartado (com o motivo, citando a posição dele no plano) se a
janela estiver fora do vídeo, se `end <= start`, se passar de `--max-dur`
(default 90s) ou se ficar **abaixo de 5s** (`shorts.MIN_DURATION`) — um trecho
mais curto que isso não vira short. A tabela sai ordenada por `score`
decrescente e marca os candidatos que se sobrepõem.

## Arquitetura

| Diretório | Conteúdo |
|-----------|----------|
| `auto_edit/` | CLI (typer), pipeline state machine, workspace manager |
| `tools/` | Scripts Python por stage (extractor, executor, captioner, overlayer) |
| `agents/` | Prompts para stages LLM (planner, reviewer, evaluator, metadata) |
| `ralph.sh` | Orquestrador bash que executa o pipeline stage-by-stage |
| `assets/` | Fontes, overlays, sons para composição de vídeo |

## Convenções

- Testes: `python -m pytest tests/ -v`
- Lint: `ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`
- Validar ralph.sh: `bash -n ralph.sh`
- **Nunca commitar direto na main** — sempre usar branches + PR (ver `/gitflow`)
- Entry point: `auto_edit.cli:app` (Typer)
- Python >= 3.11, FFmpeg obrigatório

## Variáveis de Ambiente

| Var | Default | Descrição |
|-----|---------|-----------|
| `AUTO_EDIT_LLM` | `claude` | CLI primário para agent stages (claude ou cursor) |
| `AUTO_EDIT_LLM_FALLBACK` | — | CLI fallback se primário falhar |
| `AUTO_EDIT_END_PADDING` | `0.2` | Segundos adicionados ao final de cada segmento mantido |
| `AUTO_EDIT_LANGUAGE` | `pt` | Idioma do áudio para transcrição |
| `AUTO_EDIT_HOME` | `~/.auto-edit` | Diretório de profile + plans (fora do repo) |
| `AUTO_EDIT_INBOX` | — | Pasta padrão pra `auto-edit plan ingest` |
| `AUTO_EDIT_FFMPEG` | — | ffmpeg com libass pro stage caption (se o do PATH não tiver o filtro `subtitles`) |
| `AUTO_EDIT_THUMB_TS` | — | Força o frame da thumbnail num timestamp (segundos), pulando a seleção automática |
| `AUTO_EDIT_ASSETS_OVERLAYS` | — | Pasta com os MP4s de overlay (`ctas.mp4`, `lowerthid_gabul.mp4`). Tem prioridade sobre `assets/overlays/`. Também via `--overlays-dir` no `long`/`apply-overlays` |
| `AUTO_EDIT_OVERLAYS_OPTIONAL` | — | `1` faz o stage `overlay` só avisar (em vez de falhar) quando um overlay planejado não é encontrado |
| `AUTO_EDIT_SEGMENT_THRESHOLD` | `12` | Acima de N segmentos, o `execute` corta um-a-um + concat (evita OOM do FFmpeg em vídeo longo/4K) |
| `GEMINI_API_KEY` | — | API key para correção de texto via Gemini |
| `AUTO_EDIT_YT_CLIENT_SECRET` | — | Caminho do JSON de OAuth client (Desktop) do Google Cloud, pro `auto-edit insights auth youtube` |
| `AUTO_EDIT_WORKSPACE` | `workspace` | Pasta raiz que guarda os workspaces por vídeo (CLI, MCP e motor headless) |

## Slash Commands Disponíveis

- `/edit-video` — Guia interativo para iniciar edição
- `/edit-status` — Dashboard de todos os pipelines
- `/edit-preview` — Preview textual dos cortes antes de executar
- `/review-cuts` — Revisar e ajustar plano de cortes
- `/fix-stage` — Diagnosticar e corrigir stage com falha
- `/gitflow` — Garante workflow com branches + PR

## MCP Server (Claude Code Extension)

Para usar o auto-edit como extensão do Claude Code:

```json
{
  "mcpServers": {
    "auto-edit-video": {
      "command": "auto-edit",
      "args": ["mcp-server"]
    }
  }
}
```

Isso expõe tools como `edit_short`, `edit_long`, `pipeline_status`, `resume_pipeline` e `doctor` diretamente no Claude Code.

## Motor headless / API (para frontends)

`auto-edit serve` (requer o extra `[api]`: `pip install "auto-edit-video[api]"`)
sobe uma API local **JSON + SSE** que qualquer frontend (desktop Flutter/Tauri
ou web) usa pra dirigir o pipeline canônico — sem reimplementar nada. A lógica
fica em `auto_edit/engine.py` (fachada pura sobre `ralph.sh` + `pipeline.py` +
`workspace.py`); `auto_edit/api.py` é só a casca HTTP.

```
GET  /api/health
GET  /api/library                 # lista workspaces + status derivado
GET  /api/browse?dir=             # pastas + vídeos de um diretório (file picker)
GET  /api/videos/<id>             # detalhe (stages, plano, metadata)
GET  /api/videos/<id>/plan        # cortes + o que é dito em cada trecho
PUT  /api/videos/<id>/plan        # {kept_segments: [{start, end, summary?}]}
GET  /api/videos/<id>/result      # metadata + arquivos finais
GET  /api/videos/<id>/file/<kind> # video | thumbnail | captions | notes
POST /api/edit                    # {video_path, type, context, language, overlays_dir, ...}
POST /api/videos/<id>/resume      # {from_stage}
GET  /api/jobs/<job_id>/events    # progresso ao vivo (SSE: log/stage/done/error)
GET  /api/videos/<id>/events      # SSE do job atual daquele vídeo
```

O `web_app.py`/`gui.py` legados são independentes e continuam funcionando.
