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

---

## Experimento 2 — Gemini como detector de eventos visuais

O primeiro experimento mostrou **onde** o modelo erra: ele descreve certo o que
vê e erra onde isso acontece na timeline (3 minutos de erro num vídeo de 12).
Então o segundo pergunta muito menos, de um jeito que limita o erro por
construção — e pergunta só o que a transcrição **não** tem.

```bash
doppler run -- python benchmarks/gemini_events.py \
  --video ~/Videos/proxy/bruto_proxy1080.mp4 --window 60 --fps 2
```

### O que a API oferece de controle (o que importa aqui)

| controle | pra que serve |
|---|---|
| `VideoMetadata(start_offset, end_offset)` | manda **uma janela** do arquivo já enviado, sem re-upload. É o que limita o erro de timestamp ao tamanho da janela |
| `VideoMetadata(fps)` | taxa de amostragem. O default de **1 quadro/s** é grosso demais pra achar o instante em que alguém sai de quadro |
| `response_schema` | fixa o formato da resposta (enum de tipos, números). Acaba com JSON pra consertar |
| `media_resolution` | LOW/MEDIUM/HIGH — troca custo por detalhe. LOW já basta pra "tem gente no quadro?" |
| Files API | 2 GiB por arquivo, vive 48h. O handle é reaproveitável entre chamadas — daí valer a pena cachear |

### O resultado

Testado nos primeiros 120s do vídeo da geladeira, onde o gabarito já era
conhecido (vem do nosso planner, ancorado nos timestamps do Whisper):

| evento real | detector por janela | erro |
|---|---|---|
| 8,4–14,1 se posicionando no quadro | 7,5–12,5 | ~1,5s |
| 58,0–64,2 levanta e ajusta a câmera | 58,0–64,0 | ~0,2s |
| 107,4–110,2 mexendo no microfone de lapela | 104,5–109,0 | ~2,5s |
| 20,9–23,3 repetição de fala (**áudio**) | *não relatou* | correto — foi instruído a não opinar sobre áudio |

Erro de 1–3 segundos, contra **3 minutos** quando o mesmo modelo planejava o
vídeo inteiro de uma vez. E ele se absteve corretamente do evento que era só de
áudio, onde os nossos timestamps são melhores.

Custo medido: **21k tokens / 70s** para 120s de vídeo em 2 janelas — extrapolando,
~124k tokens e ~7 min para os 12 minutos inteiros.

### Detalhe de implementação que não é opcional

Um evento em cima da fronteira volta partido em dois ("58–60" numa chamada,
"60–64" na seguinte). `merge_across_windows()` junta findings do mesmo tipo que
se tocam. Sem isso, o mesmo momento aparece duas vezes e nenhuma das duas com a
duração certa.

### Onde isso encaixa no pipeline

O ponto cego do nosso planner é exatamente este: **o que a câmera vê e o
microfone não conta.** A leitura dos dois experimentos é que o Gemini não deve
decidir cortes — ele deve reportar eventos visuais com timestamp aproximado, e
o nosso planner (que tem timestamp por palavra) decide. O caminho natural é
esses eventos entrarem no prompt do planner como mais um sinal, do lado do mapa
de energia.
