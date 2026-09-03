# Benchmark de planner — DJI_0152_proxy1080.mp4

- **Fonte:** proxy `DJI_0152_proxy1080.mp4` (1920x1080 h264 yuv420p, 4.9 Mbps, 0.43 GB) — master `DJI_20260902101001_0152_D.MP4` (3840x2160 hevc yuv420p10le, 62.8 Mbps, 5.55 GB) não sobe na Files API
- **Contexto:** review da geladeira portatil ALL WILD que comprei pra usar no carro em viagem; manter a demonstracao do produto e os numeros de consumo/bateria; cortar setup, repeticoes de fala e tempo morto mexendo na camera
- **Nosso:** `agents/planner_long.md` lendo `transcription.json` (Whisper)
- **Gemini:** `gemini-3.7-flash` assistindo o arquivo, mesmo brief
- **Downstream idêntico:** `auto_edit.snap` + `tools/executor.py`

## Números

Bruto: **706.88s**

| métrica | nosso | gemini |
|---|---|---|
| duração final | 528.49s | 637.48s |
| removido | 178.39s | 69.4s |
| removido | 25.2% | 9.8% |
| cortes | 24 | 4 |
| trechos mantidos | 24 | 3 |
| corte mediano | 4.9s | 5.5s |
| maior corte | 39.3s | 58.88s |
| blocos descartados | 3 | 1 |
| palavras mantidas | 1488 | 1431 |
| palavras cortadas ao meio | 0 | 0 |
| silêncio no corte final | 91.6s | 187.3s |

**Concordância:** IoU 0.669 — 467.57s mantidos pelos dois, 60.92s só em nosso, 169.91s só em gemini.

> Nota: nesta rodada o braço nosso rodou com a **transcrição crua do Whisper** — a
> correção de texto estourou o timeout de 60s (corrigido depois, `AUTO_EDIT_CORRECTION_TIMEOUT`).
> Ou seja, o nosso braço competiu abaixo do seu normal.

## Reparo mecânico (snap)

Palavras cortadas ao meio pelo plano, antes e depois do snap:

| braço | antes | depois |
|---|---|---|
| nosso | 2 | 0 |
| gemini | 1 | 0 |

## Custo e tempo

| braço | tempo | tokens |
|---|---|---|
| nosso | reaproveitado de rodada anterior (extract ~150s + plan/review) | — |
| gemini | 385.96s | 67587 |

## O que cada um disse que ia fazer

**nosso:** 11min47 de bruto -> ~8min39 finais. O conteudo unico e denso e justifica um long: apresentacao do produto, capacidade/compartimentos, faixa de temperatura (-22C a 0C), as quatro voltagens (12V/24V/110/220), preco, app com modo eco/maximo e nivel de bateria, protecao contra descarregar o veiculo e a dica de pre-gelar. Nao ha bloco tematico grande de conteudo repetido, entao os ~3min07 cortados vem de tempo morto e repeticao: 40s parado ligando a geladeira na tomada, 24s sem fala no meio da demonstracao do compartimento (que o plano anterior deixou passar), 19s repetindo 'ela ta ligada aqui' e mexendo na camera, 19s de digressao sobre queijo da Canasta e os silencios longos espalhados.

**gemini:** 11.7min bruto reduzido para ~9.5min úteis: corte de 1.5min de tempo morto com sala vazia enquanto o apresentador busca a tomada, além de silêncios e transições de câmera.

## Arquivos

- **nosso:** `workspace\bench_geladeira-allwild_ours\edited_video.mp4`
- **gemini:** `workspace\bench_geladeira-allwild_gemini\edited_video.mp4`
