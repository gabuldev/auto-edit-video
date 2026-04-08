# Auto Edit Video

Pipeline de edição automatizada de vídeo usando IA. Transcreve, planeja cortes, executa, adiciona legendas e gera metadata — tudo via CLI, sem intervenção manual.

## Como funciona

O pipeline é uma state machine de 9 stages orquestrada por agentes LLM (Claude) e ferramentas FFmpeg:

```
extract → plan → review → execute → overlay → caption → evaluate → metadata → done
  │         │       │        │         │          │          │          │
Whisper   Claude  Claude   FFmpeg   FFmpeg     FFmpeg    Claude     Claude
+ Claude                                      + ASS
```

| Stage | O que faz | Tipo |
|-------|-----------|------|
| **extract** | Transcreve o áudio (Whisper `small`) + mapa de energia + correção com Claude | Python |
| **plan** | Analisa transcrição e planeja os cortes (silêncios, false starts, filler) | LLM Agent |
| **review** | QA do plano de cortes (valida, adiciona cortes faltando, merge) | LLM Agent |
| **execute** | Aplica os cortes no vídeo via FFmpeg com normalização de áudio | Python |
| **overlay** | Compõe overlays gráficos com chroma key (apenas long-form) | LLM + Python |
| **caption** | Gera legendas estilo CapCut com destaque por palavra (apenas shorts) | Python |
| **evaluate** | Avalia qualidade do resultado; rejeita e volta ao plan se necessário | LLM Agent |
| **metadata** | Gera título, descrição e hashtags para publicação | LLM Agent |

Se o avaliador rejeitar, o pipeline volta ao `plan` com feedback — até 3 iterações.

## Instalação

### Opção 1 — Nix (recomendada, zero dependências manuais)

Nix instala Python, FFmpeg e todas as deps automaticamente. Nada precisa estar pré-instalado.

```bash
# Instalar Nix (uma vez, se ainda não tiver)
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install

# Instalar auto-edit (com tudo incluso)
nix profile install github:gabuldev/auto-edit-video
```

Na primeira execução, o auto-edit cria um venv e instala as deps Python (~2 GB com PyTorch). Depois disso, executa instantaneamente.

Ou rode sem instalar:

```bash
nix run github:gabuldev/auto-edit-video -- short video.mp4 --context "..."
```

### Opção 2 — curl | bash (instala deps do sistema automaticamente)

```bash
curl -sSL https://raw.githubusercontent.com/gabuldev/auto-edit-video/main/install.sh | bash
```

O script detecta e instala automaticamente o que falta (Python, FFmpeg, git) via Homebrew (macOS), apt, dnf ou pacman (Linux). Instala o `auto-edit` em `~/.auto-edit-video/`.

### Pós-instalação

```bash
auto-edit doctor    # valida o setup
auto-edit update    # atualiza para última versão
```

Para desinstalar:

```bash
# Nix
nix profile remove auto-edit-video

# curl | bash
bash ~/.auto-edit-video/uninstall.sh
```

### Dependência opcional

- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — `npm install -g @anthropic-ai/claude-code` (necessário para stages de IA)

### Desenvolvimento (Nix)

Para contribuidores:

```bash
git clone https://github.com/gabuldev/auto-edit-video.git
cd auto-edit-video
nix develop  # ou: make setup
```

## Uso

### Editar um short (vertical, com legendas)

```bash
auto-edit short upload/meu-video.mp4 \
  --context "Review de produto tech, tom casual" \
  --whisper-model small
```

### Editar long-form (horizontal, com overlays, sem legendas)

```bash
auto-edit long upload/meu-video.mp4 \
  --context "Tutorial de programação em Python"
```

### Batch (processar vários vídeos)

```bash
auto-edit batch upload/pasta-de-videos/ --type short \
  --context "Vlogs de viagem, energia alta"
```

### Merge (concatenar + editar)

```bash
auto-edit merge upload/clips/ --name video-final --type long \
  --context "Compilação de dicas de produtividade"
```

### Retomar de um stage específico

```bash
auto-edit resume upload/meu-video.mp4 --from plan
auto-edit resume upload/meu-video.mp4 --from extract --whisper-model medium
```

### Ver status do pipeline

```bash
auto-edit status upload/meu-video.mp4
```

## Claude Code Skills

O projeto inclui slash commands para usar dentro do Claude Code:

| Comando | O que faz |
|---------|-----------|
| `/edit-video` | Guia interativo para iniciar uma edição |
| `/edit-status` | Dashboard de todos os pipelines ativos |
| `/edit-preview` | Preview textual do que vai ser cortado |
| `/review-cuts` | Aprovar/editar o cut plan antes de executar |
| `/fix-stage` | Diagnostica e corrige um stage com falha |

## Opções

### Modelo Whisper

| Modelo | Velocidade | Precisão | Uso |
|--------|-----------|----------|-----|
| `tiny` | Muito rápido | Básica | Áudio limpo, fala clara |
| `base` | Rápido | Boa | Testes rápidos |
| **`small`** | **Moderado** | **Muito boa** | **Recomendado (default)** |
| `medium` | Lento | Excelente | Áudio ruidoso, múltiplos falantes |
| `large` | Muito lento | Máxima | Quando precisão é crítica |

### Legendas (shorts)

```bash
auto-edit short video.mp4 \
  --highlight-color "&H0045FF&"  # cor ASS (BBGGRR) — padrão: laranja
  --highlight-border 2.5         # espessura do destaque
  --font-size 14                 # tamanho da fonte
```

### LLM Backend

```bash
# Usar Claude (default)
auto-edit short video.mp4

# Usar Cursor Agent como fallback
auto-edit short video.mp4 --cli claude --cli-fallback cursor

# Via variáveis de ambiente
export AUTO_EDIT_LLM=claude
export AUTO_EDIT_LLM_FALLBACK=cursor
export AUTO_EDIT_LLM_TIMEOUT=600  # timeout em segundos (default: 10min)
```

## Arquitetura

```
auto-edit-video/
├── auto_edit/              # Core do pipeline
│   ├── cli.py              # CLI (Typer) — 8 comandos
│   ├── pipeline.py         # State machine (9 stages)
│   ├── runner.py           # Builder de prompts + invocação LLM
│   └── workspace.py        # Gestão de workspaces
├── agents/                 # Prompts dos agentes LLM (markdown)
│   ├── planner.md          # Regras de planejamento de cortes
│   ├── reviewer.md         # Regras de QA dos cortes
│   ├── evaluator.md        # Regras de avaliação de qualidade
│   ├── overlayer.md        # Regras de posicionamento de overlays
│   └── metadata.md         # Regras de geração de metadados
├── tools/                  # Ferramentas Python (FFmpeg/Whisper)
│   ├── extract.py          # Transcrição + energia + correção IA
│   ├── executor.py         # Cortes FFmpeg + loudnorm
│   ├── captioner.py        # Legendas ASS + burn FFmpeg
│   └── overlayer.py        # Composição de overlays + chroma key
├── ralph.sh                # Loop engine (orquestra stages)
├── tests/                  # Test suite (pytest)
├── .claude/commands/       # Claude Code skills
├── workspace/              # Workspaces por vídeo (auto-gerados)
└── output/                 # Vídeos finalizados
```

### Fluxo de dados por stage

```
upload/video.mp4
  → workspace/video/
      transcription.json      ← extract (Whisper + energia + correção Claude)
      cut_plan.json            ← plan (agente LLM)
      reviewed_plan.json       ← review (agente LLM)
      edited_video.mp4         ← execute (FFmpeg trim + concat + loudnorm)
      overlaid_video.mp4       ← overlay (FFmpeg chroma key) [long only]
      captions.ass             ← caption (ASS gerado)
      captioned_video.mp4      ← caption (FFmpeg subtitles burn) [short only]
      post_cut_transcription.json ← caption (timestamps remapeados)
      assessment.json          ← evaluate (agente LLM)
      metadata.json            ← metadata (agente LLM)
  → output/video_final.mp4    ← done (cópia + cleanup)
  → output/video.txt          ← done (título + descrição + hashtags)
```

## Funcionalidades técnicas

- **Codec fallback**: `h264_videotoolbox` → `libx264` → `libx265` (cross-platform)
- **Normalização de áudio**: EBU R128 (`loudnorm`) após cortes para volume consistente
- **Validação de cut plans**: Verifica bounds antes do FFmpeg; rejeita intervalos sub-frame
- **Correção de transcrição com IA**: Claude revisa output do Whisper (corrige alucinações, termos técnicos)
- **Timestamps remapeados**: Captioner reutiliza transcrição original sem re-rodar Whisper
- **Timeout em chamadas LLM**: Configurável via `AUTO_EDIT_LLM_TIMEOUT` (default: 600s)
- **Persistência de erros**: Falhas salvas no `pipeline.json` com mensagem de erro
- **Progresso em tempo real**: Output dos tools Python e FFmpeg visível durante execução

## Testes

```bash
pip install -e ".[test]"
python -m pytest tests/ -v
```

## Licença

MIT
