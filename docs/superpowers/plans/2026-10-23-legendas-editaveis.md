# Legendas editáveis — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A legenda do short vira parte do estilo (tokens `captions`, com prévia real) e pode ser ajustada por vídeo (posição, tamanho, esconder), regravando só a legenda.

**Architecture:** Dois módulos novos e puros: `auto_edit/caption_style.py` (tokens, validação, tradução do `caption_style` antigo, ordem de quem manda) e `auto_edit/caption_render.py` (ASS em pixels do vídeo, fontes do app via `fontsdir`, comando do ffmpeg/libass, prévia de 1 frame). O captioner, a prévia do estilo e a API do vídeo usam os dois. O estilo resolvido é gravado no `pipeline.json` na criação do workspace; "Regravar" roda só o stage `caption` e pula pro `done`.

**Tech Stack:** Python 3.11, pysubs2, ffmpeg com libass (filtro `subtitles`), Pillow (nome da família da fonte), Flask (API), JS puro no `desktop/ui/`.

**Spec:** `docs/superpowers/specs/2026-10-22-legendas-editaveis-design.md`

## Global Constraints

- Branch `feat/legendas-editaveis`; nunca commitar na main. Commits terminam com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Valor ruim em token → default, nunca erro (igual ao resto de `styles.validate`).
- Default = visual de hoje em posição, tamanho, cores, contorno e agrupamento. Só a fonte muda (Montserrat de verdade via `fontsdir`).
- Hoje o ASS não tem `PlayResX/Y` → libass usa **384×288**. Equivalências que o default tem que reproduzir em PlayRes = resolução do vídeo (W×H): fonte `14/288·H`, margem vertical `95/288·H` (≈ 33% da altura, por isso `offset` default = **33**), margens laterais `10/384·W`, contorno `1.5/288·H`, contorno do destaque `2.5/288·H`, blur do destaque `0.8/288·H`.
- Faixas: `offset` 0–40, `size` 50–200, `outline` 0–6, `words` 1–4.
- Long continua sem legenda queimada. Ajuste por vídeo só em short.
- Vídeo sem `captions` gravado usa o **default**, nunca o estilo ativo agora.
- Novo comportamento ligado por padrão; textos do app em português.
- Testes: `python -m pytest tests/ -v`; lint: `ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`; `bash -n ralph.sh`.

## Review Focus

1. **Caminho do Windows no filtro `subtitles`** (letra de drive, espaços, acento no nome da pasta): o burn tem que funcionar. Decisão: o ffmpeg roda com `cwd` = pasta do ASS e o filtro usa só caminhos relativos (`subtitles=captions.ass:fontsdir=.caption-fonts`). Teste no Task 2.
2. **Fonte caindo em outra calada** (nome de família errado, ou a Montserrat-Variable de `assets/thumbnails/fonts` ganhando da ExtraBold): cada burn recebe uma pasta só com o TTF escolhido. Teste real (pula sem libass) no Task 2: Montserrat e Bangers dão pixels diferentes, e Montserrat com/sem `fontsdir` também.
3. **Pipeline antigo com o `caption_style` que a CLI sempre gravava** (`border_highlight 2.5`, `color_highlight &H0045FF&`, `font_size 14`): sai igual ao default. Teste no Task 1.
4. **Regravar vídeo antigo sem `edited_video.mp4`**: recorta (execute → caption) e **não** refaz metadata/thumbnail. Teste no Task 4.
5. **Regravar com outro job rodando no mesmo vídeo**: recusa igual ao `resume` de hoje (mesmo guard do `_spawn`). Teste no Task 4.

---

### Task 1: Tokens `captions` (`caption_style.py` + estilos)

**Files:**
- Create: `auto_edit/caption_style.py`
- Modify: `auto_edit/styles.py` (`DEFAULT_TOKENS`, `validate()`, `PRESETS`/`_gallery`)
- Test: `tests/test_caption_style.py`, `tests/test_styles.py`

**Interfaces:**
- Produces:
  - `DEFAULT: dict` = `{"position": "bottom", "offset": 33, "size": 100, "font": "montserrat", "color": "#ffffff", "highlight": "#ff4500", "highlight_mode": "outline", "outline": 1.5, "background": "none", "words": 4, "uppercase": True, "hidden": False}`
  - `POSITIONS = ("top", "middle", "bottom")`, `HIGHLIGHT_MODES = ("outline", "fill", "box")`, `BACKGROUNDS = ("none", "box")`, `ADJUST_KEYS = ("position", "offset", "size", "hidden")`
  - `validate(raw) -> dict` (completo, seguro; `font` precisa ser id de `styles.FONTS`, importado dentro da função pra evitar ciclo)
  - `from_legacy(caption_style: dict) -> dict` (só as chaves que conseguir traduzir)
  - `resolve(pipeline: dict) -> dict` = `validate({**validate(pipeline.get("captions")), **from_legacy(cs), **{k: cs[k] for k in ADJUST_KEYS if k in cs}})`, com `cs = pipeline.get("caption_style") or {}`
  - `ass_color(hex) -> str` (`"#ff4500"` → `"&H0045FF&"`)
  - `styles.DEFAULT_TOKENS["captions"] == caption_style.DEFAULT`; `styles.validate(t)["captions"] == caption_style.validate(t.get("captions"))`

Tradução do legado (`from_legacy`): `color_highlight`/`color_text` (`&HBBGGRR&`) → `highlight`/`color`; `border_normal` → `outline`; sem `border_normal`, `border_highlight` → `outline = border_highlight * 0.6`; `font_size` → `size = font_size / 14 * 100`; `margin_v` → `position="bottom"`, `offset = margin_v / 288 * 100`; `font_name` → id de `FONTS` cujo `label` bate (sem diferenciar maiúscula), senão ignora. `color_outline`, `blur_highlight`, `font_bold` são ignorados.

Legenda de cada preset (o resto = `DEFAULT`):

| preset | font | highlight | highlight_mode | extra |
|---|---|---|---|---|
| padrao | — | — | — | — |
| minimal | poppins | #ffffff | fill | color #cfcfcf, uppercase false, outline 1 |
| neon | poppins | #39ff14 | fill | |
| impacto | anton | #ffd400 | box | |
| rosto_gigante | luckiest | #ffd400 | fill | |
| tarja | anton | #e3122b | box | |
| neon_tech | bebas | #00e5ff | fill | |
| limpo | poppins | #4ade80 | fill | uppercase false |
| jornal | archivo | #d90429 | box | background box |
| versus | luckiest | #ff3b3b | outline | |
| painel | montserrat | #ffd400 | box | |
| celular | lilita | #a3e635 | fill | |
| reacao | luckiest | #ffd400 | fill | |
| quadrinho | bangers | #e3122b | outline | outline 3 |
| ouro | archivo | #e8b84a | fill | |
| card | poppins | #6d28d9 | box | |

`_preset`/`_gallery` já mesclam dicts com `update`; passe `captions={...}` como os outros campos.

- [ ] **Step 1: Testes que falham** em `tests/test_caption_style.py`:

```python
def test_default_is_todays_look():
    assert caption_style.validate(None) == caption_style.DEFAULT

def test_bad_values_fall_back():
    v = caption_style.validate({"position": "left", "offset": 99, "size": "x", "font": "comic", "color": "red", "words": 9, "highlight_mode": "glow"})
    assert v["position"] == "bottom" and v["offset"] == 40 and v["size"] == 100
    assert v["font"] == "montserrat" and v["color"] == "#ffffff" and v["words"] == 4 and v["highlight_mode"] == "outline"

def test_old_cli_caption_style_is_the_default():
    pl = {"caption_style": {"border_highlight": 2.5, "color_highlight": "&H0045FF&", "font_size": 14}}
    assert caption_style.resolve(pl) == caption_style.DEFAULT

def test_legacy_translation():
    out = caption_style.from_legacy({"color_highlight": "&H00FF00&", "font_size": 21, "margin_v": 144, "font_name": "bangers"})
    assert out == {"highlight": "#00ff00", "size": 150, "position": "bottom", "offset": 50, "font": "bangers"}
    # offset 50 cai pra 40 no validate

def test_precedence_default_style_adjust():
    pl = {"captions": {"font": "anton", "position": "bottom"}, "caption_style": {"position": "top", "offset": 10, "font": "bebas"}}
    r = caption_style.resolve(pl)
    assert r["font"] == "anton"           # ajuste por vídeo não troca fonte
    assert (r["position"], r["offset"]) == ("top", 10)

def test_no_saved_style_uses_default_not_active(monkeypatch):
    monkeypatch.setattr(styles, "active", lambda: {"tokens": {"captions": {"font": "bangers"}}})
    assert caption_style.resolve({})["font"] == "montserrat"

def test_ass_color():
    assert caption_style.ass_color("#ff4500") == "&H0045FF&"
```

Em `tests/test_styles.py`: `validate({})["captions"] == caption_style.DEFAULT`; todo preset tem `captions` válido e `PRESETS["padrao"]["tokens"]["captions"] == caption_style.DEFAULT`; `import_` de um arquivo sem `captions` gera estilo com o default; `export` inclui `captions`.

- [ ] **Step 2:** `python -m pytest tests/test_caption_style.py tests/test_styles.py -v` → FAIL (módulo não existe).
- [ ] **Step 3:** Implementar `caption_style.py` e ligar em `styles.py` (reaproveitar `_color`, `_number`, `_choice` de lá com import lazy, ou duplicar os 3 helpers se o ciclo atrapalhar). `offset`/`size`/`outline` como número (float), `words` int.
- [ ] **Step 4:** Mesmo comando → PASS; rodar `tests/` inteiro (o smoke de presets em `test_styles` precisa continuar passando).
- [ ] **Step 5:** Commit `feat(captions): tokens de legenda no estilo`.

---

### Task 2: Gerar e queimar a legenda a partir dos tokens (`caption_render.py` + captioner)

**Files:**
- Create: `auto_edit/caption_render.py`
- Modify: `tools/captioner.py` (`caption()`, `_group_words`, `_generate_ass`, `_burn_captions`; `_resolve_caption_ffmpeg` e companhia mudam pra `caption_render` e o captioner reimporta os nomes, porque os testes importam de `tools.captioner`)
- Test: `tests/test_caption_render.py`, `tests/test_captioner.py`

**Interfaces:**
- Consumes: `caption_style.resolve`, `caption_style.ass_color`, `styles.FONTS`, `styles.font_file`
- Produces:
  - `group_words(words: list[dict], max_words: int) -> list[list[dict]]` (o `_group_words` de hoje com `max_words` no lugar de `MAX_WORDS_PER_LINE`; o captioner mantém `_group_words(words)` chamando com 4)
  - `build_ass(groups, captions: dict, width: int, height: int) -> pysubs2.SSAFile`
  - `font_family(font_id: str) -> str` (via `ImageFont.truetype(path, 10).getname()[0]`)
  - `prepare_fonts(font_id: str, folder: Path) -> Path` (cria `folder/.caption-fonts/` só com o TTF `bold` daquela fonte; retorna o nome relativo)
  - `burn_command(ffmpeg: str, video: Path, ass_name: str, fonts_name: str, output: Path) -> list[str]` (filtro `subtitles=<ass_name>:fontsdir=<fonts_name>`, sem caminho absoluto; roda com `cwd` = pasta do ASS)
  - `resolve_ffmpeg() -> str` (o `_resolve_caption_ffmpeg` atual)
  - `video_size(path: Path) -> tuple[int, int]` (ffprobe `width,height`)

Geometria de `build_ass` (s = H/288; W×H = vídeo):
- `PlayResX=W`, `PlayResY=H`, `ScaledBorderAndShadow=yes`.
- Estilo `Default`: `fontname = font_family(font)`, `bold = False` (o TTF já é pesado; bold sintético engrossa Bebas/Anton), `fontsize = 14·s·size/100`, `outline = outline·s`, `marginl = marginr = round(10·W/384)`.
- Posição: `bottom` → alignment 2, `marginv = offset/100·H`; `top` → alignment 8, mesma margem; `middle` → alignment 5, `marginv = 0`.
- Texto: `upper()` se `uppercase`. Grupo = `words` por vez.
- Destaque (contorno do destaque = `outline·5/3·s`, blur `0.8·s`):
  - `outline`: as tags de hoje (`\3c` = highlight, `\bord`, `\blur`).
  - `fill`: `\1c` = highlight, contorno normal.
  - `box`: um evento extra na camada 0 com estilo `Box` (BorderStyle 3, `outlinecolor` = highlight) e a mesma linha com `\1a&HFF&` em tudo e `\3a&HFF&` em toda palavra menos a falada; a camada 1 é o texto normal. Texto da palavra falada fica preto se a luminância do highlight > 0.6, senão `color`.
- `background: box`: outro evento na camada 0, estilo `Box` com `outlinecolor` preto e `\3a&H60&`, a linha inteira com `\1a&HFF&`.

No captioner: `style = caption_style.resolve(pipeline)`; `hidden` → grava ASS/SRT normalmente e copia o vídeo cortado pra `captioned_video.mp4` (sem ffmpeg). O print de estilo passa a mostrar fonte/posição/tamanho.

- [ ] **Step 1: Testes que falham** em `tests/test_caption_render.py`:

```python
def _style(ass):  return ass.styles["Default"]

def test_default_matches_todays_geometry_on_1080x1920():
    ass = caption_render.build_ass([[W1, W2]], caption_style.DEFAULT, 1080, 1920)
    s = _style(ass)
    assert ass.info["PlayResX"] == "1080" and ass.info["PlayResY"] == "1920"
    assert s.alignment == 2 and s.marginv == pytest.approx(95 / 288 * 1920, abs=2)
    assert s.fontsize == pytest.approx(14 / 288 * 1920, abs=0.5)
    assert s.outline == pytest.approx(1.5 / 288 * 1920, abs=0.05)
    assert "\\3c&H0045FF&" in ass.events[0].text and "HELLO" in ass.events[0].text

def test_scales_with_resolution():  # 2160x3840 = dobro de fonte e margem do 1080x1920

def test_top_and_middle(): # top → alignment 8, marginv = offset% H; middle → 5, marginv 0

def test_size_font_colors_words_uppercase():
    c = caption_style.validate({"size": 150, "font": "bangers", "color": "#ffff00", "words": 2, "uppercase": False, "highlight_mode": "fill"})
    # fontname "Bangers", fontsize 1.5x, \1c&H00FFFF& no texto normal, palavra falada \1c com highlight, texto minúsculo

def test_box_mode_adds_a_box_layer():  # evento camada 0 estilo Box (borderstyle 3); camada 1 o texto

def test_burn_command_uses_only_relative_paths(tmp_path):
    cmd = caption_render.burn_command("ffmpeg", tmp_path / "v.mp4", "captions.ass", ".caption-fonts", tmp_path / "o.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "subtitles=captions.ass:fontsdir=.caption-fonts"

def test_prepare_fonts_has_only_the_chosen_file(tmp_path):
    name = caption_render.prepare_fonts("montserrat", tmp_path)
    assert [p.name for p in (tmp_path / name).iterdir()] == ["Montserrat-ExtraBold.ttf"]
```

Teste real, `pytest.mark.skipif` sem ffmpeg com libass (`caption_render.resolve_ffmpeg` levanta): queimar um frame `color=gray:s=540x960` com Montserrat e com Bangers → bytes do PNG diferentes; e Montserrat com `fontsdir` ≠ sem `fontsdir` (prova que a fonte do app é a usada).

Em `tests/test_captioner.py`: `caption()` com `hidden: True` no `caption_style` e `_burn_captions` monkeypatched → não chama o burn, `captioned_video.mp4` existe, `captions.srt` existe.

- [ ] **Step 2:** `python -m pytest tests/test_caption_render.py tests/test_captioner.py -v` → FAIL.
- [ ] **Step 3:** Implementar `caption_render.py`; trocar o captioner pra usar ele (`video_size` do vídeo cortado, `group_words(words, style["words"])`, `prepare_fonts` na pasta do workspace, `subprocess.run(burn_command(...), cwd=workspace)`).
- [ ] **Step 4:** Mesmo comando → PASS. Conferir visualmente: queimar um short real do `workspace/` com o default e comparar com o `captioned_video.mp4` antigo (mesmo frame): posição e tamanho iguais, fonte agora Montserrat.
- [ ] **Step 5:** Commit `feat(captions): legenda desenhada pelos tokens, com as fontes do app`.

---

### Task 3: Gravar o estilo da legenda quando a edição começa

**Files:**
- Modify: `auto_edit/pipeline.py` (`init`: param `captions: dict | None = None`, grava `pipeline["captions"]`), `auto_edit/workspace.py` (`init_workspace` passa `captions=_active_captions()`), `auto_edit/shorts.py:~281` (o short derivado herda `long_pipeline.get("captions")`, senão o ativo), `auto_edit/cli.py` (`--highlight-border/--highlight-color/--font-size` com default `None`, em `short` ~307 e `merge` ~713; `caption_style` só com o que foi passado)
- Test: `tests/test_pipeline.py`, `tests/test_cli*.py` (o que já testa as flags; senão `tests/test_caption_style.py`)

**Interfaces:**
- Consumes: `styles.active()["tokens"]["captions"]`, `caption_style.validate`
- Produces: `workspace._active_captions() -> dict` (o ativo validado; qualquer exceção → `caption_style.DEFAULT`); `pipeline.json["captions"]` em todo workspace novo.

- [ ] **Step 1: Testes que falham:** `init_workspace` com estilo ativo `neon` grava `captions == validate(neon)`; trocar o ativo depois não muda o `pipeline.json`; settings quebrado → default; short derivado de um long com `captions` herda o do long; `auto-edit short` sem as flags grava `caption_style == {}`, com `--font-size 21` grava `{"font_size": 21}`.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → PASS; `tests/` inteiro.
- [ ] **Step 5:** Commit `feat(captions): estilo da legenda gravado no vídeo`.

---

### Task 4: Regravar só a legenda

**Files:**
- Modify: `auto_edit/pipeline.py` (`recaption`, `set_stage_status`, `_cleanup_workspace`), `auto_edit/engine.py` (`resume_edit`)
- Test: `tests/test_pipeline.py`, `tests/test_engine.py`

**Interfaces:**
- Produces:
  - `pipeline.recaption(workspace: Path) -> str`: com `edited_video.mp4` → `current_stage="caption"`, só `caption` volta a `pending`; sem ele → `current_stage="execute"`, só `execute` e `caption` voltam a `pending`. Nos dois grava `caption_only: True` e retorna o stage de início.
  - `set_stage_status(ws, "caption", "complete")` com `caption_only` → `current_stage = "done"` e remove a flag.
  - `_cleanup_workspace` do short não apaga mais `edited_video.mp4` (continua apagando `overlaid_video.mp4`).
  - `JobManager.resume_edit(id, "caption")` num short chama `pl.recaption` em vez de `pl.set_stage`; o resto do `resume_edit` igual (mesmo `_spawn`, mesmo guard de job rodando). Long ou outros stages: como hoje.

- [ ] **Step 1: Testes que falham:** recaption com `edited_video.mp4` → começa no caption e, depois de completar o caption, `current_stage == "done"` e `metadata`/`thumbnail` continuam `complete`; sem o arquivo → começa no execute, execute completo avança pro caption (overlay é skip), caption completo vai pro done, metadata intacta; `finalize` de short deixa `edited_video.mp4`; `resume_edit(id, "caption")` num short com outro job rodando recusa igual ao resume de hoje; num long, `resume_edit(id, "caption")` se comporta como hoje.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → PASS. `bash -n ralph.sh` (ralph não muda: o pulo é no `set_stage_status`).
- [ ] **Step 5:** Commit `feat(captions): regravar só a legenda`.

---

### Task 5: Prévia `caption` do estilo

**Files:**
- Modify: `auto_edit/styles.py` (`PREVIEW_KINDS`, `preview()`, novo `preview_frame_vertical()`), `auto_edit/caption_render.py` (`render_preview`)
- Test: `tests/test_styles.py`, `tests/test_caption_render.py`

**Interfaces:**
- Consumes: `caption_render.build_ass`, `prepare_fonts`, `burn_command`, `resolve_ffmpeg`
- Produces:
  - `PREVIEW_KINDS = ("thumbnail", "lower_third", "cta", "caption")`; `CAPTION_W, CAPTION_H = 540, 960`; `SAMPLE_CAPTION = "Editei esse vídeo com IA"`
  - `caption_render.render_preview(captions: dict, frame: Path | None, width: int, height: int) -> bytes` (PNG; sem frame, fundo `color=c=0x303030`; frase de exemplo cortada em `words`, palavra destacada = a 3ª ou a última; 1 frame com evento de 0 a 5s)
  - `styles.preview_frame_vertical(video: Path | None = None) -> Path | None`: com `video`, um frame dele; senão o `edited_video.mp4` mais novo de um short da biblioteca, senão o de um long recortado no centro em 9:16; escala/corta pra 540×960; cache como `preview_frame`.
  - `styles.preview(tokens, "caption")` → `render_preview(validate(tokens)["captions"], preview_frame_vertical(), 540, 960)`, cacheado em `_cache_dir()/caption-<sha>.png` (chave: captions + caminho/mtime do frame). Sem ffmpeg com libass → `StyleError("ffmpeg sem libass: a prévia da legenda precisa do filtro subtitles")`.
- A rota `POST /api/styles/preview/caption` já sai do endpoint existente; o smoke (`scripts/smoke_engine.py`) já itera `PREVIEW_KINDS`, então cobre a legenda de todos os presets sem mudança.

- [ ] **Step 1: Testes que falham:** `preview({}, "caption")` com `render_preview` falso recebe o default e 540×960; segunda chamada igual vem do cache; `preview_frame_vertical` prefere short a long (dois workspaces falsos com `pipeline.json` de tipos diferentes); teste real (skip sem libass) de `render_preview` → começa com `b"\x89PNG"` e Montserrat ≠ Bangers.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → PASS; `python scripts/smoke_engine.py` se tiver o motor montado, senão `python -c "from auto_edit import styles; [styles.preview(p['tokens'],'caption') for p in styles.PRESETS.values()]"`.
- [ ] **Step 5:** Commit `feat(captions): prévia da legenda no estilo`.

---

### Task 6: API do ajuste por vídeo

**Files:**
- Modify: `auto_edit/engine.py` (funções de módulo, perto de `artifact_path`), `auto_edit/api.py`
- Test: `tests/test_engine.py`, `tests/test_api*.py` (onde já se testa `/resume`)

**Interfaces:**
- Produces:
  - `engine.video_captions(video_id) -> dict` = `{"captions": caption_style.resolve(p), "adjust": {k: v for k in ADJUST_KEYS presentes no caption_style}, "fast": edited_video.mp4 existe}`; `ValueError` se não for short.
  - `engine.save_video_captions(video_id, body: dict) -> dict`: valida só as 4 chaves (`caption_style.validate` e pega `ADJUST_KEYS` do que veio), grava em `pipeline["caption_style"]` mantendo as chaves legadas, retorna `video_captions`.
  - `engine.video_caption_preview(video_id, adjust: dict) -> bytes`: `render_preview(resolve com o ajuste, preview_frame_vertical(edited_video.mp4 ou None), 540, 960)`.
  - Rotas: `GET /api/videos/<id>/captions`, `PUT /api/videos/<id>/captions` (body = as 4 chaves), `POST /api/videos/<id>/captions/preview` (body = ajuste → `image/png`). 404 sem workspace, 400 em long. Regravar = `POST /api/videos/<id>/resume {"from_stage": "caption"}` (já existe).
- CLAUDE.md: acrescentar as 3 rotas na lista da API.

- [ ] **Step 1: Testes que falham:** PUT com `{"position": "top", "offset": 12, "font": "bangers"}` grava só `position`/`offset` (fonte ignorada) e preserva `font_size` legado; GET reflete o ajuste e `fast`; long → 400; preview devolve PNG (render falso).
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(api): ajuste da legenda por vídeo`.

---

### Task 7: App — Legenda no editor de Estilos

**Files:**
- Modify: `desktop/ui/index.html` (seção `.sty-previews` e `#sty-editor`), `desktop/ui/js/styles.js` (`KINDS`, `fmt`), CSS do app onde ficam as regras `.sty-*`

**Interfaces:**
- Consumes: `POST /api/styles/preview/caption`; tokens `captions.*` via os `data-tok` genéricos que o editor já lê/grava (`getTok`/`setTok`).

O editor não tem abas: a "aba Legenda" do rascunho vira um `<fieldset>` "Legenda" na `.sty-cols`, no padrão dos outros. Controles (`data-tok`): `captions.position` (select Topo/Meio/Baixo), `captions.offset` (range 0–40, `data-num`, desabilitado no Meio), `captions.size` (range 50–200 passo 5), `captions.font` (`data-fonts`), `captions.color` e `captions.highlight` (color), `captions.highlight_mode` (select: contorno colorido / letra colorida / caixa atrás da palavra), `captions.outline` (range 0–6 passo 0.5), `captions.background` (select nenhum/caixa), `captions.words` (select 1–4), `captions.uppercase` (checkbox). `fmt`: `captions.size`/`captions.offset` em `%`. A prévia ganha um 4º `<figure>` "Legenda" com `.sty-shot` vertical (9:16, mais estreito). `KINDS` ganha `"caption"`. `captions.words` é select: converter pra número no `setTok` (como `data-num`).

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** Rodar o app (skill `run`) → Estilos → um preset: a prévia da legenda aparece; Personalizar → mexer em posição, tamanho, fonte e destaque atualiza a prévia; Salvar → recarregar mantém. Screenshot.
- [ ] **Step 3:** Commit `feat(app): legenda no editor de estilos`.

---

### Task 8: App — "Ajustar legenda" no short pronto

**Files:**
- Create: `desktop/ui/js/caption-adjust.js` (`mountCaptionAdjust(id, container)`, `unmountCaptionAdjust()`), no padrão de `publish.js`
- Modify: `desktop/ui/index.html` (card na `.res-grid`), `desktop/ui/js/result.js` (monta só se `d.type === "short"` e o vídeo terminou), `desktop/ui/js/api.js` (`videoCaptions(id)`, `saveVideoCaptions(id, adjust)`, `videoCaptionPreview(id, adjust)` → blob URL)

**Interfaces:**
- Consumes: as 3 rotas do Task 6; `api.resume(id, "caption")`.

Comportamento:
- Prévia vertical (o PNG do servidor) com uma faixa tracejada por cima, arrastável na vertical. Soltar: centro da faixa em `y` (0–1) → `y < 0.4` → `top`, `offset = round(y·100)`; `y > 0.6` → `bottom`, `offset = round((1−y)·100)`; senão `middle`. Clampar `offset` em 0–40. Pede a prévia nova (debounce 350 ms, descarta resposta velha como o `seq` de `styles.js`).
- Tamanho (range 50–200), Esconder legenda (checkbox; esconde a prévia da faixa).
- **Regravar legenda**: `PUT` do ajuste e depois `resume(id, "caption")`, e vai pra tela do pipeline como o botão de retomar faz hoje. Com `fast: false`, o texto do botão avisa: "Esse vídeo é de antes desta versão: vai recortar de novo (alguns minutos)".
- Ao voltar pro resultado, o `<video>` recarrega com `?t=<agora>` (o arquivo mudou e o webview guarda cache).

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** Rodar o app com um short real: arrastar pra cima, aumentar, Regravar → pipeline roda só caption → resultado mostra a legenda no lugar novo; metadata não refaz (conferir no `pipeline.json`). Esconder → vídeo sem legenda. Screenshot de antes e depois.
- [ ] **Step 3:** Commit `feat(app): ajustar legenda por vídeo`.

---

### Task 9: Docs e fechamento

**Files:**
- Modify: `CLAUDE.md` (linha do `assets/`/renderer: legenda faz parte do estilo, `auto_edit/caption_style.py` + `caption_render.py`, `fontsdir`; `--font-size/--highlight-*` só valem quando passados), `.gitignore` (`.superpowers/`)

- [ ] **Step 1:** Editar.
- [ ] **Step 2:** `python -m pytest tests/ -v`, ruff, `bash -n ralph.sh` → tudo verde.
- [ ] **Step 3:** Commit `docs: legendas editáveis`.
