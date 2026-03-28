# /fix-stage

Diagnostica e corrige automaticamente um pipeline com stage falhado.

## Argumento

O usuário pode passar o nome do workspace como argumento: `/fix-stage DJI_0780`

Se não passar, listar os workspaces com status `failed` e perguntar qual corrigir.

## O que fazer

### Passo 1 — Identificar o workspace com falha

Se argumento fornecido:
```bash
cat workspace/<argumento>/pipeline.json
```

Se não fornecido, listar workspaces com falha:
```bash
for d in workspace/*/; do
  stage=$(python auto_edit/pipeline.py get-stage "$d" 2>/dev/null)
  echo "$d $stage"
done
```
Ler os `pipeline.json` e encontrar os que têm algum stage com `"status": "failed"`.

### Passo 2 — Ler o erro

No `pipeline.json`, encontrar o stage com `"status": "failed"` e ler o campo `"error"` se existir.

Também verificar se existem arquivos relevantes no workspace:
- `reviewed_plan.json` — se o stage era `execute`
- `cut_plan.json` — se o stage era `review`
- `transcription.json` — se o stage era `plan`

### Passo 3 — Diagnosticar a causa

Com base no stage falhado e na mensagem de erro, classificar o problema:

| Stage | Erro típico | Causa provável |
|-------|------------|----------------|
| `extract` | ffmpeg not found | FFmpeg não está no PATH |
| `extract` | Whisper error | Modelo Whisper não baixado |
| `plan` / `review` | timeout / JSON inválido | LLM travou ou retornou resposta mal formatada |
| `execute` | kept_segments[N] end=... | LLM gerou bounds inválidos no cut plan |
| `execute` | All kept segments shorter | Todos os intervalos menores que 1 frame |
| `caption` | FileNotFoundError | edited_video.mp4 não existe (execute não completou) |
| `overlay` | No overlay files found | Assets não estão em assets/overlays/ |
| `evaluate` | timeout | LLM travou na avaliação |

### Passo 4 — Propor a correção

Explicar o diagnóstico em linguagem clara e propor a ação de correção:

**Para erros de LLM (plan/review/evaluate):**
```
O stage "plan" falhou porque o LLM retornou JSON inválido.
Correção: Re-executar o stage com:
  auto-edit resume <video> --from plan
```

**Para erros de bounds inválidos no execute:**
```
O planner gerou um segmento com end=9999 mas o vídeo tem 63s.
Correção: Re-executar a partir do plan para gerar um novo cut plan:
  auto-edit resume <video> --from plan
```

**Para erros de arquivo faltando:**
```
edited_video.mp4 não existe. O stage "execute" não completou.
Primeiro corrigir o execute:
  auto-edit resume <video> --from execute
```

**Para erros de overlay:**
```
Nenhum overlay encontrado em assets/overlays/
Copiar os assets para a pasta correta:
  auto-edit sync-overlays
Ou pular o overlay e continuar:
  auto-edit resume <video> --from caption
```

### Passo 5 — Executar com confirmação

Perguntar ao usuário: "Posso executar `auto-edit resume ...` agora?"

Se confirmar, executar o comando de correção.

## Notas

- Se o erro não for reconhecido, mostrar a mensagem de erro completa e sugerir que o usuário reporte.
- Nunca editar `pipeline.json` diretamente sem avisar o usuário.
- Se o vídeo original não existir mais no path original, avisar que o arquivo de entrada foi movido.
