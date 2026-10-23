# auto-edit-video

Pipeline de edição automatizada de vídeo usando IA. Transcreve, planeja cortes, executa, adiciona legendas e gera metadata — tudo via CLI.

## Quick Reference

```bash
# Editar short (vertical, com legendas)
auto-edit short video.mp4 --context "review de produto tech"

# Editar long (horizontal, sem legendas, com overlays)
auto-edit long video.mp4 --context "tutorial de Python"

# Cold open (teaser) e reordenação de blocos vêm LIGADOS por padrão;
# desligue com --no-cold-open / --no-reorder
auto-edit long video.mp4 -c "..." --no-reorder

# Batch (vários vídeos)
auto-edit batch upload/ --type short --context "vlogs de viagem"

# Shorts a partir de um long já editado
auto-edit shorts video.mp4              # propõe candidatos
auto-edit shorts video.mp4 --pick 1,3   # corta os escolhidos

# Estilos: criar com IA, exportar/importar (o app faz o mesmo na tela Estilos)
auto-edit style generate "tech escuro, neon roxo" --image ref.png --save   # a IA reproduz o layout da referência
auto-edit style adjust meu-estilo "título maior, tira o círculo" --activate
auto-edit style export neon -o neon.autoedit-style.json
auto-edit style import neon.autoedit-style.json --activate

# Publicar no YouTube (vídeo final + thumbnail + metadata)
auto-edit publish auth youtube                       # conecta o canal (uma vez)
auto-edit publish youtube video.mp4 --privacy unlisted
auto-edit publish youtube video.mp4 --publish-at 2026-10-10T18:00:00-03:00
# long: legenda (.srt da transcrição) vai junto por padrão (--no-captions desliga);
# --comment posta o comentário pra fixar (vídeo privado não aceita; fixar é no Studio)

# Retenção: onde o público saiu, com o que era dito (YouTube Analytics)
auto-edit insights retention video.mp4      # salva retention.json; o planner usa nos próximos
auto-edit insights retention --all

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
extract → plan → review → evaluate → execute → overlay → caption → metadata → done
Whisper   Claude  Claude   Claude     FFmpeg    FFmpeg    FFmpeg    Claude
```

- **short**: pula overlay, faz caption (legendas estilo CapCut) — planner = `agents/planner.md` (limpeza)
- **long**: faz overlay (lower third + CTA; o agente lê a transcrição pós-corte e responde no tempo do vídeo editado), pula caption — planner = `agents/planner_long.md` (curadoria editorial: descarta blocos temáticos, define duração pela densidade do conteúdo, reporta `dropped_blocks`)

O resumo da curadoria aparece em `auto-edit status <video>` e no `--dry-run`.

No long, o `metadata` escreve o título pra **clique** (gancho/resultado, sem
nome de marca que estranho não reconhece, complementando a thumbnail) e
`title_options` (3 ângulos, o 1º é o `youtube_title`) pra testar no Studio; com
o insights conectado, indica em `next_video` um vídeo do canal pra tela final.
Os dois saem no `metadata.txt` e no card Publicar do app. O `overlay` não põe
nada nos últimos 20s (`END_SCREEN_SEC`): ali fica a tela final do YouTube.

O evaluator julga o **corte planejado**, antes de renderizar: a transcrição do
corte sai do plano (`postcut --planned`, mesmos intervalos do executor, sem
FFmpeg) e o cold open/reordenação roda logo antes dele. Se rejeitar, o pipeline
volta ao `plan` com feedback (até 3 iterações) e só refaz plan → review →
evaluate; o FFmpeg corta uma vez só, depois da aprovação.

### Ordem de reprodução (cold open / reordenação)

O plano diz **o que fica** (`kept_segments`, sempre cronológico). O campo
opcional `sequence` diz **em que ordem tocar**: janelas no tempo do original,
recortadas pelo que foi mantido (nunca traz de volta um corte). Blocos cobrem
tudo que ficou sem se sobrepor; teasers (`role: "teaser"`, 2–15s, até 20s no
total) tocam a mais e o trecho toca de novo no lugar. Sequência inválida é
ignorada e o vídeo sai cronológico. Lógica em `auto_edit/sequence.py`.

Com `--reorder`, o mesmo agente também pode propor a ordem dos blocos; os
blocos são normalizados numa partição do vídeo (sem buraco nem sobreposição)
e só valem se de fato mudarem a ordem. Se a nova ordem já abre no trecho do
teaser, o teaser é descartado (não toca a mesma coisa duas vezes).

Ligado por padrão (`--no-cold-open`/`--no-reorder` ou os checkboxes no app desligam), o agente `agents/cold_open.md` roda
no `execute`, antes do executor, e escolhe o teaser. Se ele pular, falhar ou o
teaser não passar nas regras, o vídeo sai sem cold open — nunca falha o stage.

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
| `renderer/` | Layouts em React → PNG sem navegador (Satori + resvg-wasm), compilado pelo bun no executável `auto-edit-render` que vai no app. Hoje: a thumbnail (`tools/thumbnailer.py` cai pro Pillow se ele faltar ou falhar) e os overlays animados do long (lower third + CTA, `tools/overlayer.py`). **Estilo = dados** (tokens: cores, fontes, cantos, posições, textos do CTA, velocidade), validados em `auto_edit/styles.py` (presets Padrão/Minimal/Neon/Impacto + os da pessoa em `~/.auto-edit/styles/`, ativo em `settings.style`); o layout React que aplica os tokens fica em `renderer/src/layouts/<nome>/`. Tela **Estilos** do app: marca (nome, @, logo), galeria com prévia real num frame do vídeo mais recente (`auto-edit-render preview`) e editor. A galeria traz 12 estilos prontos com layout próprio da thumbnail em HTML (`auto_edit/style_presets.py`: Rosto Gigante, Tarja, Neon Tech, Limpo, Jornal, Versus, Painel, Celular, Reação, Quadrinho, Preto e Ouro, Card; o título usa a fonte do estilo). **Criar com IA** é beta: desligado no app (`AI_STYLES` em `desktop/ui/js/styles.js`), segue na CLI (`agents/stylist.md` via `agents.complete(images=)`): a IA vê a thumbnail de referência e escreve o **layout da thumbnail em HTML + CSS** (`tokens.thumbnail.html`, limpo em `auto_edit/thumb_html.py`; lacunas `{{titulo}}`, `{{frame}}`, `{{frame2}}`, `{{destaque}}`…; `data-fit` ajusta o título), desenha com um frame e título reais e corrige comparando (`agents/stylist_review.md`, até 3 voltas, job com progresso); **Ajustar com IA** e editor de HTML no app; o renderer desenha em `renderer/src/html.ts` e o thumbnailer cai pro layout padrão (e depois Pillow) se falhar; só o long 16:9 usa. Agentes com visão: Claude, Codex, OpenRouter, Ollama de visão. `{{rosto}}`/`{{rosto_contorno}}` são a pessoa recortada automaticamente de um frame (`auto_edit/face_cutout.py`: U²-Net via onnxruntime, só num frame onde um detector de rosto (UltraFace, 1,2 MB) acha um rosto — mão sozinha nunca vira recorte; se o frame da thumb não tem rosto, procura em outros momentos do vídeo; sem rosto em nenhum, o layout sai sem o recorte. Modelos baixados no 1º uso em `~/.auto-edit/models`; foto em `assets/thumbnails/faces/` tem prioridade). Cores do logo (`auto_edit/palette.py`), exportar/importar `.autoedit-style.json` (sem a marca). Dev: `cd renderer && bun install` |

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
| `AUTO_EDIT_LLM` | `claude` | Agente dos stages de IA: `claude`, `cursor`, `agy` (Antigravity), `opencode`, `codex`, `openrouter` (API, chave em `OPENROUTER_API_KEY` ou salva pelo app em `tokens/openrouter.key`) ou `ollama` (modelo local). Ver `auto_edit/agents.py` |
| `AUTO_EDIT_AGY_MODEL` / `AUTO_EDIT_OPENCODE_MODEL` / `AUTO_EDIT_CODEX_MODEL` / `AUTO_EDIT_OPENROUTER_MODEL` / `AUTO_EDIT_OLLAMA_MODEL` | — | Modelo de cada agente (ex.: `opencode/big-pickle`, `anthropic/claude-sonnet-4.5`, `qwen2.5:7b`; OpenRouter usa `openrouter/auto` sem modelo) |
| `AUTO_EDIT_OLLAMA_CTX` | `32768` | Janela de contexto do modelo local. Com Ollama como principal, plan e overlay recebem a transcrição compacta em linhas (`auto_edit/runner.py`, `_compact_transcript`; long de 10 min ≈ 18k tokens); prompt maior que a janela é recusado (cai no fallback, se houver), nunca truncado |
| `AUTO_EDIT_LLM_FALLBACK` | — | CLI fallback se primário falhar |
| `AUTO_EDIT_END_PADDING` | `0.2` | Segundos adicionados ao final de cada segmento mantido |
| `AUTO_EDIT_LANGUAGE` | `pt` | Idioma do áudio para transcrição |
| `AUTO_EDIT_HOME` | `~/.auto-edit` | Diretório de profile + plans (fora do repo) |
| `AUTO_EDIT_INBOX` | — | Pasta padrão pra `auto-edit plan ingest` |
| `AUTO_EDIT_FFMPEG` | — | ffmpeg com libass pro stage caption (se o do PATH não tiver o filtro `subtitles`) |
| `AUTO_EDIT_THUMB_TS` | — | Força o frame da thumbnail num timestamp (segundos), pulando a seleção automática |
| `AUTO_EDIT_THUMB_RENDERER` | — | `pillow` desenha a thumbnail com o layout antigo (Pillow) em vez do React (`renderer/`) |
| `AUTO_EDIT_RENDER_BIN` | — | Caminho do `auto-edit-render`. Sem ele: o do PATH (o app traz no `bin/` do motor) ou, num checkout, `bun run renderer/src/cli.tsx` |
| `AUTO_EDIT_ASSETS_OVERLAYS` | — | Pasta com os MP4s de overlay próprios, com fundo verde (`ctas.mp4`, `lowerthid_gabul.mp4`). Opcionais: sem eles o React desenha. Tem prioridade sobre `assets/overlays/`. Também via `--overlays-dir` no `long`/`apply-overlays` |
| `AUTO_EDIT_OVERLAY_SOURCE` | `auto` | `auto`: MP4 próprio se existir, senão React. `react`: sempre React. `mp4`: só MP4 (comportamento antigo). Nome/@/logo do lower third vêm de `brand` no settings (app → Estilos); sem nome, usa o do canal do YouTube conectado. Cores/fontes/posições vêm do estilo ativo |
| `AUTO_EDIT_OVERLAYS_STRICT` | — | `1` faz o stage `overlay` falhar quando um overlay planejado não sai (sem MP4 e sem React). Por padrão ele só avisa e renderiza sem |
| `AUTO_EDIT_SEGMENT_THRESHOLD` | `12` | Acima de N segmentos, o `execute` corta um-a-um + concat (evita OOM do FFmpeg em vídeo longo/4K) |
| `GEMINI_API_KEY` | — | API key para correção de texto via Gemini |
| `AUTO_EDIT_YT_CLIENT_SECRET` | — | Caminho do JSON de OAuth client (Desktop) do Google Cloud, pro `auto-edit insights auth youtube` e `auto-edit publish auth youtube`. Sem ele, reaproveita o client de um token já salvo. Publish e insights usam **uma conexão só** (`auto_edit/youtube_auth.py`, `tokens/youtube.json`). App OAuth em modo "Testing" expira o token em 7 dias: publique o app ("In production") pra não expirar |
| `AUTO_EDIT_YT_CATEGORY` | `28` | Categoria do YouTube nos uploads do `publish` (28 = Ciência e tecnologia) |
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
GET  /api/videos/<id>/captions    # legenda do short: estilo final, ajuste próprio, fast (tem edited_video)
PUT  /api/videos/<id>/captions    # {position, offset, size, hidden}: só essas 4 chaves; ausente mantém o anterior
POST /api/videos/<id>/captions/preview  # {ajuste} → PNG da legenda num frame do short (regravar: /resume from_stage=caption)
GET  /api/videos/<id>/result      # metadata + arquivos finais
GET  /api/videos/<id>/file/<kind> # video | thumbnail | captions | notes
POST /api/edit                    # {video_path, type, context, language, overlays_dir, ...}
POST /api/videos/<id>/resume      # {from_stage}
GET  /api/videos/<id>/shorts      # candidatos a short de um long pronto
POST /api/videos/<id>/shorts      # {max_dur} roda o clipper (job + SSE)
POST /api/videos/<id>/shorts/cut  # {pick: [1, 3]} semeia os _shortN e corta em fila
GET  /api/publish/youtube         # conta conectada? (POST .../connect abre o OAuth)
GET  /api/videos/<id>/publish     # defaults do metadata + histórico (publish.json)
POST /api/videos/<id>/publish/youtube  # {title, description, tags, privacy, publish_at, force}
POST /api/videos/<id>/open/<kind> # abre no app padrão / {reveal} no Finder
GET  /api/videos/<id>/retention   # análise salva (POST busca a curva no YouTube)
GET  /api/styles                  # estilos (presets + seus), o ativo, fontes, marca
PUT  /api/styles/active           # {id}
POST /api/styles                  # {name, tokens, id?, activate?} salva um estilo seu
DELETE /api/styles/<id>
POST /api/styles/preview/<kind>   # {tokens} → PNG (thumbnail | lower_third | cta)
POST /api/styles/generate         # {description, image?} → {job_id}; SSE progress → done {result: rascunho} (IA)
POST /api/styles/adjust           # {tokens, request, image?} → {job_id}; o mesmo, ajustando um estilo
POST /api/styles/palette          # {image?} → {colors, suggested} (sem imagem: o logo salvo)
POST /api/styles/<id>/export      # grava em Downloads e mostra no Finder → {path}
POST /api/styles/import           # {file} → estilo salvo (nunca sobrescreve)
PUT|DELETE|GET /api/brand/logo    # {data: "data:image/png;base64,…"}
GET  /api/jobs/<job_id>/events    # progresso ao vivo (SSE: log/stage/progress/done/error)
GET  /api/videos/<id>/events      # SSE do job atual daquele vídeo
```

O `web_app.py`/`gui.py` legados são independentes e continuam funcionando.
