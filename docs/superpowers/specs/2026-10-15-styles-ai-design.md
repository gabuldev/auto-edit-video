# Estilos fase 3 — criados pela IA, paleta do logo, exportar/importar

Data: 2026-10-15 · Branch: `feat/styles-ai`

## Objetivo

Com várias pessoas usando o app, cada uma deve chegar num estilo com a cara do
canal sem ajustar token por token, e conseguir compartilhar esse estilo.

Sucesso:
- Um estilo gerado pela IA aparece com prévia real e é editável como qualquer outro.
- Um arquivo exportado, importado em outra máquina, fica idêntico.
- "Usar cores do logo" dá uma paleta coerente em um clique.

## Restrições

- Estilo = dados (`auto_edit/styles.py`, `validate()`). A IA só preenche tokens
  existentes; nada de layout novo nem código.
- Agentes (`auto_edit/agents.py`) são só texto. Imagem de referência vira
  **cores extraídas localmente**, passadas como texto. Funciona com todo agente;
  a IA não vê forma/tipografia da referência (aceito).
- Nada salva sozinho: geração devolve um rascunho.
- Exportação não leva marca (nome, @, logo).

## 1. Paleta — `auto_edit/palette.py` (novo, Pillow)

- `extract(image: Path | bytes, n=5) -> list[str]`: reduz (thumbnail ~128px),
  descarta pixels com alpha < 128, quantiza (`Image.quantize`, median cut),
  descarta quase-branco/quase-preto/cinza (saturação HSV < 0.15 ou valor fora de
  [0.12, 0.95]), ordena por frequência × saturação. Retorna hex `#rrggbb`. Pode
  retornar lista vazia.
- `suggest(colors) -> {accent, panel, text} | None`: accent = cor mais saturada;
  panel = mesmo matiz, valor ~0.12, saturação ~0.6; text = `#ffffff` ou `#111111`
  pelo maior contraste WCAG contra o panel. `None` se `colors` vazio.

## 2. Geração — `agents/stylist.md` + `styles.generate()`

`styles.generate(description: str, image: bytes | None = None, *, cli=None) -> dict`

- Monta o prompt: descrição, cores extraídas da imagem (se houver), nome do
  canal (`render.brand()`), e o contrato: chaves de `FONTS`, `ICONS`,
  `POSITIONS_LT`, `POSITIONS_CTA`, limites numéricos (`panel_opacity` 0.3–1,
  `radius` 0–60, `speed` 0.5–2), CTA até 3 passos com texto ≤ 24 caracteres.
- Roda via `agents.invoke` (primário → `AUTO_EDIT_LLM_FALLBACK`), timeout 120s.
- Lê o primeiro objeto JSON da saída (tolerante a cercas ```json).
- Retorna `{"name", "description", "tokens": validate(...)}`. Nome vazio vira
  "Estilo IA". Saída sem JSON nenhum → `StyleError("a IA não devolveu um estilo")`.

## 3. Exportar / importar — `styles.py`

- Formato do arquivo `.autoedit-style.json`:
  `{"format": 1, "name", "description", "tokens"}`.
- `export(style_id) -> dict` (presets também exportáveis).
- `import_(data: dict) -> dict`: exige `format == 1` e `tokens` dict, senão
  `StyleError("arquivo não é um estilo do Auto-Edit")`. Passa por `validate()` e
  salva com id novo via `save(...)`. Nome repetido ganha sufixo " (2)".

## 4. API — `auto_edit/api.py`

| Rota | Corpo | Resposta |
|------|-------|----------|
| `POST /api/styles/generate` | `{description, image?}` (data URL) | `{job_id}`; o evento `done` do SSE traz `{name, description, tokens}` |
| `POST /api/styles/palette` | `{image?}` (sem → logo salvo) | `{colors, suggested}` |
| `GET /api/styles/<id>/export` | — | JSON do arquivo, `Content-Disposition: attachment` |
| `POST /api/styles/import` | `{file}` (o JSON do arquivo) | o estilo salvo |

Geração usa o `JobManager` do engine (mesmo padrão do clipper) com um job sem
vídeo associado. Descrição vazia e sem imagem → 400.

## 5. App — `desktop/ui/js/styles.js`

- Galeria: card **"✨ Criar com IA"** → painel com textarea, anexar imagem
  (opcional), "Gerar" com progresso. Resultado abre no editor como rascunho
  (fluxo `startEditing` existente), prévias reais atualizam. Erro no painel.
- Editor, bloco de cores: **"Usar cores do logo"** (só com logo salvo) → aplica
  `suggested` no rascunho. Sem cor marcante → aviso inline.
- Detalhe: **"Exportar"** → diálogo de salvar do Tauri.
- Galeria: **"Importar"** → seletor de arquivo → `POST /import` → seleciona o novo.

## 6. CLI — `auto-edit style`

- `style generate "descrição" [--image ref.png] [--save] [--activate]`
- `style export <id> [-o arquivo]`
- `style import <arquivo> [--activate]`

## Erros

- IA falha (primário + fallback) → mensagem no painel/CLI, sem rascunho.
- Import inválido → "arquivo não é um estilo do Auto-Edit".
- Paleta vazia → "sem cor marcante na imagem".

## Testes

- `tests/test_palette.py`: imagens sintéticas (cor sólida, transparente com
  logo, só cinza → vazio), contraste do `text`.
- `tests/test_styles.py`: `generate` com agente falso (JSON válido, JSON em
  cerca, lixo parcial → defaults, sem JSON → erro); export/import ida e volta,
  formato errado, nome duplicado.
- `tests/test_api.py`: as 4 rotas (generate com agente falso).
- `scripts/smoke_engine.py`: passo "palette from logo".
- Docs: CLAUDE.md (rotas, CLI), README (bullet Estilos).

## Fora de escopo

Galeria comunitária no repo, legendas seguindo o estilo, perfis multi-marca,
fonte própria, layouts React da comunidade.
