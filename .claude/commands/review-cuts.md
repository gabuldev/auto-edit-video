# /review-cuts

Mostra o plano de cortes de forma legível e permite aprovar, rejeitar ou ajustar antes de executar o FFmpeg.

## Argumento

O usuário pode passar o nome do workspace: `/review-cuts DJI_0780`

Se não passar, listar workspaces que estão aguardando no stage `execute` (reviewed_plan.json existe, execute ainda não rodou).

## O que fazer

### Passo 1 — Carregar os dados

Ler:
- `workspace/<nome>/reviewed_plan.json` — plano de cortes aprovado pelo reviewer
- `workspace/<nome>/transcription.json` — transcrição com timestamps das palavras
- `workspace/<nome>/pipeline.json` — para saber a duração e tipo do vídeo

### Passo 2 — Montar o relatório de cortes

Calcular:
- Duração original do vídeo
- Total de tempo a ser cortado
- Total de tempo que vai sobrar
- Número de cortes por tipo (silence / content / false_start / etc)

Mostrar cada segmento que FICARÁ no vídeo final, com contexto da transcrição:

```
📋 Plano de Cortes — DJI_0780  (63.4s → 44.2s, -30%)
══════════════════════════════════════════════════════

MANTIDO  [00:00 → 00:08]  8.1s
  "Hoje vou mostrar como montar uma impressora 3D..."

✂️  CORTE  [00:08 → 00:12]  4.0s  silêncio
  (sem fala, energia < -36dB)

MANTIDO  [00:12 → 00:35]  23.0s
  "O primeiro passo é pegar as peças e..."

✂️  CORTE  [00:35 → 00:38]  3.0s  false start
  "então ahn... então vamos"

MANTIDO  [00:38 → 01:03]  25.0s
  "...pegar a base e encaixar no trilho vertical"

══════════════════════════════════════════════════════
5 cortes  |  -19.2s (-30%)  |  44.2s finais
Silêncios: 3  |  Conteúdo: 2
```

Para cada segmento MANTIDO, buscar na transcrição as palavras que cobrem aquele intervalo e mostrar um trecho da fala.

### Passo 3 — Perguntar o que o usuário quer fazer

```
O que deseja fazer?
  [1] ✅ Aprovar e executar os cortes agora
  [2] ✏️  Ajustar um corte específico
  [3] ➕ Adicionar um corte novo
  [4] ❌ Cancelar e re-executar o planner com instruções
  [5] 👁️  Só visualizar, não fazer nada ainda
```

### Passo 4a — Se "Aprovar e executar" (opção 1)

Executar:
```bash
python auto_edit/pipeline.py set-stage workspace/<nome> execute
```
Então rodar o executor:
```bash
python tools/executor.py workspace/<nome>
```
Acompanhar o output e reportar quando concluir.

### Passo 4b — Se "Ajustar um corte" (opção 2)

Perguntar: "Qual corte quer ajustar? (ex: o corte de 00:08 → 00:12)"

Mostrar o corte selecionado e perguntar:
- Novo start time?
- Novo end time?
- Ou remover completamente?

Fazer a edição diretamente no `reviewed_plan.json` e mostrar o plano atualizado.
Voltar ao Passo 3.

### Passo 4c — Se "Adicionar corte" (opção 3)

Perguntar: "Informe o intervalo a cortar: start → end (em segundos ou mm:ss)"

Validar que o intervalo está dentro da duração do vídeo e não sobrepõe cortes existentes.
Adicionar ao `reviewed_plan.json` no array `cuts` (ou remover do `kept_segments`).
Recalcular `kept_segments` a partir dos `cuts` atualizados.
Mostrar o plano atualizado e voltar ao Passo 3.

### Passo 4d — Se "Re-executar planner" (opção 4)

Perguntar: "Qual instrução adicional para o planner? (ex: 'cortar mais agressivamente', 'manter as pausas dramáticas')"

Salvar o feedback em `pipeline.json` no campo `evaluator_feedback`.
Resetar o pipeline para o stage `plan`:
```bash
python auto_edit/pipeline.py set-stage workspace/<nome> plan
```
Informar que o planner será rerrunado na próxima execução do pipeline.

## Notas

- Se `reviewed_plan.json` não existir (pipeline ainda não chegou no review), avisar e sugerir esperar ou rodar `/edit-status`.
- Se `execute` já foi completado, avisar que os cortes já foram aplicados e mostrar apenas para referência (sem opções de edição).
- Timestamps no formato `mm:ss` são mais legíveis que segundos puros — usar sempre.
- Se a transcrição não cobrir um intervalo (energia baixa sem palavras), mostrar "(sem fala detectada)".
