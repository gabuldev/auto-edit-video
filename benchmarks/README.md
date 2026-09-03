# Benchmarks

## Planner: nosso vs Gemini (agentic video)

Quem escolhe melhor os cortes de um long — o **nosso planner**, que lê só a
transcrição do Whisper, ou o **Gemini**, que assiste o vídeo?

O anúncio do [agentic video understanding][post] não é um editor: é o modelo
decidindo sozinho o que assistir, em que velocidade e por qual modalidade
(frame, áudio, transcrição), com *sub-second moment retrieval* pra "precise
automated editing". Então o que dá pra comparar de verdade é **o plano de
cortes** — o resto do nosso pipeline (executor, legenda, overlay, metadata) não
tem equivalente do outro lado.

[post]: https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/

### Como o teste é justo

Os dois braços recebem:

- o **mesmo vídeo**;
- o **mesmo brief editorial** — `agents/planner_long.md`, literal, com um
  cabeçalho curto trocando "você recebe a transcrição" por "assista o vídeo";
- o **mesmo schema** de saída (`cuts` / `kept_segments` / `dropped_blocks`);
- o **mesmo downstream** — `auto_edit.snap` repara as fronteiras e
  `tools/executor.py` corta com os mesmos parâmetros de encode.

A única variável é quem planeja e o que ele percebe. É aí que mora a hipótese:
nosso planner **nunca vê a imagem**, então ele é cego pra take perdido, tela
travada, apresentador saindo do quadro — coisas que não aparecem na transcrição.

### Rodando

A chave vem do Doppler (projeto `auto-edit-video`, workplace gabuldev), então
não precisa de `.env`. Sem Doppler, basta ter `GEMINI_API_KEY` no ambiente.

```bash
pip install google-genai

doppler run -- python benchmarks/run_bench.py \
  --video ~/videos/live.mp4 \
  --context "live sobre carreira dev; manter as perguntas do chat" \
  --model gemini-3.7-flash
```

`--skip-render` compara só os planos (sem FFmpeg). `--slug` nomeia a pasta do
relatório.

### Modelos

O anúncio cobre **`gemini-3.7-flash`**, `gemini-3.6-flash` e
`gemini-3.5-flash-lite` — é onde o comportamento agêntico existe. O default é o
3.7. A API também expõe um `gemini-3.8-flash` que o post não menciona; se ele
herdou o mesmo comportamento, é uma terceira rodada interessante, mas não é o
que está sendo anunciado. O script lista os ids que a sua chave alcança quando
o `--model` não existe.

### O que sai

`benchmarks/reports/<slug>/`:

- `report.md` — a tabela comparativa, o reparo que cada plano precisou, custo e
  tempo, e o `target_rationale` que cada um escreveu;
- `plan_nosso.json` / `plan_gemini.json`;
- `metrics.json` — tudo em número, pra reprocessar depois.

Os dois cortes renderizados ficam em `workspace/bench_<slug>_*/edited_video.mp4`.

### As métricas, e por que cada uma

| métrica | o que revela |
|---|---|
| duração final / % removido | quão agressivo cada um foi |
| cortes, corte mediano, maior corte | granularidade: micro-trims vs blocos inteiros |
| blocos descartados | quanto de curadoria editorial de fato aconteceu |
| **palavras cortadas ao meio** | fala destruída na fronteira — o defeito que o `snap` conserta |
| antes/depois do snap | quanto de muleta mecânica cada planner precisou |
| **silêncio no corte final** | dead air que sobrou, medido pelo limiar adaptativo desta gravação |
| IoU dos trechos mantidos | quanto os dois concordam sobre o que é bom |
| tempo e tokens | o que cada abordagem custa |

Número não decide sozinho: assista os dois `edited_video.mp4`. As métricas
existem pra dizer **onde** olhar.
