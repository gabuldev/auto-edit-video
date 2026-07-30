# Narrated Mode — Roteiro + B-roll + Voz → Vídeo

**Status:** Design aprovado, pré-implementação
**Data:** 2026-06-15
**Tipo novo de pipeline:** `narrated` (além de `short`/`long`)

## Problema

O pipeline atual (`short`/`long`) assume que **o áudio do vídeo é o conteúdo**: transcreve a fala do take, corta silêncio/filler dessa fala, e legenda as palavras ditas. Funciona pra vídeo onde a pessoa fala na câmera.

Não serve pra vídeo narrado com roteiro: B-roll (clips sem fala útil) + uma narração escrita à parte. Nesse caso a narração não existe como áudio no take; o visual é mapeado por intenção ("ônibus vermelho cruzando a ponte"), não por transcrição do clip. Rodar o pipeline atual transcreve o som ambiente errado, corta com base nisso, e legenda o áudio errado.

## Objetivo

Novo modo que recebe **roteiro + 1 áudio de narração gravada + pasta de B-rolls** e produz um vídeo montado:
- B-roll trocando em vários cortes por bloco do roteiro (dinâmica de vlog)
- A narração gravada como única trilha de áudio
- Legenda estilo CapCut gerada da própria narração
- AI casa clips↔blocos por visão; o usuário aprova num preview antes de renderizar

## Premissas confirmadas (do brainstorming)

- **Narração:** o usuário grava a própria voz (não TTS), **um arquivo único corrido** com a narração inteira.
- **Fidelidade:** o usuário narra fiel ao roteiro escrito (frases iguais), mas o **timing real difere** dos timestamps do roteiro.
- **Match de clips:** AI analisa o conteúdo visual dos clips e casa com a descrição de cada bloco (sem o usuário nomear clip por bloco).
- **Granularidade:** **vários clips por bloco** — um bloco de ~8s pode ter 2+ cortes pra ficar dinâmico.
- **Aprovação:** AI propõe o mapa bloco→clips; usuário revisa em preview (texto + thumbnails), ajusta, **só então renderiza**.
- **Áudio dos clips:** mudo total — só a voz.
- **Cobertura imperfeita:** se os clips não somam a duração do bloco, o último clip estica (leve slow/freeze). Nunca tela preta.
- **Sem música** nesta v1 (Phase 2).

## Comando

```bash
auto-edit narrate roteiro.md \
  --voice narracao.mp3 \
  --clips ./brolls/ \
  --type short \
  -c "Tower Bridge" \
  [-l pt] [-m small]
```

- `roteiro.md` — texto livre do roteiro (posicional)
- `--voice` — arquivo de áudio da narração gravada (obrigatório)
- `--clips` — pasta com os B-rolls (obrigatório)
- `--type` — `short` (9:16) ou `long` (16:9); controla reframe e estilo de legenda
- `-c/--context`, `-l/--language`, `-m/--whisper-model` — iguais aos modos atuais

## Fluxo de stages

```
parse-script → extract-vo → align-blocks → analyze-clips → match → review → assemble → caption → metadata → thumbnail → done
   novo          reusa         novo           novo         novo    gate     novo       reusa     reusa      reusa
```

| Stage | Tipo | Função |
|-------|------|--------|
| `parse-script` | agent (claude) | Roteiro texto livre → blocos estruturados |
| `extract-vo` | tool (Whisper) | Transcreve a **voz** → word timestamps |
| `align-blocks` | tool (Python) | Casa texto de cada bloco com a transcrição → start/end real no áudio |
| `analyze-clips` | tool (Gemini visão) | Descreve conteúdo de cada clip; cacheado |
| `match` | agent (claude) | Casa clips↔blocos, empacota vários por bloco, define in/out |
| `review` | gate (slash + resume) | Usuário aprova/ajusta o mapa antes de renderizar |
| `assemble` | tool (ffmpeg) | Monta B-roll no timeline, muta clips, põe a voz, reframe |
| `caption` | reusa | Transcreve a voz, gera/queima legenda CapCut |
| `metadata` | reusa | Título/descrição/tags |
| `thumbnail` | reusa | Thumbnail |

## Mudança estrutural em `pipeline.py`

Hoje `STAGES` é uma lista única global com skip por tipo (`SKIP_FOR_LONG`, `SKIP_FOR_SHORT`). O fluxo `narrated` é diferente o bastante (não tem `plan`/`execute`/`evaluate` no mesmo sentido) pra justificar **sequências de stages por tipo**:

```python
STAGE_SEQUENCES = {
    "short":    ["extract", "plan", "review", "execute", "caption", "evaluate", "metadata", "thumbnail", "done"],
    "long":     ["extract", "plan", "review", "execute", "overlay", "evaluate", "metadata", "thumbnail", "done"],
    "narrated": ["parse-script", "extract-vo", "align-blocks", "analyze-clips", "match", "review", "assemble", "caption", "metadata", "thumbnail", "done"],
}
```

- `init()` recebe o tipo e materializa só os stages daquela sequência.
- `set_stage_status()` avança pelo próximo stage **da sequência do vídeo**, não da lista global.
- `loop_back()` continua só pros tipos que têm `evaluate` (short/long). `narrated` v1 não tem loop de avaliação automático (o gate de review humano substitui).
- Os tipos atuais mantêm comportamento idêntico (mesma ordem de stages, mesmos skips traduzidos pra sequência explícita). Refator de forma, não de comportamento, pra short/long.

`ralph.sh` ganha os novos casos no dispatch (`parse-script)`, `extract-vo)`, etc.), apontando pra tools/agents novos. Os casos existentes não mudam.

## Contratos de dados

### `script.json` (saída de `parse-script`)
```json
{
  "blocks": [
    {
      "id": 1,
      "narration": "A Tower Bridge é linda, mas nasceu de um caos! No século 19...",
      "visual": "imagem imponente da Tower Bridge vista do rio Tâmisa",
      "script_hint": [0.0, 8.0]
    }
  ]
}
```
- `narration` — texto exato narrado (usado pelo alinhamento)
- `visual` — descrição pro match de clips
- `script_hint` — os `[m:ss]` do roteiro; **só palpite de ordem**, não vira timing final

### `vo_alignment.json` (saída de `align-blocks`)
```json
{
  "vo_duration": 88.0,
  "blocks": [
    { "id": 1, "vo_start": 0.0,  "vo_end": 7.4 },
    { "id": 2, "vo_start": 7.4,  "vo_end": 15.9 }
  ]
}
```
- A voz manda no tempo. `vo_end - vo_start` = duração que o B-roll do bloco precisa cobrir.
- Alinhamento por **similaridade de texto** (não match exato) — robusto a pequenas variações na gravação.

### `clip_index.json` (saída de `analyze-clips`, cacheado)
```json
{
  "onibus.mp4":       { "duration": 12.3, "desc": "ônibus vermelho de 2 andares cruzando ponte", "tags": ["ônibus", "ponte", "londres"] },
  "piso_vidro.mp4":   { "duration": 6.8,  "desc": "piso de vidro com vista do trânsito embaixo", "tags": ["piso de vidro", "altura"] }
}
```

### `clip_map.json` (saída de `match`, editável no gate)
```json
{
  "blocks": [
    {
      "id": 4,
      "vo_start": 30.1,
      "vo_end": 38.0,
      "clips": [
        { "file": "onibus.mp4",        "in": 2.0, "out": 5.5 },
        { "file": "ponte_abrindo.mp4", "in": 0.0, "out": 4.4 }
      ]
    }
  ]
}
```
- Soma das durações dos clips (`out-in`) ≈ `vo_end - vo_start`.
- Um clip pode aparecer em blocos diferentes (material limitado).

## Detalhe das peças novas

### `analyze-clips`
- Pra cada clip: extrai 3–5 frames (ffmpeg, em início/meio/fim) → Gemini Vision → `{desc, tags}`.
- Lê `duration` via ffprobe.
- Cacheia em `clip_index.json`; pula clips já indexados (clip não muda).
- Fallback sem `GEMINI_API_KEY`: usa claude com visão lendo os frames.

### `match` (agent)
- Entrada: blocos (`visual` + duração alvo) + `clip_index`.
- Saída: `clip_map.json` com vários clips por bloco, in/out definidos, cobrindo a duração.
- Regra de packing: empacota clips até `Σ(out-in) ≈ duração do bloco`; corta o último clip pra fechar.
- Pode reusar clips entre blocos; evita repetir o mesmo clip em blocos adjacentes quando há alternativa.

### `assemble` (tool ffmpeg)
- Lê `clip_map.json` em ordem de bloco.
- Pra cada clip: `trim`/`atrim`-mudo + `setpts`, concatena tudo numa trilha de vídeo.
- Áudio: descarta o dos clips; usa `narracao.mp3` como única trilha (mesmo tratamento Apple-compat do `executor.py` — loudnorm + aformat stereo).
- Reframe 9:16 (short) ou 16:9 (long) reusando a lógica de crop/scale do `executor.py`.
- Cobertura: se `Σ clips < duração do bloco`, estica o último clip (`setpts`/`tpad`) pra não deixar buraco.
- Saída: `edited_video.mp4`, com duração = duração da voz.

### `caption` (reusa, sem mudança de código)
- Roda no `edited_video.mp4`; transcreve a voz → legenda CapCut.
- Beneficia do guard de cobertura já adicionado (rejeita post_cut stale; avisa se legenda não cobre o vídeo).

## Preview gate

Depois de `match`, o pipeline pausa em `review`. O usuário roda:
```bash
auto-edit review-broll roteiro      # (e/ou slash /review-broll)
```
Mostra por bloco: intervalo na voz, trecho da narração, clips escolhidos com in/out e descrição, e uma grade de thumbnails dos frames usados. O usuário edita `clip_map.json` (troca arquivo, ajusta in/out) ou aprova. Então:
```bash
auto-edit resume roteiro --from assemble
```
Sem aprovação não renderiza.

## Custo e performance

- Gasto concentra em `analyze-clips`: N clips × ~4 frames no Gemini. Cacheado → roda 1× por pasta. ~20 clips ≈ poucos centavos.
- `match` e `parse-script`: 1 chamada claude cada, baratas.
- `assemble` + `caption`: ffmpeg local (re-encode ~ duração da voz).

## Plano de testes (pytest, padrão do repo)

- `parse-script`: roteiro de exemplo (Tower Bridge) → número e conteúdo de blocos corretos.
- `align-blocks`: dada transcrição sintética + blocos, calcula `vo_start/end`; inclui caso de frase com pequena variação (similaridade, não exato).
- `match` packing: `Σ(out-in)` por bloco ≈ duração alvo; sem buraco; não estoura.
- `assemble`: `clip_map` → string de filtro ffmpeg correta (clips mudos + voz única + reframe); duração final == duração da voz.
- `pipeline.py`: `STAGE_SEQUENCES` — short/long mantêm ordem idêntica à atual; narrated materializa a sequência nova; `set_stage_status` avança certo por tipo.
- Guard de cobertura de legenda: reusa o já adicionado no `captioner.py`.

## Fora de escopo (v1)

- Música / trilha de fundo (Phase 2).
- TTS (narração é sempre voz gravada).
- Match por visão "mágico" sem gate (o gate humano é parte do design).
- Loop de avaliação automático (`evaluate`) pro modo narrated.
- Narração em múltiplos arquivos (só arquivo único corrido).

## Riscos

- **Improviso na gravação** desalinha blocos → mitigado por similaridade + gate visível.
- **Visão erra conteúdo** (ônibus→carro) → mitigado pelo gate de review com thumbnails.
- **Material insuficiente** (poucos clips pra cobrir a voz) → `match` reusa clips; `assemble` estica; gate mostra repetição pro usuário decidir.
