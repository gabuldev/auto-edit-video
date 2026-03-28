# /edit-video

Guia interativo para iniciar uma edição de vídeo com as opções certas.

## O que fazer

### Passo 1 — Identificar o arquivo de vídeo

Se o usuário passou um argumento com caminho de arquivo, usar esse arquivo diretamente.

Se não passou, verificar se existe alguma pasta `upload/` com vídeos:
```bash
ls upload/ 2>/dev/null
```

Se existir, listar os vídeos encontrados e perguntar qual processar.

Se não existir pasta upload, perguntar: "Qual o caminho do arquivo de vídeo?"

Validar que o arquivo existe antes de continuar. Formatos aceitos: `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.m4v`

### Passo 2 — Tipo de vídeo

Perguntar:
```
Qual o tipo do vídeo?
  [1] Short / Reels / TikTok  (vertical, até 3 min, com legendas)
  [2] YouTube / Long-form     (horizontal, sem legendas automáticas)
```

### Passo 3 — Contexto para o planner

Este é o campo mais importante — é o que o AI usa para tomar decisões de corte.

Perguntar: "Sobre o que é esse vídeo? Descreva em 1-3 frases."

Dar exemplos se o usuário não souber:
- "Tutorial de montagem de impressora 3D, tom técnico mas acessível"
- "Vlog de viagem para Japão, energia alta, público jovem"
- "Review de produto de tech, foco em comparação com concorrente"

Se o usuário der uma descrição vaga (ex: "um vídeo meu"), fazer uma pergunta de follow-up:
"Qual o tema principal e o tom que você quer passar?"

### Passo 4 — Qualidade do áudio (modelo Whisper)

Mostrar as opções com contexto real:
```
Qualidade da fala no vídeo:
  [1] tiny   — áudio limpo, fala clara, sem sotaque forte  (mais rápido)
  [2] base   — áudio razoável, pequenos ruídos  (recomendado)
  [3] small  — áudio com ruído de fundo ou sotaque  (mais preciso)
  [4] medium — áudio difícil, múltiplos falantes  (lento)
```

Se o usuário não souber, recomendar `base`.

### Passo 5 — Opções avançadas (opcional)

Perguntar: "Quer configurar opções avançadas? (legendas, iterações de revisão)"

Se sim:
- Para shorts: "Cor de destaque das legendas? (padrão: laranja)"
- "Quantas rodadas de revisão pelo avaliador? (padrão: 3, mín: 1)"

Se não, usar defaults.

### Passo 6 — Confirmar e executar

Mostrar o comando que será executado:
```
Vou rodar:
  auto-edit short upload/meu-video.mp4 \
    --context "Tutorial de impressora 3D, tom técnico" \
    --whisper-model base \
    --max-iter 3

Confirmar? [S/n]
```

Se confirmar, executar o comando e acompanhar o output.

Informar ao usuário que pode acompanhar o progresso com `/edit-status` em outra janela.

### Passo 7 — Após iniciar

Mostrar onde o output ficará:
```
Pipeline iniciado! Acompanhe com /edit-status
O vídeo final será salvo em: output/<nome-do-video>_final.mp4
```

## Notas

- Nunca executar sem confirmar com o usuário no Passo 6.
- Se o vídeo já tiver um workspace existente (pipeline.json), avisar:
  "Este vídeo já tem um pipeline em andamento (stage: X). Quer continuar de onde parou com /fix-stage, ou iniciar do zero?"
- Para batch processing de uma pasta, sugerir `auto-edit batch` em vez de rodar um por um.
