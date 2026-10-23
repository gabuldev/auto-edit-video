# Legendas editáveis (estilo + ajuste por vídeo)

## Por que

O app tem muita gente usando, no mundo todo. A legenda do short tem visual fixo
no código (`tools/captioner.py`, `DEFAULTS`): Montserrat negrito 14, branca com
contorno preto, palavra falada com contorno laranja, até 4 palavras,
MAIÚSCULAS, centralizada embaixo a 95px. Às vezes ela cai em cima do rosto. Não
dá pra saber o enquadramento de cada um, então quem usa ajusta: posição,
tamanho, fonte, cores, tudo.

Pedido do dono (aprovado nos rascunhos):
1. **No estilo** (tela Estilos → editor → aba "Legenda"): vale pra todos os vídeos.
2. **Por vídeo** (vídeo pronto → "Ajustar legenda"): arrastar a posição,
   tamanho, esconder; "Regravar legenda" refaz só a legenda.

## Metas

- Legenda faz parte do estilo (tokens `captions`), com prévia real.
- Cada um dos 16 estilos prontos traz uma legenda que combina com ele.
- Ajuste por vídeo sobrepõe o estilo só naquele vídeo e regrava rápido.
- O que a prévia mostra é o que sai no vídeo (mesmo motor: libass).

## Não metas

- Animações de entrada por palavra (pop, bounce), emojis, legenda em 2 cores
  por frase. Fica pra depois.
- Legenda no long (long continua sem legenda queimada; o .srt segue no publish).
- Editar o texto/timing das palavras (correção de transcrição). Outro projeto.
- Detectar o rosto e desviar a legenda sozinho. A pessoa ajusta.

## Anti-metas (falhou mesmo funcionando)

- Prévia diferente do vídeo final (fonte, tamanho ou posição).
- Vídeo antigo ou estilo da pessoa salvo antes disso mudar de layout/cores sem
  ela pedir: sem `captions`, sai com a mesma posição, tamanho, cores e
  contorno de hoje. (A fonte muda: ver "Fonte de hoje" abaixo.)
- Fonte que existe no Mac do dono mas não na máquina do usuário (Windows/Linux)
  caindo em Arial calada.

## Desenho

### 1. Tokens `captions` no estilo (`auto_edit/styles.py`)

Novo bloco em `DEFAULT_TOKENS`, validado em `validate()` como o resto
(valor ruim → default, nunca erro):

| campo | valores | default (= visual de hoje) |
|---|---|---|
| `position` | `top` / `middle` / `bottom` | `bottom` |
| `offset` | 0–40 (% da altura, distância da borda escolhida; ignorado em `middle`) | equivale aos 95px de hoje |
| `size` | 50–200 (% do tamanho base) | 100 |
| `font` | id de `FONTS` | `montserrat` |
| `color` | hex | `#ffffff` |
| `highlight` | hex (palavra falada) | `#ff4500` |
| `highlight_mode` | `outline` (contorno colorido, como hoje) / `fill` (letra colorida) / `box` (caixa atrás da palavra) | `outline` |
| `outline` | 0–6 | 1.5 (normal; o destaque segue proporcional, 2.5 hoje) |
| `background` | `none` / `box` (caixa semitransparente atrás da linha) | `none` |
| `words` | 1–4 por vez | 4 (`MAX_WORDS_PER_LINE` de hoje) |
| `uppercase` | bool | true |
| `hidden` | bool (só usado no ajuste por vídeo) | false |

Os 16 presets ganham `captions` que combinem (fonte/cor de destaque do estilo).
"Padrão" fica com o visual de hoje. Quem já usa um preset (ex.: Neon) recebe a
legenda nova dele no próximo short: é o que o rascunho aprovado prometeu ("cada
estilo pronto já vem com uma legenda combinando").

**Fonte de hoje.** O ASS pede `Montserrat` negrito, mas o filtro não recebe
`fontsdir` e a fonte não está instalada: o libass cai numa fonte do sistema
(Verdana Bold no Mac do dono; outra no Windows/Linux). Com `fontsdir`, o
default passa a sair na Montserrat de verdade (`Montserrat-ExtraBold.ttf`),
igual em todas as máquinas. É uma mudança visível em todo short novo, aceita
como correção.

Estilos já salvos pela pessoa (`~/.auto-edit/styles/`) e `.autoedit-style.json`
importados sem `captions` → default = visual de hoje. Exportar inclui `captions`.

### 2. Captioner lê o estilo (`tools/captioner.py`)

- Ordem de quem manda: default ← `captions` do estilo ativo **no momento da
  edição** ← ajuste do vídeo (`pipeline.json["caption_style"]`).
- O estilo usado é gravado no `pipeline.json` (`captions` resolvido) quando a
  edição começa (`POST /api/edit`, CLI `short`/`long`/`batch`/`merge`/`shorts`):
  trocar de estilo depois não muda vídeo já feito; "Regravar" usa o gravado +
  o ajuste. Vídeo feito antes disso (sem `captions` gravado) usa o **default**
  (visual de hoje), nunca o estilo ativo agora.
- `caption_style` antigo (chaves `color_highlight`, `border_highlight`… da CLI)
  continua aceito e traduzido.
- CLI `--highlight-color/--highlight-border/--font-size`: hoje sempre gravam
  default no `pipeline.json` e por isso passariam por cima do estilo. Viram
  `None` por padrão e só valem quando passados.
- Tamanho/posição em proporção do vídeo (`PlayResX/Y` do ASS = resolução do
  vídeo), pra valer igual em 1080×1920 e 2160×3840.
- **Fontes**: o filtro `subtitles` recebe `fontsdir=` com `assets/fonts` (e
  `assets/thumbnails/fonts`), e o nome de família no ASS é o nome interno do
  TTF de `FONTS`. Assim a fonte escolhida é a que sai em qualquer máquina.
- `hidden` → copia o vídeo cortado como final, sem queimar (o .srt continua).

### 3. Prévia (`styles.preview(tokens, "caption")`)

- Novo `PREVIEW_KINDS` `caption`: um frame vertical do vídeo mais recente
  (short; sem short, o centro do long recortado em 9:16; sem vídeo, um fundo
  neutro), com uma frase de exemplo e uma palavra destacada, desenhado pelo
  **mesmo** gerador ASS + ffmpeg/libass do captioner, 1 frame → PNG. Mesmo cache
  das outras prévias (chave inclui os tokens).
- `POST /api/styles/preview/caption` já sai de graça do endpoint existente.

### 4. App — Estilos → aba "Legenda" (`desktop/ui/`)

Controles do rascunho aprovado: Posição (Topo/Meio/Baixo) + altura fina,
Tamanho, Fonte, Cor do texto, Cor da palavra falada, Jeito do destaque,
Contorno, Fundo atrás do texto, Palavras por vez, MAIÚSCULAS. Prévia ao lado,
atualiza ao mexer (debounce como as outras prévias). Os cards da galeria não
mudam.

### 5. App — "Ajustar legenda" no vídeo pronto (só short)

- No resultado do short: prévia vertical com a legenda arrastável (vertical),
  Tamanho, Esconder legenda, botão **Regravar legenda**.
- Arrastar define `position`/`offset`; salva só `position`, `offset`, `size`,
  `hidden` em `pipeline.json["caption_style"]` (o resto vem do estilo gravado).
- Prévia usa um frame do próprio vídeo cortado.
- API nova: `GET/PUT /api/videos/<id>/captions` (ajuste atual / salvar) e
  "Regravar" = `POST /api/videos/<id>/resume {from_stage: "caption"}` (existe).
  Depois do caption, o pipeline segue normal (metadata e thumbnail não refazem:
  o resume para no `done` se só a legenda foi pedida — ver "Para o builder").

### 6. Guardar o vídeo sem legenda

- `_cleanup_workspace` (`auto_edit/pipeline.py`) para de apagar
  `edited_video.mp4` do short (é ele que recebe a legenda). Custo: ~1 cópia do
  short em disco (dezenas a ~100 MB).
- Vídeo feito antes disso não tem a cópia: "Regravar" avisa que vai recortar
  (alguns minutos) e roda `resume --from execute`.

## Testes

- `validate()`: default = visual de hoje; valores ruins caem no default; estilo
  sem `captions` e import antigo funcionam.
- Captioner: o ASS gerado reflete cada token (alinhamento/margem por posição,
  fonte, tamanho proporcional, cores BGR, modos de destaque, palavras por vez,
  maiúsculas); ordem default ← estilo gravado ← ajuste; `caption_style` antigo
  traduzido; `hidden` não queima; `fontsdir` presente no filtro.
- Regressão: sem estilo/ajuste, o ASS sai com a mesma posição, tamanho, cores,
  contorno e agrupamento de hoje (snapshot do ASS; a fonte agora vem do
  `fontsdir`).
- Prévia `caption` gera PNG (marcado como skip sem ffmpeg com libass).
- API do ajuste: salvar só as 4 chaves; regravar sem `edited_video.mp4` cai pro
  execute.
- Smoke do app (`scripts/smoke_engine.py`): prévia de legenda de todos os
  presets.

## Escolhas que ficaram comigo

- Prévia com libass (igual ao final) em vez de desenhar no Satori.
- Estilo gravado no vídeo na primeira legenda (vídeo antigo não muda sozinho).
- Manter `edited_video.mp4` do short.
- Default sai na Montserrat de verdade (corrige o fallback calado de hoje).
- Presets trazem legenda própria e quem já usa um recebe ela no próximo short.
- Vídeo antigo sem estilo gravado regrava com o default, não com o estilo ativo.
- Estilo gravado quando a edição começa (não quando a legenda roda).

## Para o builder

- Regravar só a legenda: hoje `resume --from caption` segue pra metadata e
  thumbnail. Decidir se para depois do caption (preferível: metadata não muda)
  e como sinalizar isso pro `ralph.sh`.
