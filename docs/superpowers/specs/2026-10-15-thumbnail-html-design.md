# Thumbnail configurável — layout em HTML escrito pela IA

Data: 2026-10-15 · Branch: `feat/styles-ai` (continua a fase 3,
`2026-10-15-styles-ai-design.md`)

## Objetivo

"Criar um estilo" tem que criar o estilo de verdade: texto, fonte, posição e
os elementos na tela, não só as cores. A pessoa manda uma imagem de referência
(ex.: uma thumbnail do YouTube) e a thumbnail gerada segue aquele layout.
Elementos são opcionais por estilo: um estilo pode ter só frame + título,
outro pode ter um segundo frame num círculo, etiqueta, logo.

Não existe catálogo fixo de opções ("posição do título", "tem círculo?"): isso
não escala. O layout é **HTML + CSS escrito pela IA**, desenhado pelo Satori.

Sucesso:
- Com uma referência, a thumbnail gerada reproduz o layout dela (posições,
  tamanhos, fontes, contorno, elementos), com o frame e o título do vídeo.
- Pedir "título maior, tira o círculo" ajusta o layout atual.
- O arquivo exportado leva o layout; importado em outra máquina, fica igual.
- Se o layout falhar, a thumbnail sai do mesmo jeito (layout padrão).

## Escopo

- Só a **thumbnail long (16:9)**. Lower third e CTA continuam nos tokens de
  hoje. Shorts (9:16) continuam no layout padrão.
- Fica: export/import, cores do logo, colar/arrastar imagem, remover imagem.
- Sai da criação: a extração local de cores da referência
  (`palette.extract` continua existindo, usada por "usar cores do logo").

## 1. Layout no estilo — `tokens.thumbnail.html`

- Token opcional `tokens["thumbnail"]["html"]: str`. Sem ele, a thumbnail usa
  o layout React de hoje (`Thumbnail.tsx`). `accent_from` continua.
- HTML com CSS inline (`style="..."`), pensado em **1280×720**. Elemento raiz
  ocupa a tela toda.
- Lacunas (substituídas na hora de desenhar):

| Lacuna | Vira |
|---|---|
| `{{titulo}}` | título da thumbnail (texto) |
| `{{etiqueta}}` | texto curto de apoio (pode ser vazio) |
| `{{frame}}` | frame principal do vídeo (data URL) |
| `{{frame2}}` | segundo frame, de outro momento (data URL) |
| `{{rosto}}` | recorte do rosto, PNG transparente (data URL) |
| `{{logo}}` | logo da marca (data URL) |
| `{{destaque}}` | cor de destaque (`accent` do estilo ou do assunto, conforme `accent_from`) |
| `{{cor.accent}}`, `{{cor.panel}}`, `{{cor.text}}` | cores do estilo |

  Imagem sem fonte (sem logo, sem rosto) → o elemento `<img>` some.
  Texto vazio → o elemento que só tem a lacuna some.
- **Ajuste do título:** o elemento do título leva
  `data-fit="linhas:2;min:60;max:160"` (linhas máximas, tamanho mín/máx em px).
  O renderer mede com a fonte real e escolhe o maior tamanho que cabe na caixa
  do elemento (largura/altura do `style`), como `fit()` em
  `renderer/src/text.ts` faz hoje. Sem `data-fit`, usa o `font-size` escrito.
- **Fontes:** só as do app. `font-family` aceita os rótulos de `FONTS`. Entram
  fontes display OFL novas: Luckiest Guy, Lilita One, Bangers, Archivo Black
  (TTF estático em `assets/fonts/`, com o `OFL-*.txt`). Fonte desconhecida vira
  a fonte de título do estilo.

### Limpeza ao salvar — `auto_edit/thumb_html.py` (novo)

`sanitize(html: str) -> str` roda no `validate()` (todo estilo salvo, gerado ou
importado passa por ele). `ThumbHtmlError(StyleError)` quando não sobra nada.

- Remove `<script>`, `<style>`, `<link>`, `<iframe>`, `<object>`, `<svg>`,
  atributos `on*`, comentários.
- `src` de `<img>` só pode ser uma lacuna de imagem; outro valor → remove o
  `<img>`.
- `url(...)` em CSS: removido (nada externo, nada embutido).
- Tags permitidas: `div`, `span`, `p`, `img`. Atributos: `style`, `src`,
  `data-fit`.
- Limite de 20 000 caracteres.
- CSS fora do que o Satori entende é ignorado pelo Satori; não validamos
  propriedade por propriedade.

`placeholders(html) -> set[str]` diz quais lacunas o layout usa (o pipeline só
procura `{{frame2}}`/`{{rosto}}` se precisar).

## 2. Renderer — tipo `html`

- `renderer/src/cli.tsx`: `auto-edit-render html <spec.json> <out.png>` e
  `preview` com `kind: "thumbnail_html"`.
- spec: `{html, width, height, values: {titulo, etiqueta, destaque, cor.*},
  images: {frame, frame2, rosto, logo: caminho|null}, fonts: [{name, path}]}`.
- `renderer/src/html.ts` (novo): troca as lacunas (texto escapado), imagens
  viram data URL, some com o que ficou sem valor, aplica `data-fit`, converte
  com `satori-html` (dependência nova, versão fixa) e chama o Satori com as
  fontes pedidas.
- Erro de parse/render → exit 1 com o motivo (igual hoje).

## 3. Pipeline — `tools/thumbnailer.py`

- Estilo ativo com `thumbnail.html` → monta o spec `html` e chama o renderer.
- `{{frame2}}` só se o layout usa: o frame de melhor nota de **outro momento**
  (≥ 15% do vídeo de distância do principal), de preferência sem rosto,
  reaproveitando `_score_sharpness`/`_score_face_region`.
- Falhou → layout React padrão → Pillow (a thumbnail nunca deixa de sair).
  O motivo vai pro log.
- Short (9:16) ignora o `html`.

## 4. IA que vê imagem — `agents.complete(prompt, *, images=None, timeout)`

- `images: list[Path]`. Cada agente:
  - **claude:** copia as imagens pra uma pasta temporária, cita os caminhos no
    prompt, roda com `--add-dir <pasta> --allowedTools Read`.
  - **codex:** `exec -i <imagem>` (uma flag por imagem).
  - **openrouter:** mensagem com partes `image_url` (data URL).
  - **ollama:** campo `images` (base64); só se o modelo for de visão
    (`/api/show` → `capabilities` contém `vision`).
  - **cursor, agy, opencode:** sem visão.
- `VISION_AGENTS` + `sees_images(name) -> bool`.
- Com `images`, pula agentes sem visão: primário sem visão → tenta o fallback;
  nenhum vê → `AgentError(NO_VISION)` com
  "seu agente de IA não enxerga imagens — troque nas Configurações".
- Sem `images`, comportamento de hoje.

## 5. Criar a partir da referência — `styles.generate`

Vira um job (1–3 min) com progresso por SSE.

`styles.generate(description, image=None, *, complete=None, render=None,
on_progress=None, rounds=3) -> draft`

1. **Desenha:** prompt `agents/stylist.md` reescrito: contrato do layout
   (lacunas, `data-fit`, tags/CSS que o Satori entende, fontes disponíveis,
   1280×720), a descrição, a referência como imagem. Resposta: JSON
   `{name, description, tokens}` com `tokens.thumbnail.html` e as cores/fontes
   (os overlays herdam).
2. **Confere:** desenha a prévia com um frame real (o do vídeo mais recente,
   como a galeria) e o título do último vídeo (`metadata.json`; sem vídeo:
   frame neutro e "SEU TÍTULO AQUI").
3. **Compara:** prompt `agents/stylist_review.md`: a referência e a prévia
   como imagens, o HTML atual. Resposta: `{"ok": true}` ou
   `{"html": "..."}` corrigido. Até `rounds` voltas no total;
   `on_progress("volta 2/3")`.
4. Devolve o rascunho (nunca salva). HTML que não passa no `sanitize` numa
   volta → fica o da volta anterior; na primeira → erro "a IA não devolveu um
   layout válido".

- Sem imagem: igual, só que a volta 3 compara com a descrição (só a prévia
  como imagem). Agente sem visão + sem imagem → só o passo 1, sem voltas.
- **Ajustar com IA:** `styles.adjust(tokens, request, *, image=None, ...)`
  roda os passos 2–4 partindo do HTML atual com o pedido da pessoa.

## 6. API

- `POST /api/styles/generate` → `{job_id}` (antes era síncrono). SSE em
  `/api/jobs/<id>/events`: `progress` ("desenhando", "volta 2/3"), `done` com o
  rascunho, `error` com a mensagem.
- `POST /api/styles/adjust` `{tokens, request}` → `{job_id}`, mesmo formato.
- `POST /api/styles/preview/thumbnail` com `tokens.thumbnail.html` desenha o
  HTML.
- Corpo inválido (não objeto, descrição não texto) → 400.

## 7. App — `desktop/ui/js/styles.js`

- Criar com IA: progresso ao vivo no painel ("volta 2/3"); galeria travada
  enquanto roda (como hoje).
- Agente sem visão + imagem → aviso antes de rodar, com link pras
  Configurações.
- Editor:
  - **Ajustar com IA:** campo de pedido + botão; mesmo progresso.
  - **Avançado → Editar HTML:** textarea, prévia atualiza ao parar de digitar
    (debounce), erro de limpeza aparece embaixo.
  - "Voltar pro layout padrão" remove o `html`.
  - Cores e fontes de hoje continuam e mudam a thumbnail (lacunas de cor).

## 8. CLI

- `auto-edit style generate` mostra as voltas; `--rounds N`.
- `auto-edit style adjust <id> "pedido"` (salva como novo, `--save`).

## Erros

| Caso | Resultado |
|---|---|
| Agente sem visão, com imagem | aviso NO_VISION, nada roda |
| IA sem JSON / HTML inválido na 1ª volta | "a IA não devolveu um layout válido" |
| HTML inválido numa volta posterior | mantém a volta anterior |
| Renderer falha na prévia de uma volta | para as voltas, devolve o último HTML válido |
| HTML falha no pipeline | layout padrão → Pillow, motivo no log |
| Imagem de referência ilegível/grande | erro de hoje (`_image_bytes`) |

## Testes

- `thumb_html.sanitize`: tira script/style/link/on*/url(), `img` com src
  estranho, tag desconhecida; mantém lacunas; limite de tamanho;
  `placeholders()`.
- Renderer (`bun test`): lacunas, texto escapado, elemento some sem valor,
  `data-fit` encolhe título longo, fonte desconhecida cai na do estilo.
- `agents.complete(images=...)`: comando/corpo de cada agente (claude
  `--add-dir`, codex `-i`, openrouter `image_url`, ollama `images`), pulo de
  agente sem visão, NO_VISION.
- `styles.generate`: voltas com agente e renderer falsos (ok na volta 2 para,
  HTML ruim mantém o anterior, máx. de voltas, progresso).
- Thumbnailer: usa `html` quando há; `frame2` só se usado e de outro momento;
  cai pro padrão se o renderer falha.
- API: generate/adjust viram job; 400 em corpo inválido.
- Smoke (`scripts/smoke_engine.py`): desenha um HTML de exemplo.

## Fora de escopo

- Lower third e CTA em HTML (depois que esse motor estiver pronto).
- Shorts 9:16 com layout próprio.
- Biblioteca/loja de layouts da comunidade (o arquivo exportado já serve).
