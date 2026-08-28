# Shorts derivados de um vídeo long

**Data:** 2026-08-27
**Status:** aprovado, aguardando plano de implementação

## Problema

Depois que `auto-edit long` termina, o vídeo editado guarda vários momentos que
funcionariam sozinhos como Reels/Shorts. Hoje não há como extraí-los: rodar
`auto-edit short` no mesmo arquivo faz o planner de short apenas limpar
silêncio, porque ele não seleciona highlights — ele limpa um take que já
deveria estar bem escolhido.

## Ideia central

Um short derivado é um pipeline `short` **normal** cujo "vídeo original" é o
long já editado e cuja "transcrição" é o `post_cut_transcription.json` do long.

Os dois artefatos vivem no mesmo timeline pós-corte, então executor, captioner,
metadata e thumbnailer funcionam sem nenhuma alteração. O código novo se limita
ao comando, ao prompt do agente e ao seed do workspace derivado.

## Decisões

| Decisão | Escolha | Por quê |
|---|---|---|
| Fonte do corte | Vídeo long já editado | Herda limpeza de silêncio e loudnorm; sem re-encode do 4K bruto; timestamps já batem com a transcrição pós-corte |
| Trigger | Comando separado | Não mexe em `STAGES` (nenhum `pipeline.json` existente fica com stage faltando); dá pra rodar de novo com outra seleção sem refazer o long |
| Seleção | Agente propõe, humano aprova | Descobrir que nenhum momento presta custa poucos tokens; evita encode de 4K num short ruim |
| Reframe | Center-crop, o que já existe | Reusa `_reframe_vf`; funciona pra talking-head com câmera parada |
| Entrega | Pipeline short completo | Corte + legendas + thumbnail + metadata, reusando os stages atuais |

## Fonte exata do vídeo

A fonte é `<ws_long>/edited_video.mp4`, **não** `output/<stem>_final.mp4`.

- O `_final.mp4` tem o cover frame no início (2 frames, ~67ms). Usá-lo
  deslocaria todas as legendas em 67ms.
- `_cleanup_workspace` só apaga `edited_video.mp4` quando `type == "short"`,
  então num workspace de long o arquivo sobrevive.
- `edited_video.mp4` não tem os overlays de CTA, que não fazem sentido dentro
  de um short.

Se o arquivo não existir (workspace limpo à mão), o comando falha pedindo
`auto-edit resume <video> --from execute`.

## Fluxo

### Fase 1 — propor

```
auto-edit shorts <video>
```

1. Resolve o workspace do long com `get_workspace`. Falha se não existe
   `pipeline.json` ou se `current_stage != "done"`.
2. Agente `agents/clipper.md` lê `post_cut_transcription.json`, o `context` do
   pipeline e o `metadata.json` do long.
3. Escreve `clips_plan.json` no workspace do long.
4. Imprime a tabela de candidatos no terminal e para. Nada é cortado.

### Fase 2 — cortar

```
auto-edit shorts <video> --pick 1,3
```

Lê o `clips_plan.json` já existente — sem nova chamada de LLM. Para cada clipe
escolhido monta um workspace derivado e roda `ralph.sh` a partir do `execute`.

## `clips_plan.json`

Escrito no workspace do long.

```json
{
  "source_duration": 378.75,
  "clips": [
    {
      "start": 0.0,
      "end": 42.3,
      "hook": "a impressora parava de reconhecer o AMS — a solução é não atualizar",
      "reason": "problema e solução completos, sem depender de contexto anterior",
      "score": 8,
      "self_contained": true
    }
  ]
}
```

`score` é 0–10 e serve só pra ordenar a tabela.

## Regras do clipper

- Alvo de 20–60s; máximo rígido de 90s, ajustável por `--max-dur`.
- Auto-contido: o clipe precisa fazer sentido pra quem nunca viu o long. Nada
  de "como eu falei ali atrás".
- Gancho nos primeiros ~3s.
- Fronteiras em limite de palavra do `post_cut_transcription.json`. O encaixe é
  feito por `shorts.snap_clip_to_words`, e **não** por `auto_edit.snap`: o
  `snap_plan` termina em `rebuild_kept(cuts, duration, ...)`, e
  `rebuild_kept([], 378.75)` — que é o caso aqui, já que o plano sintético não
  tem cortes — devolve o long inteiro, apagando em silêncio a janela do clipe.
  O `snap_clip_to_words` encaixa só a janela: puxa o início pra frente até o
  começo de uma palavra e o fim pra trás até o fim de uma palavra, considerando
  apenas palavras **inteiramente contidas** na janela (uma palavra que cruza a
  borda é ignorada; janela sem nenhuma palavra contida volta intacta).
- Candidatos podem se sobrepor (você escolhe um dos dois), mas a sobreposição é
  sinalizada na tabela.

## Interface

| Comando | Efeito |
|---|---|
| `auto-edit shorts <video>` | Propõe, escreve `clips_plan.json`, imprime a tabela, para |
| `auto-edit shorts <video> --pick 1,3` | Corta os escolhidos a partir do plano existente |
| `auto-edit shorts <video> --all` | Corta todos os candidatos |
| `auto-edit shorts <video> --replan` | Força novo clipper por cima do plano antigo |
| `--max-dur N` | Duração máxima de um clipe (default 90) |

## Workspace derivado

`workspace/<stem>_short<N>/`, criado com:

| Arquivo | Conteúdo |
|---|---|
| `pipeline.json` | `type: "short"`, `video_path` = `<ws_long>/edited_video.mp4`, `video_name` = `<stem>_short<N>`, `context` = contexto do long + o `hook` do clipe |
| `transcription.json` | Cópia do `post_cut_transcription.json` do long |
| `reviewed_plan.json` | `{"cuts": [], "kept_segments": [{"start": S, "end": E, "summary": hook}], "approved": true}` |

Stages marcados `skip`: `extract`, `plan`, `review`, `overlay`, `evaluate`.
Rodam normalmente: `execute`, `caption`, `metadata`, `thumbnail`.

`video_name` **precisa** ser sobrescrito. `pipeline.init` o deriva de
`video_path.stem`, o que daria `edited_video` pros dois campos que importam:
`finalize` escreveria `output/edited_video_final.mp4` e cada short sobrescreveria
o anterior. Pela mesma razão o seed cria o diretório do workspace diretamente,
sem passar por `get_workspace`/`init_workspace` — essas funções também derivam o
nome do stem do arquivo de vídeo.

O comando invoca `ralph.sh` no workspace derivado diretamente, e não
`_run_pipeline`, que resolveria o workspace pelo stem e reinicializaria o
`pipeline.json` que acabamos de montar.

Saída: `output/<stem>_short<N>_final.mp4`, mais `.srt`, thumbnail e `.txt` de
metadata, exatamente como qualquer short.

### Por que `evaluate` fica `skip`

`pipeline.loop_back` define `current_stage = "plan"` incondicionalmente, mesmo
com o stage marcado `skip`. Num workspace derivado isso re-planejaria a partir
da transcrição inteira do long e destruiria a janela do clipe. A curadoria do
clipper mais a aprovação humana já são o portão de qualidade; um evaluator com
loop quebrado seria pior que nenhum.

Fazer `loop_back` respeitar `skip` é uma melhoria real, mas é mudança no núcleo
do pipeline e fica fora deste escopo.

## Precondições e erros

| Situação | Mensagem |
|---|---|
| Sem `pipeline.json` no workspace do long | Rode `auto-edit long <video>` primeiro |
| `current_stage != "done"` | Pipeline do long não terminou; mostra o stage atual |
| `edited_video.mp4` ausente | Rode `auto-edit resume <video> --from execute` |
| `--pick` sem `clips_plan.json` | Rode sem `--pick` primeiro pra gerar os candidatos |
| Índice de `--pick` fora de faixa | Lista os índices válidos |
| Clipe com `end <= start`, fora do vídeo, ou acima de `--max-dur` | Rejeitado com o índice e o motivo; os demais seguem |

## Testes

Unitários, sem FFmpeg, no padrão de `tests/test_executor.py`:

- Validação do `clips_plan.json`: janela fora do vídeo, `end <= start`, duração
  acima do teto, lista vazia.
- Seed do workspace derivado: stages certos em `skip`, `reviewed_plan`
  sintético bem formado, `video_path` apontando pro `edited_video.mp4`,
  `video_name` distinto por clipe (dois shorts do mesmo long não colidem no
  `output/`), contexto herdado.
- Parse do `--pick`: índices inválidos, duplicados, fora de faixa.
- Resolução da fonte e cada mensagem de precondição.

## Fora de escopo

- Detecção de rosto pra centralizar o crop.
- Offset de crop por clipe.
- Cortar do vídeo bruto original.
- Flag `--shorts N` no comando `long`.
- Fazer `loop_back` respeitar stages `skip`.
