# Thumbnail Template System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reposicionar o texto das thumbnails para a zona segura do Instagram e trocar o `STYLE_MAP` hardcoded por um registry data-driven de templates por tipo de conteúdo, com o `sub_text` renderizado como chip colorido e escolhido pelo agente de metadata.

**Architecture:** Extrair a colocação vertical e o registry para funções puras e testáveis em `tools/thumbnailer.py`. O registry vem de `assets/thumbnails/templates.json` (com fallback embutido). O agente `metadata.md` passa `thumbnail.template` + `sub_text` como gancho; o thumbnailer resolve o template (com compat para `style_hint` legado), aplica um grade sutil por tipo e desenha o sub como chip.

**Tech Stack:** Python 3.11+, Pillow, numpy, pytest, ruff. FFmpeg (já usado, não afetado por este plano).

## Global Constraints

- Python >= 3.11. Sem novas dependências (só Pillow + numpy, já presentes).
- Zona segura do Instagram: texto e chip vivem em `y ∈ [0.22*h, 0.78*h]`; no short o bloco não passa de `FACE_ZONE_TOP = 0.52*h` para não tapar o rosto.
- Registry data-driven: adicionar um tipo = editar `templates.json`, sem tocar em código.
- Nunca quebrar workspaces antigos: `style_hint` legado mapeia para template via `_STYLE_HINT_COMPAT`; template desconhecido cai no `default`.
- Sem marca fixa na thumbnail de short (dropar compositing de logo no fluxo short).
- Lint: `ruff check tools/ tests/ --select E,F,W --ignore E501`. Testes: `python -m pytest tests/ -v`.
- Todo texto de output em português (mesma língua do vídeo), padrão do projeto.
- Trabalhar na branch `feat/thumbnail-template-system`.

---

### Task 1: Registry de templates (loader + fallback)

**Files:**
- Create: `assets/thumbnails/templates.json`
- Modify: `tools/thumbnailer.py` (adicionar constantes + `_load_templates`, perto de `STYLE_MAP`)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Produces: `_BUILTIN_TEMPLATES: dict`, `_load_templates() -> dict` retornando `{"default": str, "templates": {name: {"description": str, "accent": [int,int,int], "grade": [[int,int,int],[int,int,int]], "sub_text_color": [int,int,int]}}}`. Respeita override `AUTO_EDIT_ASSETS_TEMPLATES` (caminho de arquivo JSON).

- [ ] **Step 1: Criar o JSON do registry**

Create `assets/thumbnails/templates.json`:

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

- [ ] **Step 2: Escrever o teste que falha**

Create `tests/test_thumbnailer.py`:

```python
"""Tests for tools/thumbnailer.py — templates, safe-zone, chip render."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.thumbnailer import (
    _BUILTIN_TEMPLATES,
    _load_templates,
)


class TestLoadTemplates:
    def test_builtin_has_three_types(self):
        assert set(_BUILTIN_TEMPLATES["templates"]) >= {"dev", "maker", "gadget"}
        assert _BUILTIN_TEMPLATES["default"] in _BUILTIN_TEMPLATES["templates"]

    def test_reads_json_from_env(self, tmp_path, monkeypatch):
        custom = {"default": "x", "templates": {"x": {
            "description": "d", "accent": [1, 2, 3],
            "grade": [[0, 0, 0], [1, 1, 1]], "sub_text_color": [9, 9, 9]}}}
        f = tmp_path / "templates.json"
        f.write_text(json.dumps(custom))
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", str(f))
        reg = _load_templates()
        assert reg["templates"]["x"]["accent"] == [1, 2, 3]

    def test_missing_file_falls_back_to_builtin(self, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", "/nonexistent/nope.json")
        reg = _load_templates()
        assert "dev" in reg["templates"]

    def test_invalid_json_falls_back(self, tmp_path, monkeypatch):
        f = tmp_path / "bad.json"
        f.write_text("{not valid")
        monkeypatch.setenv("AUTO_EDIT_ASSETS_TEMPLATES", str(f))
        reg = _load_templates()
        assert "dev" in reg["templates"]
```

- [ ] **Step 3: Rodar o teste e ver falhar**

Run: `python -m pytest tests/test_thumbnailer.py -v`
Expected: FAIL — `ImportError: cannot import name '_BUILTIN_TEMPLATES'`

- [ ] **Step 4: Implementar loader**

Em `tools/thumbnailer.py`, logo após o bloco `STYLE_MAP`/`DEFAULT_STYLE` (por volta da linha 62), adicionar:

```python
_BUILTIN_TEMPLATES = {
    "default": "dev",
    "templates": {
        "dev": {
            "description": "programação, frameworks, dicas de dev, carreira",
            "accent": [55, 224, 160],
            "grade": [[11, 31, 26], [6, 16, 13]],
            "sub_text_color": [4, 18, 12],
        },
        "maker": {
            "description": "impressão 3D, hardware, firmware, montagens, mods",
            "accent": [255, 159, 46],
            "grade": [[36, 22, 5], [15, 10, 5]],
            "sub_text_color": [26, 14, 0],
        },
        "gadget": {
            "description": "review de produto, unboxing, comparativo de gadgets",
            "accent": [255, 63, 134],
            "grade": [[38, 10, 26], [15, 5, 11]],
            "sub_text_color": [255, 255, 255],
        },
    },
}

_STYLE_HINT_COMPAT = {
    "bold-energy": "gadget",
    "clean-minimal": "dev",
    "dramatic": "gadget",
    "fun-colorful": "maker",
}


def _load_templates() -> dict:
    """Load the template registry from JSON, falling back to built-in defaults."""
    candidates: list[Path] = []
    env = os.environ.get("AUTO_EDIT_ASSETS_TEMPLATES")
    if env:
        candidates.append(Path(env))
    candidates.append(_repo_root() / "assets" / "thumbnails" / "templates.json")

    for p in candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text())
                if isinstance(data, dict) and data.get("templates"):
                    return data
        except Exception:
            continue
    return _BUILTIN_TEMPLATES
```

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `python -m pytest tests/test_thumbnailer.py -v`
Expected: PASS (4 testes)

- [ ] **Step 6: Commit**

```bash
git add assets/thumbnails/templates.json tools/thumbnailer.py tests/test_thumbnailer.py
git commit -m "feat: registry data-driven de templates de thumbnail"
```

---

### Task 2: Resolução de template (compat com style_hint)

**Files:**
- Modify: `tools/thumbnailer.py` (adicionar `_resolve_template` após `_load_templates`)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Consumes: `_load_templates()`, `_STYLE_HINT_COMPAT` (Task 1).
- Produces: `_resolve_template(name: str | None, style_hint: str | None, registry: dict) -> tuple[str, dict]` — retorna `(template_name, template_dict)`.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_thumbnailer.py`:

```python
from tools.thumbnailer import _resolve_template


class TestResolveTemplate:
    def setup_method(self):
        self.reg = _BUILTIN_TEMPLATES

    def test_explicit_name_wins(self):
        name, tpl = _resolve_template("maker", None, self.reg)
        assert name == "maker"
        assert tpl["accent"] == [255, 159, 46]

    def test_unknown_name_falls_back_to_default(self):
        name, _ = _resolve_template("banana", None, self.reg)
        assert name == "dev"

    def test_legacy_style_hint_maps(self):
        name, _ = _resolve_template(None, "bold-energy", self.reg)
        assert name == "gadget"

    def test_none_uses_default(self):
        name, _ = _resolve_template(None, None, self.reg)
        assert name == "dev"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_thumbnailer.py::TestResolveTemplate -v`
Expected: FAIL — `cannot import name '_resolve_template'`

- [ ] **Step 3: Implementar**

Adicionar em `tools/thumbnailer.py` após `_load_templates`:

```python
def _resolve_template(
    name: str | None, style_hint: str | None, registry: dict
) -> tuple[str, dict]:
    """Resolve a template by explicit name, legacy style_hint, or default."""
    templates = registry.get("templates", {})
    default_name = registry.get("default")
    if default_name not in templates:
        default_name = next(iter(templates), None)

    if name and name in templates:
        return name, templates[name]

    if style_hint:
        mapped = _STYLE_HINT_COMPAT.get(style_hint)
        if mapped in templates:
            return mapped, templates[mapped]

    return default_name, templates.get(default_name, {})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_thumbnailer.py::TestResolveTemplate -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Commit**

```bash
git add tools/thumbnailer.py tests/test_thumbnailer.py
git commit -m "feat: resolucao de template com compat de style_hint"
```

---

### Task 3: Colocação na zona segura (função pura)

**Files:**
- Modify: `tools/thumbnailer.py` (adicionar constantes de safe-zone + `_safe_block_top`, perto das dimensões no topo)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Produces: constantes `IG_SAFE_TOP=0.22`, `IG_SAFE_BOT=0.78`, `FACE_ZONE_TOP=0.52`; `_safe_block_top(h: int, total_h: int, position: str = "center") -> int` — topo do bloco de texto, clampado à zona segura.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_thumbnailer.py`:

```python
from tools.thumbnailer import (
    _safe_block_top,
    IG_SAFE_TOP,
    IG_SAFE_BOT,
    FACE_ZONE_TOP,
)


class TestSafeBlockTop:
    H = 1920

    def test_center_small_block_at_upper_safe(self):
        top = _safe_block_top(self.H, 300, "center")
        assert top == int(self.H * 0.24)
        assert top >= int(self.H * IG_SAFE_TOP)
        assert top + 300 <= int(self.H * FACE_ZONE_TOP)

    def test_center_tall_block_pinned_to_top_limit(self):
        # block too tall to fit above the face zone -> pinned at safe top
        top = _safe_block_top(self.H, 900, "center")
        assert top == int(self.H * IG_SAFE_TOP)

    def test_center_never_above_safe_top(self):
        for total_h in (100, 400, 700, 1200):
            top = _safe_block_top(self.H, total_h, "center")
            assert top >= int(self.H * IG_SAFE_TOP)

    def test_left_stays_within_safe_bottom(self):
        top = _safe_block_top(self.H, 300, "left")
        assert top >= int(self.H * IG_SAFE_TOP)
        assert top + 300 <= int(self.H * IG_SAFE_BOT)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_thumbnailer.py::TestSafeBlockTop -v`
Expected: FAIL — `cannot import name '_safe_block_top'`

- [ ] **Step 3: Implementar**

Em `tools/thumbnailer.py`, logo após `LONG_SIZE`/`ENERGY_RESOLUTION` (por volta da linha 27):

```python
# ── Instagram safe zone (grid crops 9:16 to center 1:1) ─────────────────────
IG_SAFE_TOP = 0.22   # abaixo disso a grid corta o topo
IG_SAFE_BOT = 0.78   # acima disso a grid corta a base
FACE_ZONE_TOP = 0.52  # texto do short não invade abaixo daqui (rosto ~0.55–0.65)


def _safe_block_top(h: int, total_h: int, position: str = "center") -> int:
    """Top-y for the text block, clamped into the Instagram safe zone.

    center/upper: block sits in the upper safe zone, above the face zone.
    left/right:   block may extend down to the safe bottom.
    """
    if position in ("left", "right"):
        desired = int(h * 0.35) - total_h // 2
        bottom_limit = int(h * IG_SAFE_BOT)
    else:
        desired = int(h * 0.24)
        bottom_limit = int(h * FACE_ZONE_TOP)

    top_limit = int(h * IG_SAFE_TOP)
    max_top = bottom_limit - total_h
    block_top = min(desired, max_top)
    block_top = max(block_top, top_limit)
    return block_top
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_thumbnailer.py::TestSafeBlockTop -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Commit**

```bash
git add tools/thumbnailer.py tests/test_thumbnailer.py
git commit -m "feat: colocacao de texto na zona segura do instagram"
```

---

### Task 4: Chip do sub_text + grade por tipo

**Files:**
- Modify: `tools/thumbnailer.py` (adicionar `_draw_sub_chip` e `_apply_grade`)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Produces:
  - `_draw_sub_chip(img: Image.Image, text: str, font, accent: tuple, text_color: tuple, center_xy: tuple[int,int]) -> Image.Image` — desenha retângulo arredondado accent + texto centrado; retorna RGBA.
  - `_apply_grade(img: Image.Image, grade: list | None, strength: float = 0.22) -> Image.Image` — overlay de gradiente vertical `[topo, base]`; retorna RGB do mesmo tamanho.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_thumbnailer.py`:

```python
from tools.thumbnailer import _draw_sub_chip, _apply_grade


class TestSubChip:
    def test_chip_paints_accent_pixels(self):
        img = Image.new("RGBA", (300, 120), (0, 0, 0, 255))
        font = ImageFont.load_default(size=24)
        out = _draw_sub_chip(img, "SÓ R$100", font, (255, 0, 0), (255, 255, 255), (150, 60))
        arr = np.asarray(out.convert("RGB"))
        # há pixels vermelhos do chip
        red = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] < 60)
        assert red.sum() > 0


class TestApplyGrade:
    def test_same_size_and_changes_pixels(self):
        img = Image.new("RGB", (200, 400), (128, 128, 128))
        out = _apply_grade(img, [[255, 0, 0], [0, 0, 255]])
        assert out.size == img.size
        arr = np.asarray(out)
        # topo puxa vermelho, base puxa azul
        assert int(arr[5, 100, 0]) > int(arr[395, 100, 0])
        assert int(arr[395, 100, 2]) > int(arr[5, 100, 2])

    def test_none_grade_returns_rgb(self):
        img = Image.new("RGB", (50, 50), (10, 20, 30))
        out = _apply_grade(img, None)
        assert out.mode == "RGB"
        assert out.size == (50, 50)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_thumbnailer.py::TestSubChip tests/test_thumbnailer.py::TestApplyGrade -v`
Expected: FAIL — `cannot import name '_draw_sub_chip'`

- [ ] **Step 3: Implementar**

Adicionar em `tools/thumbnailer.py` (perto de `_draw_dark_band`, na seção de text rendering):

```python
def _draw_sub_chip(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    accent: tuple,
    text_color: tuple,
    center_xy: tuple[int, int],
) -> Image.Image:
    """Draw sub_text as a filled rounded chip in the accent color."""
    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x = max(10, int(th * 0.5))
    pad_y = max(6, int(th * 0.30))
    cx, cy = center_xy

    x0 = cx - tw // 2 - pad_x
    y0 = cy - th // 2 - pad_y
    x1 = cx + tw // 2 + pad_x
    y1 = cy + th // 2 + pad_y
    radius = max(6, (y1 - y0) // 3)

    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=tuple(accent))
    draw.text((cx, cy), text, font=font, fill=tuple(text_color), anchor="mm")
    return img


def _apply_grade(
    img: Image.Image, grade: list | None, strength: float = 0.22
) -> Image.Image:
    """Blend a subtle vertical [top, bottom] color grade over the frame."""
    img = img.convert("RGB")
    if not grade:
        return img
    arr = np.asarray(img, dtype=np.float32)
    h = arr.shape[0]
    top = np.array(grade[0], dtype=np.float32)
    bottom = np.array(grade[1], dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    overlay = top[None, None, :] + (bottom - top)[None, None, :] * ramp
    out = arr * (1.0 - strength) + overlay * strength
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_thumbnailer.py::TestSubChip tests/test_thumbnailer.py::TestApplyGrade -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add tools/thumbnailer.py tests/test_thumbnailer.py
git commit -m "feat: chip do sub_text e grade de cor por tipo"
```

---

### Task 5: Ligar template no render (short + long)

**Files:**
- Modify: `tools/thumbnailer.py` (`_draw_thumbnail_text`, `_thumbnail_short`, `_thumbnail_long`)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Consumes: `_resolve_template`, `_load_templates`, `_safe_block_top`, `_draw_sub_chip`, `_apply_grade` (Tasks 1–4).
- Produces: `_draw_thumbnail_text(img, main_text, sub_text, template: dict, position="center") -> Image.Image` (assinatura muda: `style_hint: str` → `template: dict`).

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_thumbnailer.py`:

```python
from tools.thumbnailer import _draw_thumbnail_text


class TestDrawThumbnailText:
    def test_accepts_template_dict_and_renders(self):
        img = Image.new("RGB", (1080, 1920), (40, 40, 40))
        template = _BUILTIN_TEMPLATES["templates"]["gadget"]
        out = _draw_thumbnail_text(img, "CASE DA GOPRO", "SÓ R$100", template, "center")
        assert out.size == (1080, 1920)
        arr = np.asarray(out.convert("RGB"))
        # chip magenta do gadget aparece em algum lugar
        magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 90) & (arr[:, :, 2] > 110)
        assert magenta.sum() > 0

    def test_no_subtext_still_renders(self):
        img = Image.new("RGB", (1080, 1920), (40, 40, 40))
        template = _BUILTIN_TEMPLATES["templates"]["dev"]
        out = _draw_thumbnail_text(img, "CAIU O FLUTTER", None, template, "center")
        assert out.size == (1080, 1920)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_thumbnailer.py::TestDrawThumbnailText -v`
Expected: FAIL — `_draw_thumbnail_text() got ... 'template'` / TypeError de assinatura

- [ ] **Step 3: Substituir `_draw_thumbnail_text`**

Trocar a função `_draw_thumbnail_text` inteira (linhas ~581–687) por:

```python
def _draw_thumbnail_text(
    img: Image.Image,
    main_text: str,
    sub_text: str | None,
    template: dict,
    position: str = "center",
) -> Image.Image:
    """Overlay main_text (branco condensado) e sub_text (chip accent) na safe zone."""
    img = img.convert("RGBA")
    font_path = _find_font()
    w, h = img.size

    accent_color = tuple(template.get("accent", [255, 220, 0]))
    sub_text_color = tuple(template.get("sub_text_color", [0, 0, 0]))

    main_text = main_text.upper()
    max_text_width = int(w * 0.55) if position in ("left", "right") else int(w * 0.72)

    main_font, main_lines = _auto_size_font(
        font_path, main_text, max_text_width,
        max_size=int(w * 0.13), min_size=int(w * 0.05), max_lines=2,
    )
    sample_bbox = main_font.getbbox("Ag")
    line_h = sample_bbox[3] - sample_bbox[1]
    line_spacing = int(line_h * 0.15)
    main_block_h = line_h * len(main_lines) + line_spacing * (len(main_lines) - 1)

    sub_font = None
    sub_lines: list[str] = []
    sub_line_h = 0
    if sub_text:
        sub_text = sub_text.upper()
        sub_font, sub_lines = _auto_size_font(
            font_path, sub_text, int(w * 0.80),
            max_size=int(w * 0.075), min_size=int(w * 0.035), max_lines=1,
        )
        sub_bbox = sub_font.getbbox("Ag")
        sub_line_h = sub_bbox[3] - sub_bbox[1]

    chip_extra = int(sub_line_h * 0.6) if sub_lines else 0
    gap = int(line_h * 0.4) if sub_lines else 0
    total_h = main_block_h + gap + (sub_line_h + chip_extra if sub_lines else 0)

    block_top = _safe_block_top(h, total_h, position)

    if position == "left":
        text_x = int(w * 0.05)
        anchor = "lm"
    elif position == "right":
        text_x = int(w * 0.95)
        anchor = "rm"
    else:
        text_x = w // 2
        anchor = "mm"

    band_center = block_top + total_h // 2
    band_center = min(band_center, int(h * IG_SAFE_BOT) - int(line_h * 0.3))
    img = _draw_dark_band(img, band_center, total_h + int(line_h * 0.6))

    draw = ImageDraw.Draw(img)
    outline_w = max(6, int(line_h * 0.08))

    y = block_top
    for line in main_lines:
        _draw_text_with_outline(
            draw, (text_x, y + line_h // 2), line,
            main_font, (255, 255, 255), (0, 0, 0),
            outline_width=outline_w, anchor=anchor,
        )
        y += line_h + line_spacing

    if sub_lines and sub_font:
        y += gap
        chip_cx = w // 2 if anchor == "mm" else text_x
        img = _draw_sub_chip(
            img, sub_lines[0], sub_font, accent_color, sub_text_color,
            (chip_cx, y + sub_line_h // 2),
        )

    return img.convert("RGB")
```

- [ ] **Step 4: Atualizar `_thumbnail_short`**

Trocar o corpo de `_thumbnail_short` (linhas ~693–730) por:

```python
def _thumbnail_short(workspace: Path, metadata: dict, pipeline: dict) -> Path:
    """Generate thumbnail for short video: best frame + template + bold text."""
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("short_title", ""))
    sub_text = thumb_data.get("sub_text")

    registry = _load_templates()
    template_name, template = _resolve_template(
        thumb_data.get("template"), thumb_data.get("style_hint"), registry
    )
    print(f"[thumbnailer] template={template_name}")

    w, h = SHORT_SIZE

    transcription_path = workspace / "transcription.json"
    transcription = json.loads(transcription_path.read_text()) if transcription_path.exists() else {}

    duration = transcription.get("duration", 30.0)
    energy_peak = _find_energy_peak(transcription)
    video_path = pipeline["video_path"]

    frame_path = _pick_best_frame(video_path, duration, workspace, energy_peak)

    img = Image.open(frame_path)
    img = _crop_center(img, w, h)
    img = _apply_grade(img, template.get("grade"))

    img = _draw_thumbnail_text(img, main_text, sub_text, template, position="center")

    output = workspace / "thumbnail.png"
    img.save(output, "PNG", quality=95)
    print(f"[thumbnailer] Short thumbnail → {output}")

    frame_path.unlink(missing_ok=True)
    return output
```

(Isso remove o compositing de logo do short — sem marca fixa.)

- [ ] **Step 5: Atualizar `_thumbnail_long` para a nova assinatura**

Em `_thumbnail_long`, resolver o template e passá-lo ao texto. Trocar o começo (linhas ~735–738) de:

```python
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("youtube_title", ""))
    sub_text = thumb_data.get("sub_text")
    style_hint = thumb_data.get("style_hint", DEFAULT_STYLE)
    context = pipeline.get("context", "")
```

por:

```python
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("youtube_title", ""))
    sub_text = thumb_data.get("sub_text")
    style_hint = thumb_data.get("style_hint", DEFAULT_STYLE)
    context = pipeline.get("context", "")

    registry = _load_templates()
    _, template = _resolve_template(
        thumb_data.get("template"), thumb_data.get("style_hint"), registry
    )
```

E a chamada de texto (linha ~786), trocar:

```python
    img_rgb = _draw_thumbnail_text(img_rgb, main_text, sub_text, style_hint, position=text_pos)
```

por:

```python
    img_rgb = _draw_thumbnail_text(img_rgb, main_text, sub_text, template, position=text_pos)
```

(Os geradores de background do long — `_generate_imagen_bg`, `_generate_gradient_bg`, `_stylize_frame_bg` — continuam usando `style_hint` como estão. Não mexer neles.)

- [ ] **Step 6: Rodar a suíte inteira**

Run: `python -m pytest tests/test_thumbnailer.py -v`
Expected: PASS (todos). Rodar também `python -m pytest tests/ -v` para garantir que nada quebrou.

- [ ] **Step 7: Lint**

Run: `ruff check tools/thumbnailer.py tests/test_thumbnailer.py --select E,F,W --ignore E501`
Expected: sem erros. Corrigir imports não usados (ex: `STYLE_MAP`/`DEFAULT_STYLE` se ficarem órfãos — manter `DEFAULT_STYLE` só se ainda referenciado no long; senão remover).

- [ ] **Step 8: Commit**

```bash
git add tools/thumbnailer.py tests/test_thumbnailer.py
git commit -m "feat: renderiza thumbnail via template (safe-zone + chip + grade)"
```

---

### Task 6: Agente de metadata — campo template + copy do gancho

**Files:**
- Modify: `agents/metadata.md`

**Interfaces:**
- Consumes: nomes de template do registry (`dev`/`maker`/`gadget`) — mantidos em sync manual com `templates.json`.
- Produces: schema com `thumbnail.template` e `sub_text` como gancho. Sem teste automatizado (é prompt); validação manual no Step 4.

- [ ] **Step 1: Reescrever a seção "Thumbnail Text"**

Substituir a seção `## Thumbnail Text` (linhas ~19–30) por:

```markdown
## Thumbnail Text

Generate a `thumbnail` object with text optimized for a video thumbnail image. This is NOT the title — it is the bold, visual text that grabs attention at a glance in the Instagram feed.

- `main_text`: The hero text. 2–5 impactful words, read instantly. Carry a promise or tension. Same language as the video.
- `sub_text`: A **hook**, not a description. Máx 30 chars. Creates a curiosity/tension gap that only the video closes. Renders inside a colored chip for pop.
  - ❌ describes: "FEITA EM 3D", "REVIEW COMPLETO", "TUTORIAL"
  - ✅ hooks: "NINGUÉM FAZ ISSO", "SÓ R$100", "-70% DE ERRO", "E DEU CERTO?"
  - Numbers, prices and specs count as hooks when surprising. Set to null if `main_text` is self-sufficient.
- `template`: The content-type template that drives the thumbnail's color identity. Choose ONE:
  - `"dev"` — programação, frameworks, dicas de dev, carreira
  - `"maker"` — impressão 3D, hardware, firmware, montagens, mods
  - `"gadget"` — review de produto, unboxing, comparativo de gadgets
  If none fits, use `"dev"`.
```

(Remove `style_hint` e `logos` da seção do short. `style_hint` continua aceito pelo pipeline por compat, mas não é mais pedido.)

- [ ] **Step 2: Atualizar o schema de exemplo (short)**

Trocar o bloco `Schema for short` (linhas ~40–51) por:

```markdown
Schema for short:
{
  "short_title": "...",
  "hook": "...",
  "hashtags": ["receita", "paocaseiro", ...],
  "thumbnail": {
    "main_text": "PEÇA 3D QUEBROU",
    "sub_text": "E A IA RESOLVEU?",
    "template": "maker"
  }
}
```

- [ ] **Step 3: Atualizar o schema de exemplo (long)**

Trocar o bloco `Schema for long` (linhas ~53–64) por:

```markdown
Schema for long:
{
  "youtube_title": "...",
  "youtube_description": "...",
  "tags": ["pão caseiro", "como fazer pão", ...],
  "thumbnail": {
    "main_text": "META AI RAY-BAN GEN 2",
    "sub_text": "VALE OS R$1500?",
    "template": "gadget",
    "logos": ["meta", "rayban"]
  }
}
```

(Long mantém `logos` — ainda usa face/logo asset.)

- [ ] **Step 4: Verificação manual end-to-end**

Rodar o stage de thumbnail num vídeo real e conferir visualmente:

Run: `auto-edit resume <video.mp4> --from metadata` (ou o stage que dispara metadata+thumbnail)
Verificar em `workspace/.../thumbnail.png`:
- Texto principal 100% dentro do quadrado central (abrir a imagem, o miolo vertical 22–78% contém main+sub).
- Chip do sub_text na cor do template escolhido.
- Rosto não tapado pelo texto.

- [ ] **Step 5: Commit**

```bash
git add agents/metadata.md
git commit -m "feat: metadata escolhe template e escreve sub_text como gancho"
```

---

## Self-Review

**Spec coverage:**
- §3 safe-zone → Task 3 (`_safe_block_top`) + Task 5 (uso em `_draw_thumbnail_text`). ✓
- §4 registry data-driven → Task 1 (`templates.json` + `_load_templates`) + Task 2 (`_resolve_template`). ✓
- §4 chip do sub → Task 4 (`_draw_sub_chip`) + Task 5 (uso). ✓
- §4 grade por tipo → Task 4 (`_apply_grade`) + Task 5. ✓
- §4 compat style_hint → Task 2 (`_STYLE_HINT_COMPAT` + resolução). ✓
- §5 metadata template + copy do gancho → Task 6. ✓
- §2 sem marca fixa → Task 5 Step 4 (remove logo do short). ✓
- §6 testes (safe-zone, registry, compat, chip) → Tasks 1–5 cobrem; validação visual em Task 6 Step 4. ✓

**Placeholder scan:** Sem TBD/TODO. Todo step tem código ou comando concreto. ✓

**Type consistency:** `_resolve_template` retorna `(str, dict)` usado em Tasks 5. `_draw_thumbnail_text(..., template: dict, ...)` consistente entre definição (Task 5 Step 3) e chamadas (Steps 4–5). `_safe_block_top(h, total_h, position)` mesma assinatura em teste e uso. `_apply_grade`/`_draw_sub_chip` assinaturas batem entre Task 4 e Task 5. ✓
```
