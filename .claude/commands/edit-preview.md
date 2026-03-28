# /edit-preview

Gera um preview textual do vídeo editado — mostra o que vai sobrar e o que vai ser cortado, como um roteiro.

## Argumento

O usuário pode passar o nome do workspace: `/edit-preview DJI_0780`

Se não passar, listar workspaces que têm `reviewed_plan.json` disponível.

## O que fazer

### Passo 1 — Carregar os dados

Ler:
- `workspace/<nome>/reviewed_plan.json`
- `workspace/<nome>/transcription.json`
- `workspace/<nome>/pipeline.json`

Verificar qual plano usar:
- Se `reviewed_plan.json` existe → usar (plano final)
- Senão, se `cut_plan.json` existe → usar com aviso "(plano preliminar, ainda não revisado)"
- Senão → avisar que o planner ainda não rodou

### Passo 2 — Reconstruir a timeline completa

Usar a duração do vídeo e os intervalos de `kept_segments` (ou invertendo `cuts`) para montar uma sequência de blocos: MANTIDO / CORTADO / MANTIDO / CORTADO...

Para cada bloco MANTIDO:
- Buscar em `transcription.json` as palavras cujos timestamps caem dentro do intervalo
- Montar o texto da fala concatenando as palavras
- Se não houver palavras (música, b-roll silencioso), mostrar "(sem fala)"

Para cada bloco CORTADO:
- Mostrar o motivo do corte se disponível no plano (`reason` ou `type`)
- Mostrar um trecho da fala que foi removida (até 8 palavras)

### Passo 3 — Calcular estatísticas

- Duração original
- Duração final (soma dos segmentos mantidos)
- Tempo cortado total e percentual
- Número de cortes por tipo
- Número de palavras mantidas vs removidas

### Passo 4 — Exibir o preview

Formato:

```
🎬 Preview — DJI_0780
Original: 1:43  →  Final: 1:12  (-30%, -31s)
Cortes: 8 total  (5 silêncios, 3 conteúdo)
══════════════════════════════════════════════════════

▶  [00:00 – 00:08]  8s
   "Hoje vou mostrar como montar uma impressora 3D
   de forma simples e rápida"

✂  [00:08 – 00:12]  4s  · silêncio
   (cortado: pausa longa sem fala)

▶  [00:12 – 00:47]  35s
   "O primeiro passo é separar todas as peças
   que vêm na caixa... o trilho vertical aqui...
   e essa é a base que vai segurar tudo"

✂  [00:47 – 00:50]  3s  · false start
   (cortado: "então ahn então vamos")

▶  [00:50 – 01:12]  22s
   "Agora vamos encaixar a base no trilho usando
   os parafusos M3 que vêm no kit"

══════════════════════════════════════════════════════
📊 Resumo
   Duração: 1:43 → 1:12  (-30%)
   Silêncios removidos: 5  (-18s)
   Conteúdo removido: 3  (-13s)
   Palavras mantidas: 127/164 (77%)
```

### Passo 5 — Oferecer próximos passos

```
O que deseja fazer?
  [1] ✅ Parece bom — executar os cortes agora
  [2] ✏️  Revisar e ajustar os cortes  (abre /review-cuts)
  [3] 🔁 Re-executar o planner com mais contexto
  [4] 👁️  Só visualizar, não fazer nada
```

Se escolher [1], verificar se o stage `execute` já foi completado:
- Se não: rodar `python tools/executor.py workspace/<nome>`
- Se sim: informar que o vídeo já foi cortado e está em `workspace/<nome>/edited_video.mp4`

Se escolher [2]: seguir o fluxo do `/review-cuts`.

Se escolher [3]: perguntar a instrução adicional, salvar em `evaluator_feedback` e resetar para o stage `plan`.

## Notas

- Truncar falas muito longas em cada bloco: mostrar até ~15 palavras com "..." se necessário.
- Formatar timestamps como `mm:ss` (não segundos puros).
- Se o vídeo for muito longo (> 200 segmentos), limitar o preview aos primeiros 20 segmentos e mostrar "... e mais N segmentos" ao final.
- Se `execute` já rodou e `edited_video.mp4` existe, adicionar nota: "(cortes já aplicados — este é o resultado final)".
