# Análise — nosso planner vs Gemini agentic video

Escrito à mão a partir do que os dois cortes renderizados mostram. Os números
estão em [`report.md`](report.md); aqui está o que eles significam.

**Vídeo:** review de geladeira portátil ALL WILD, 11:47 de bruto, DJI 4K
(rodado num proxy 1080p — ver "Fonte" no report).

## O resultado em duas linhas

Nosso braço **cortou 109s mais de vídeo e ainda preservou 57 palavras mais de
fala** (178,4s removidos / 1488 palavras contra 69,4s / 1431). O que a gente
tirou era silêncio; o que o Gemini tirou era conteúdo. E ele deixou o **dobro**
de tempo morto no corte final: 187,3s contra 91,6s.

## O erro que decidiu: ancoragem temporal, não julgamento editorial

O Gemini descreveu **corretamente** o evento mais cortável do vídeo — o
apresentador sai de quadro para ligar a geladeira na tomada — e então colocou
esse evento no **lugar errado da timeline**, errando por cerca de 3 minutos:

| | onde cada um pôs "ele saiu pra ligar na tomada" |
|---|---|
| nosso | 7:37.9–8:17.5 (39,5s) |
| Gemini | 10:48.0–11:46.9 (58,9s) |

A transcrição do Whisper resolve a disputa. Na janela do Gemini (648–707s) há
**sete falas seguidas**, e são as mais valiosas do vídeo:

> "*eu vou fazer um outro vídeo dela funcionando no carro*" · "*Tanto ela conta
> a Starlink... quando desligar o carro ela ainda vai continuar gelando*" ·
> "*deixa aqui nos comentários que eu tento responder*" · "*se vocês também têm
> geladeiras automotivas deixem aqui o feedback*" · "*espero que vocês tenham
> gostado desse tipo de conteúdo*"

Na janela do nosso planner (457,7–497,2s) há **silêncio literal** entre duas
frases: "Mas aí eu só ligar na tomada aqui" → 39,5s → "Olha, deixa eu mostrar
para vocês".

Os frames confirmam, e são o oposto do que o Gemini afirmou:

| frame | o que tem | quem cortou |
|---|---|---|
| [470s](evidencia/470s_sala-vazia_nosso-cortou.jpg) | sala vazia, apresentador fora de quadro | **nós** ✅ |
| [680s](evidencia/680s_voce-falando_gemini-cortou.jpg) | apresentador em quadro, falando | **Gemini** ❌ |

O Gemini justificou o corte como "*quase 1.5 minuto de cena vazia com ruídos de
fundo e nenhum conteúdo para o espectador*". É factualmente falso — e essa é a
parte perigosa para um pipeline automatizado: não é um corte discutível, é
perda de conteúdo com justificativa confiante.

Ele também escreveu em `dropped_blocks` que o bloco terminava em **13:36.5**,
num vídeo de 11:47. O `normalize()` do harness cortou para a duração real; sem
isso o executor receberia uma fronteira fora da timeline.

## A hipótese do teste não se confirmou

A motivação era: *nosso planner é cego (lê só a transcrição), então ver o vídeo
deve ser a vantagem decisiva.* Aconteceu o inverso — e onde mais dói, porque
foram justamente os eventos **visuais** que o modelo que estava olhando deixou
passar:

| frame | o que tem | Gemini |
|---|---|---|
| [11s](evidencia/011s_se-posicionando_gemini-manteve.jpg) | entrando no quadro, cabeça baixa, se posicionando | manteve |
| [108s](evidencia/108s_mexendo-no-microfone_gemini-manteve.jpg) | as duas mãos no peito, ajustando o microfone de lapela no meio da frase | manteve |

Nosso planner cortou os dois **sem nunca ver a imagem** — porque os dois vêm
com silêncio, e o mapa de energia denuncia (-40 a -53 dB nesta gravação).

## O plano do Gemini é quase um subconjunto do nosso

| | |
|---|---|
| cortes nossos que o Gemini também fez | **3 de 24** |
| cortes do Gemini que nós também fizemos | **3 de 4** |
| cortes nossos que o Gemini ignorou por completo | **21** |

Três dos quatro cortes dele nós já fazíamos. O quarto — o único que ele
"descobriu" sozinho — é o que estava no lugar errado. Ele não trouxe nenhuma
percepção que a gente não tivesse; trouxe um erro que a gente não tem.

O gargalo, então, não é percepção nem gosto editorial: é **granularidade**
(4 cortes num vídeo que pedia 24) e **ancoragem** (o único corte próprio caiu
3 minutos fora de lugar).

## Ressalvas contra a nossa própria conclusão

- **n=1.** Um vídeo, 12 minutos, um formato, um idioma. Vale para este vídeo;
  não generaliza.
- **Nosso braço competiu abaixo do normal:** rodou com a transcrição **crua** do
  Whisper, porque a correção de texto estourava um timeout de 60s (bug
  corrigido depois — `AUTO_EDIT_CORRECTION_TIMEOUT`).
- **Uma passada só para ele.** Nosso resultado é `planner` + `reviewer` +
  `snap`. O Gemini teve um passe único, sem revisão e sem reparo prévio.
- **Proxy 1080p, não o master 4K** — necessário porque a Files API corta em
  2 GiB. Não deve afetar decisão de corte, mas está dito.

## O que isso sugere fazer com a API

Se o problema é ancoragem e não percepção, a leitura é que **o Gemini não deve
decidir cortes** — ele deve reportar o que vê, e quem decide continua sendo
quem tem timestamps confiáveis. Duas hipóteses testáveis, em ordem de custo:

1. **Âncora:** dar a ele o vídeo **mais** a transcrição com timestamps por
   palavra. Se a colocação corrigir, o problema era só ancoragem.
2. **Detector por janela:** em vez de pedir um plano de 12 minutos, perguntar
   por janelas curtas (a API aceita `video_metadata` com offset de início/fim),
   pedindo apenas *eventos visuais* — "fora de quadro", "mexendo no
   equipamento", "tela travada", "take perdido". O erro de timestamp fica
   limitado ao tamanho da janela por construção, e o resultado entra como sinal
   extra no nosso planner, que segue dono da decisão.

A segunda é a que tem cara de virar produto: cobre exatamente o ponto cego do
nosso pipeline (o que a câmera vê e o microfone não conta) sem entregar a ele a
parte em que ele erra.

## Adendo — a hipótese 2 foi testada e funciona

`benchmarks/gemini_events.py` implementa o detector por janela (60s por
chamada, 2 fps, `response_schema`, timestamps relativos à janela e somados por
nós). Rodado nos primeiros 120s, onde o gabarito já era conhecido:

| evento real | detector | erro |
|---|---|---|
| 8,4–14,1 se posicionando | 7,5–12,5 | ~1,5s |
| 58,0–64,2 levanta e ajusta a câmera | 58,0–64,0 | ~0,2s |
| 107,4–110,2 mexendo no microfone | 104,5–109,0 | ~2,5s |
| 20,9–23,3 repetição de fala (áudio) | não relatou | correto |

Erro de 1–3 segundos contra os 3 minutos do experimento 1 — **mesmo modelo,
mesma gravação**. O que muda é só o tamanho da pergunta e o fato de o timestamp
ser relativo a uma janela curta em vez de absoluto num vídeo de 12 minutos.

Saída completa em [`eventos_visuais_0-120.json`](eventos_visuais_0-120.json).
Custo: 21k tokens e 70s para 120s de vídeo (~124k tokens / ~7min extrapolando
para o vídeo inteiro).

Conclusão prática: o Gemini vira um **sensor**, não um decisor. Os eventos
entram no prompt do planner como mais um sinal, ao lado do mapa de energia, e
quem escolhe o corte continua sendo quem tem timestamp por palavra.
