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

# Status / Resume / Doctor
auto-edit status video.mp4
auto-edit resume video.mp4 --from plan
auto-edit doctor
```

## Pipeline

```
extract → plan → review → execute → overlay → caption → evaluate → metadata → done
Whisper   Claude  Claude   FFmpeg   FFmpeg    FFmpeg    Claude     Claude
```

- **short**: pula overlay, faz caption (legendas estilo CapCut)
- **long**: faz overlay, pula caption

Se o evaluator rejeitar, o pipeline volta ao `plan` com feedback (até 3 iterações).

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
| `GEMINI_API_KEY` | — | API key para correção de texto via Gemini |

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
