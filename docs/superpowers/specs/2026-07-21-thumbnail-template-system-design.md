# Thumbnail Template System — Design

**Data:** 2026-07-21
**Branch:** `feat/thumbnail-template-system`
**Arquivos afetados:** `tools/thumbnailer.py`, `agents/metadata.md`, `assets/thumbnails/templates.json` (novo), `tests/`

---

## 1. Problema

Thumbnails de short são `1080×1920` (9:16). Na aba **Posts** do Instagram (grid) a imagem é recortada para **1:1 central** — perde ~22% do topo e ~22% da base (faixa visível: y ∈ [422, 1498] = `22%`–`78%` da altura).

Hoje o texto principal é desenhado em `block_top = h*0.08` (≈ y154), **dentro da zona cortada**. Resultado: a primeira linha da headline some na grid. Confirmado na grid real do usuário ("CASE DA **GOPRO**" → só "GOPRO"). Na aba Reels (9:16 cheio) lê tudo; na grid, não.

Além do corte, o usuário quer:
- Identidade visual mais profissional (templates por tipo de conteúdo).
- Ajudar engajamento — reconhecido como alavanca de **CTR** (não de retenção/watch-time), principalmente via legibilidade + **copy do gancho** no `sub_text`.

## 2. Objetivos

1. **Corte resolvido** — todo texto vive na faixa segura `22%–78%`. Lê nas duas views.
2. **Sistema de templates por tipo de conteúdo**, **data-driven e extensível** (não hardcoded em 3).
3. **LLM escolhe o template** pelo contexto do vídeo.
4. **Copy do `sub_text` como gancho** (curiosidade/tensão/número), não descrição.
5. **Sem marca fixa** — só o texto do conteúdo (decisão do usuário).

### Não-objetivos (fora de escopo)

- Retenção / edição dos primeiros segundos (é outro sistema).
- Logo/marca na thumbnail (dropado — pode voltar em spec futura).
- Redesenho do fluxo de thumbnail **long** além de herdar a correção de safe-zone e o registry.

---

## 3. Correção de posicionamento (safe-zone)

### Constantes novas (`thumbnailer.py`)

```python
IG_SAFE_TOP = 0.22   # abaixo disso a grid corta
IG_SAFE_BOT = 0.78   # acima disso a grid corta
FACE_ZONE_TOP = 0.52 # texto não deve invadir abaixo daqui (rosto mora ~0.55–0.65)
```

### Regra de layout do bloco de texto

Em `_draw_thumbnail_text`, para a posição usada no short (`center`):

- `block_top` alvo = `int(h * 0.24)` (dentro da zona segura, terço superior).
- O bloco inteiro (main 1–2 linhas + gap + sub chip) deve caber em `[h*0.22, h*FACE_ZONE_TOP]`. Se a altura medida (`total_h`) exceder essa faixa, reduzir `max_size` do auto-size até caber (o loop de `_auto_size_font` já existe; adicionar limite de altura, não só de largura).
- Clamp final: `band_center` e a banda escura nunca ultrapassam `h*IG_SAFE_BOT`.

Isso mantém: main + sub 100% legíveis na grid quadrada **e** rosto visível na metade de baixo (não tapado pelo texto).

> A posição `left`/`right`/`upper` (usadas no long) recebem o mesmo clamp de safe-zone, mas o alvo vertical continua o atual delas.

---

## 4. Registry de templates (data-driven)

### Arquivo novo: `assets/thumbnails/templates.json`

```json
{
  "default": "dev",
  "templates": {
    "dev": {
      "description": "programação, frameworks, dicas de dev, carreira",
      "accent": [55, 224, 160],
      "grade": [[11, 31, 26], [6, 16, 13]],
      "sub_text_color": [4, 18, 12]
    },
    "maker": {
      "description": "impressão 3D, hardware, firmware, montagens, mods",
      "accent": [255, 159, 46],
      "grade": [[36, 22, 5], [15, 10, 5]],
      "sub_text_color": [26, 14, 0]
    },
    "gadget": {
      "description": "review de produto, unboxing, comparativo de gadgets",
      "accent": [255, 63, 134],
      "grade": [[38, 10, 26], [15, 5, 11]],
      "sub_text_color": [255, 255, 255]
    }
  }
}
```

- **`accent`** — cor do chip do `sub_text` (RGB).
- **`grade`** — par de cores `[topo, base]` para um tint/gradiente sutil sobre o frame do vídeo (dá a "cara" do tipo). Aplicado leve, sobre o frame estilizado existente.
- **`sub_text_color`** — cor do texto dentro do chip (contraste com o accent).

### Carregamento

- `_load_templates()` lê `templates.json` (via `_repo_root()` + override `AUTO_EDIT_ASSETS_*` no mesmo padrão dos outros assets). Se ausente ou inválido → usa um dict built-in embutido com os mesmos 3 (fallback, nunca quebra).
- Adicionar um tipo novo = adicionar entrada no JSON. Zero código.

### Migração do `STYLE_MAP` atual

`STYLE_MAP` (bold-energy / clean-minimal / dramatic / fun-colorful) é substituído pelo registry. Manter um **mapa de compatibilidade** `style_hint → template` para não quebrar metadata/workspaces antigos:

```
bold-energy → gadget, clean-minimal → dev, dramatic → gadget, fun-colorful → maker
```

### Render do `sub_text` como chip

Hoje o `sub_text` é só texto em cor accent. Novo: renderizar como **chip** — retângulo arredondado preenchido em `accent`, com o texto em `sub_text_color` por cima (como no mockup aprovado). Main text permanece branco condensado com outline.

---

## 5. Agente de metadata (`agents/metadata.md`)

### Campo novo: `thumbnail.template`

Substitui `style_hint`. O agente escolhe **um dos nomes de template disponíveis**. Como o registry é data-driven, a lista canônica de tipos + descrições fica no prompt (mantida em sync manualmente; o thumbnailer valida e cai no `default` se vier nome desconhecido).

Lista inicial no prompt:
- `dev` — programação, frameworks, dicas de dev, carreira
- `maker` — impressão 3D, hardware, firmware, montagens
- `gadget` — review de produto, unboxing, comparativo

`style_hint` vira **opcional/legado**: se o modelo mandar só `style_hint`, o thumbnailer mapeia via tabela de compat.

### `sub_text` como gancho (copy)

Reescrever a instrução do `sub_text`:

> `sub_text`: gancho de **curiosidade, tensão ou número**, não descrição. Deve criar uma lacuna de informação que só o vídeo fecha. Máx 30 chars. Renderiza num chip colorido de destaque.
>
> - ❌ descreve: "FEITA EM 3D", "REVIEW COMPLETO", "TUTORIAL"
> - ✅ gancho: "NINGUÉM FAZ ISSO", "SÓ R$100", "-70% DE ERRO", "E DEU CERTO?"
>
> Números, preços e specs contam como gancho quando são surpreendentes.

`main_text` mantém a regra atual (2–5 palavras de impacto), com nota reforçando promessa/tensão.

### Schema atualizado (short)

```json
"thumbnail": {
  "main_text": "CAIU O FLUTTER",
  "sub_text": "REACT EM 5 DIAS",
  "template": "dev"
}
```

`logos` sai do schema do short (sem marca fixa). Mantido no long por ora (long ainda usa face/logo asset), mas fora do caminho crítico desta spec.

---

## 6. Testes

Adicionar em `tests/test_thumbnailer.py` (ou equivalente):

1. **Safe-zone** — gerar thumbnail de um frame sintético; assertar que o bounding box do texto desenhado cai em `[0.22*h, 0.78*h]`. (Rastrear posições via os valores calculados, não OCR.)
2. **Registry** — `_load_templates()` lê o JSON; template desconhecido cai no `default`; JSON ausente usa fallback built-in.
3. **Compat** — `style_hint` legado mapeia para o template certo.
4. **Chip** — `sub_text` produz chip preenchido (sem exception; regressão de render).

Rodar: `python -m pytest tests/ -v` e `ruff check tools/ --select E,F,W --ignore E501`.

---

## 7. Ordem de implementação

1. `templates.json` + `_load_templates()` + fallback built-in.
2. Refatorar `_draw_thumbnail_text` para safe-zone + chip do sub.
3. Tabela de compat `style_hint → template` + validação de template.
4. Atualizar `agents/metadata.md` (campo `template` + copy do gancho).
5. Testes.
6. Validar visualmente com um vídeo real (`auto-edit short ... ` ou resume no stage de thumbnail).

---

## 8. Riscos / decisões abertas

- **Fonte:** o mockup usou fonte de sistema; o pipeline usa Anton/BebasNeue/Montserrat dos assets. O visual final vai depender da fonte real — validar no passo 6.
- **Grade sutil vs. frame:** o tint por tipo não pode escurecer o rosto. Aplicar só nas bordas/como leve overlay, respeitando o `_stylize_frame_bg` existente.
- **Sync prompt↔registry:** lista de tipos vive em dois lugares (JSON + metadata.md). Aceito por ora; futuro pode injetar o registry no prompt automaticamente.
