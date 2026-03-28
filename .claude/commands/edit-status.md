# /edit-status

Mostra o status de todos os pipelines de edição de vídeo no projeto.

## O que fazer

1. Listar todos os workspaces existentes:
   ```bash
   ls workspace/
   ```

2. Para cada workspace encontrado, ler o `pipeline.json`:
   ```bash
   cat workspace/<nome>/pipeline.json
   ```

3. Montar um dashboard formatado com estas colunas:
   - **Workspace** — nome do vídeo
   - **Status** — ícone + stage atual
   - **Progresso** — quantos stages completos / total
   - **Iteração** — se estiver em loop de avaliação
   - **Tempo** — quando foi criado ou última atualização

4. Usar estes ícones por status:
   - `done` → ✅
   - `running` → 🔄
   - `failed` → ❌
   - `pending` (com stages completos) → ⏸️
   - `pending` (recém criado) → 🆕

5. Se algum stage tiver campo `"error"` no pipeline.json, mostrar um resumo do erro em vermelho abaixo da linha.

6. Ao final mostrar um resumo:
   - Quantos vídeos prontos
   - Quantos em progresso
   - Quantos com falha

## Exemplo de output esperado

```
📊 Auto-Edit Pipeline Status
─────────────────────────────────────────────────────
✅  impressora-3d          done           9/9   iter 1   (Mar 17)
🔄  DJI_0780              execute        5/9   iter 2   (agora)
❌  tutorial-react        execute        4/9   iter 1   (Mar 19)
    └─ erro: kept_segments[0] end=9999 exceeds duration 63.4s
⏸️  novo-video            plan           1/9   iter 1   (Mar 27)
─────────────────────────────────────────────────────
✅ 1 pronto  🔄 1 rodando  ❌ 1 com falha  ⏸️ 1 pausado
```

## Notas

- Se não existir nenhum workspace, avisar que nenhum pipeline foi iniciado ainda.
- Ordenar por `created_at` do pipeline.json (mais recente primeiro).
- Se o campo `current_stage` for `"done"`, buscar o arquivo final em `output/` e mostrar o nome.
