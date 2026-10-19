# Thumbnail configurável (layout HTML da IA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A style can carry its own thumbnail layout (HTML + inline CSS written by the AI from a reference image), rendered by Satori in the pipeline, the previews and the AI's self-correction rounds.

**Architecture:** `tokens.thumbnail.html` is sanitized in Python (`auto_edit/thumb_html.py`) on every `validate()`. The renderer (`renderer/src/html.ts`) parses it with `ultrahtml`, fills placeholders, fits the title and hands the tree to Satori — reached through the existing `thumbnail`/`preview` commands when the spec has `html`. `agents.complete()` gains `images=`; `styles.generate()` becomes design → render → compare rounds, run as an engine task with SSE progress.

**Tech Stack:** Python 3.11 (Flask, Pillow, stdlib `html.parser`), Bun + TypeScript (Satori 0.57.2, resvg-wasm, opentype.js, ultrahtml 1.6.0), vanilla JS app.

**Spec:** `docs/superpowers/specs/2026-10-15-thumbnail-html-design.md`

## Global Constraints

- Only the long (16:9, 1280×720) thumbnail uses `html`; shorts and the overlays keep today's code.
- A thumbnail is never lost: html → default React layout → Pillow.
- Nothing saves by itself: AI returns a draft.
- Only bundled fonts; new ones are OFL static TTFs with their `OFL-*.txt`.
- Exported files never carry the brand.
- Allowed tags `div span p img`; attrs `style src data-fit`; `img src` only an image placeholder; no `url(` in CSS; ≤ 20 000 chars.
- Agents without vision (cursor, agy, opencode) never receive images; error text: "seu agente de IA não enxerga imagens — troque nas Configurações".
- New dependency pinned exactly: `ultrahtml` `1.6.0`.
- Tests: `python -m pytest tests/ -q`; lint `ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`; renderer `cd renderer && bun test`.

## Review Focus

1. HTML whose root is missing or has several top-level elements, or a `div` with several children and no `display` → Satori throws; expected: renderer wraps/adds `display:flex` and draws.
2. Title much longer than the reference's ("Como eu montei minha impressora 3D do zero em um fim de semana") → `data-fit` shrinks it inside its box, never overflows the frame.
3. Style imported from someone else with a hostile `html` (`<img src="https://…">`, `style="background:url(…)"`, `onerror`) → sanitized away on import; renderer never fetches anything.
4. AI answers prose, or a JSON without `html`, in a correction round → keep the previous layout, don't fail the job.
5. Agent set to Cursor with a reference image and a vision-capable fallback → the fallback runs; no fallback → the warning, and nothing runs.

Rulings already taken while planning (spec deviations):
- Spec §2 names a new `html` CLI command; the plan reuses `thumbnail` and `preview` (they switch on `spec.html`) — fewer code paths, same behavior.
- Two extra placeholders `{{titulo_inicio}}` / `{{titulo_fim}}` (title minus last word / last word), because the default layout already colors the last word and references often split the title.
- Text values are inserted into parsed text nodes (never re-parsed as HTML), so "escaping" is structural.

---

### Task 1: Display fonts

**Files:**
- Create: `assets/fonts/LuckiestGuy-Regular.ttf`, `LilitaOne-Regular.ttf`, `Bangers-Regular.ttf`, `ArchivoBlack-Regular.ttf` + `OFL-LuckiestGuy.txt`, `OFL-LilitaOne.txt`, `OFL-Bangers.txt`, `OFL-ArchivoBlack.txt`
- Modify: `auto_edit/styles.py` (`FONTS`)
- Test: `tests/test_styles.py`

**Interfaces:** Produces `FONTS` ids `luckiest`, `lilita`, `bangers`, `archivo` (labels "Luckiest Guy", "Lilita One", "Bangers", "Archivo Black").

- [ ] **Step 1: failing test**

```python
class TestDisplayFonts:
    @pytest.mark.parametrize("fid", ["luckiest", "lilita", "bangers", "archivo"])
    def test_new_display_fonts_ship_with_the_app(self, fid):
        assert styles.font_file(styles.FONTS[fid]["bold"]) is not None
```

- [ ] **Step 2:** `python -m pytest tests/test_styles.py -k DisplayFonts -q` → FAIL KeyError.
- [ ] **Step 3:** download from `https://raw.githubusercontent.com/google/fonts/main/ofl/<dir>/<File>` (`luckiestguy/LuckiestGuy-Regular.ttf`, `lilitaone/LilitaOne-Regular.ttf`, `bangers/Bangers-Regular.ttf`, `archivoblack/ArchivoBlack-Regular.ttf`, each dir's `OFL.txt` → `OFL-<Name>.txt`) into `assets/fonts/`; check `file` says TrueType. Add to `FONTS`:

```python
    "luckiest": {"label": "Luckiest Guy", "bold": "LuckiestGuy-Regular.ttf"},
    "lilita": {"label": "Lilita One", "bold": "LilitaOne-Regular.ttf"},
    "bangers": {"label": "Bangers", "bold": "Bangers-Regular.ttf"},
    "archivo": {"label": "Archivo Black", "bold": "ArchivoBlack-Regular.ttf"},
```

- [ ] **Step 4:** test → PASS; full suite green.
- [ ] **Step 5:** commit `feat(styles): fontes display (Luckiest Guy, Lilita One, Bangers, Archivo Black)`.

### Task 2: `thumb_html.sanitize` + token

**Files:**
- Create: `auto_edit/thumb_html.py`
- Modify: `auto_edit/styles.py` (`validate`, `thumbnail` token)
- Test: `tests/test_thumb_html.py`, `tests/test_styles.py`

**Interfaces:**
- Produces: `thumb_html.sanitize(html: str) -> str` (raises `ThumbHtmlError(ValueError)`), `thumb_html.placeholders(html) -> set[str]`, `IMAGE_SLOTS = ("frame", "frame2", "rosto", "logo")`, `TEXT_SLOTS = ("titulo", "titulo_inicio", "titulo_fim", "etiqueta")`, `MAX_CHARS = 20000`.
- `validate()` keeps `tokens["thumbnail"]["html"]` only when it sanitizes; key absent otherwise.

- [ ] **Step 1: failing tests** (`tests/test_thumb_html.py`)

```python
import pytest
from auto_edit import thumb_html as th

OK = '<div style="display:flex;width:1280px;height:720px"><img src="{{frame}}" style="width:1280px"/><span data-fit="linhas:2;min:60;max:160" style="color:{{destaque}}">{{titulo}}</span></div>'

def test_keeps_a_good_layout():
    out = th.sanitize(OK)
    assert "{{frame}}" in out and "{{titulo}}" in out and 'data-fit="linhas:2;min:60;max:160"' in out

def test_strips_scripts_styles_links_and_handlers():
    out = th.sanitize('<div onclick="x()"><script>alert(1)</script><style>*{}</style><link href="a"><span>oi</span></div>')
    assert "script" not in out and "style>" not in out and "link" not in out and "onclick" not in out and "oi" in out

def test_img_with_a_foreign_src_is_dropped():
    out = th.sanitize('<div><img src="https://evil/x.png"/><img src="{{logo}}"/></div>')
    assert "evil" not in out and "{{logo}}" in out

def test_css_url_is_removed():
    out = th.sanitize('<div style="background:url(https://x/y.png);color:red">a</div>')
    assert "url(" not in out and "color:red" in out

def test_unknown_tags_are_unwrapped_keeping_text():
    assert "<b" not in th.sanitize("<div><b>forte</b></div>") and "forte" in th.sanitize("<div><b>forte</b></div>")

def test_empty_or_huge_raises():
    with pytest.raises(th.ThumbHtmlError):
        th.sanitize("<script>x</script>")
    with pytest.raises(th.ThumbHtmlError):
        th.sanitize("<div>" + "a" * 20001 + "</div>")

def test_placeholders():
    assert th.placeholders(OK) == {"frame", "titulo", "destaque"}
```

In `tests/test_styles.py`:

```python
class TestThumbnailHtml:
    def test_html_survives_validate(self):
        t = styles.validate({"thumbnail": {"html": '<div><span>{{titulo}}</span></div>'}})
        assert "{{titulo}}" in t["thumbnail"]["html"]

    def test_bad_html_is_dropped(self):
        assert "html" not in styles.validate({"thumbnail": {"html": "<script>x</script>"}})["thumbnail"]

    def test_import_sanitizes(self, home):
        s = styles.import_({"format": 1, "name": "X", "tokens": {"thumbnail": {"html": '<div><img src="http://a/b.png"/><span>{{titulo}}</span></div>'}}})
        assert "http" not in s["tokens"]["thumbnail"]["html"]
```

(`home` = the existing fixture in `tests/test_styles.py` that points `AUTO_EDIT_HOME` at tmp; reuse its name.)

- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3: implement** `auto_edit/thumb_html.py`:

```python
"""A style's thumbnail layout: HTML + inline CSS (written by the AI), made
safe before it is saved — only layout tags, no scripts, nothing external."""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

TAGS = {"div", "span", "p", "img"}
DROP = {"script", "style", "link", "iframe", "object", "svg", "head", "title", "meta", "template", "noscript"}
ATTRS = {"style", "src", "data-fit"}
IMAGE_SLOTS = ("frame", "frame2", "rosto", "logo")
TEXT_SLOTS = ("titulo", "titulo_inicio", "titulo_fim", "etiqueta")
MAX_CHARS = 20000
_SLOT = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")


class ThumbHtmlError(ValueError):
    pass


def _clean_style(css: str) -> str:
    decls = [d.strip() for d in css.split(";")]
    keep = [d for d in decls if d and ":" in d and "url(" not in d.lower() and "expression" not in d.lower()]
    return ";".join(keep)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0  # inside a dropped tag
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.skip += 1
            return
        if self.skip or tag not in TAGS:
            return
        kept = []
        for k, v in attrs:
            if k not in ATTRS or v is None:
                continue
            if k == "style":
                v = _clean_style(v)
            if k == "src" and not re.fullmatch(r"\{\{\s*(%s)\s*\}\}" % "|".join(IMAGE_SLOTS), v.strip()):
                return  # an image from anywhere else: drop the element
            kept.append(f'{k}="{_html.escape(v, quote=True)}"')
        attr = (" " + " ".join(kept)) if kept else ""
        if tag == "img":
            if not any(a.startswith("src=") for a in kept):
                return
            self.out.append(f"<img{attr}/>")
            return
        self.out.append(f"<{tag}{attr}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in DROP:
            self.skip -= 1
        elif tag in TAGS and tag != "img" and self.stack and self.stack[-1] == tag:
            self.stack.pop()
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag):
        if tag in DROP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in TAGS or tag == "img":
            return
        if tag in self.stack:
            while self.stack:
                t = self.stack.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.out.append(_html.escape(data, quote=False))


def sanitize(html: str) -> str:
    if not isinstance(html, str) or not html.strip():
        raise ThumbHtmlError("layout vazio")
    if len(html) > MAX_CHARS:
        raise ThumbHtmlError(f"layout grande demais (máx. {MAX_CHARS} caracteres)")
    p = _Cleaner()
    p.feed(html)
    p.close()
    out = "".join(p.out) + "".join(f"</{t}>" for t in reversed(p.stack))
    if not re.search(r"<(div|span|p|img)\b", out):
        raise ThumbHtmlError("layout sem nenhum elemento")
    return out


def placeholders(html: str) -> set[str]:
    return set(_SLOT.findall(html or ""))
```

In `styles.validate()`, build the thumbnail dict:

```python
    thumb_out = {"accent_from": _choice(thumb.get("accent_from"), ("topic", "style"), d["thumbnail"]["accent_from"])}
    if isinstance(thumb.get("html"), str) and thumb["html"].strip():
        try:
            thumb_out["html"] = thumb_html.sanitize(thumb["html"])
        except thumb_html.ThumbHtmlError:
            pass
    ...
        "thumbnail": thumb_out,
```

(`from auto_edit import thumb_html` at top of styles.py.)

- [ ] **Step 4:** tests PASS; full suite + ruff green.
- [ ] **Step 5:** commit `feat(styles): layout da thumbnail em HTML, limpo ao salvar`.

### Task 3: Renderer draws the HTML

**Files:**
- Create: `renderer/src/html.ts`, `renderer/src/html.test.ts`
- Modify: `renderer/src/cli.tsx`, `renderer/package.json` (ultrahtml 1.6.0, `"test": "bun test"`), `renderer/bun.lock`

**Interfaces:**
- Consumes: spec JSON with `html` (string), `values` ({titulo, titulo_inicio, titulo_fim, etiqueta, destaque, "cor.accent", "cor.panel", "cor.text"}), `images` ({frame, frame2, rosto, logo}: path | null), `fonts` ([{name, path, weight}]; the first is the default), `width`, `height`.
- Produces: `htmlTree(html, values, images: Record<string,string|null> /* data URLs */, measure: Record<string, Measurer>, defaultFont: string, w, h): object` (Satori VNode); `thumbnail`/`preview` commands draw it when `spec.html` is set.

- [ ] **Step 1: failing tests** (`renderer/src/html.test.ts`)

```ts
import { expect, test } from "bun:test";
import { htmlTree } from "./html";

const m = (t: string, s: number) => t.length * s * 0.5; // fake measurer
const V = { titulo: "Titulo grande demais pra caber numa linha so", titulo_inicio: "Titulo", titulo_fim: "so", etiqueta: "", destaque: "#00d6ff", "cor.accent": "#00d6ff", "cor.panel": "#111111", "cor.text": "#ffffff" };
const find = (n: any, pred: (n: any) => boolean): any => {
  if (!n || typeof n !== "object") return null;
  if (pred(n)) return n;
  const kids = Array.isArray(n.props?.children) ? n.props.children : [n.props?.children];
  for (const k of kids) { const r = find(k, pred); if (r) return r; }
  return null;
};

test("fills text and color placeholders", () => {
  const t = htmlTree('<div><span style="color:{{destaque}}">{{titulo}}</span><span>x</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  const span = find(t, (n) => n.type === "span" && n.props.style.color);
  expect(span.props.style.color).toBe("#00d6ff");
  expect(span.props.children).toBe(V.titulo);
});

test("img without a value and element left empty disappear", () => {
  const t = htmlTree('<div><img src="{{logo}}"/><span>{{etiqueta}}</span><span>fica</span></div>', V, { logo: null }, { Anton: m }, "Anton", 1280, 720);
  expect(find(t, (n) => n.type === "img")).toBeNull();
  expect(find(t, (n) => n.type === "span" && n.props.children === "")).toBeNull();
});

test("data-fit shrinks a long title into its box", () => {
  const t = htmlTree('<div><span data-fit="linhas:1;min:20;max:200" style="width:400px;font-family:Anton">{{titulo}}</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  const span = find(t, (n) => n.type === "span");
  expect(span.props.style.fontSize).toBeLessThan(200);
  expect(span.props.style.fontSize).toBeGreaterThanOrEqual(20);
});

test("unknown font family falls back to the default; multi-child div gets display:flex; root sized", () => {
  const t = htmlTree('<div><span style="font-family:Comic Sans">a</span><span>b</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  expect(t.props.style.display).toBe("flex");
  expect(t.props.style.width).toBe(1280);
  expect(find(t, (n) => n.type === "span").props.style.fontFamily).toBe("Anton");
});

test("several top-level elements are wrapped", () => {
  const t = htmlTree("<span>a</span><span>b</span>", V, {}, { Anton: m }, "Anton", 1280, 720);
  expect(t.type).toBe("div");
  expect(t.props.children.length).toBe(2);
});
```

- [ ] **Step 2:** `cd renderer && bun test` → FAIL (no ./html).
- [ ] **Step 3: implement** `renderer/src/html.ts`:

```ts
// A style's thumbnail layout (HTML + inline CSS, sanitized by
// auto_edit/thumb_html.py) → a Satori tree: placeholders filled, elements
// without a value removed, the title fitted with the real font.
import { parse, ELEMENT_NODE, TEXT_NODE } from "ultrahtml";
import { fit, type Measurer } from "./text";

type Values = Record<string, string>;
const SLOT = /\{\{\s*([a-z0-9_.]+)\s*\}\}/g;
const ENT: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&#x27;": "'" };
const unescape = (s: string) => s.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (e) => ENT[e]);
const px = (v: unknown) => (typeof v === "string" && /^-?[\d.]+px$/.test(v.trim()) ? parseFloat(v) : typeof v === "number" ? v : undefined);

function css(s: string): Record<string, any> {
  const out: Record<string, any> = {};
  for (const d of s.split(";")) {
    const i = d.indexOf(":");
    if (i < 1) continue;
    const key = d.slice(0, i).trim().toLowerCase().replace(/^-webkit-/, "Webkit-").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    out[key] = d.slice(i + 1).trim();
  }
  return out;
}

function parseFit(s: string) {
  const o: Record<string, number> = {};
  for (const part of s.split(";")) {
    const [k, v] = part.split(":").map((x) => x.trim());
    if (k && v && !isNaN(+v)) o[k] = +v;
  }
  return { lines: o.linhas ?? 2, min: o.min ?? 40, max: o.max ?? 160 };
}

export function htmlTree(html: string, values: Values, images: Record<string, string | null>, measure: Record<string, Measurer>,
                         defaultFont: string, w: number, h: number): any {
  const fill = (s: string) => s.replace(SLOT, (_, k) => values[k] ?? "");
  const fonts = new Set(Object.keys(measure));
  const fontOf = (style: Record<string, any>) => {
    const fam = String(style.fontFamily || "").split(",")[0].trim().replace(/^['"]|['"]$/g, "");
    return fonts.has(fam) ? fam : defaultFont;
  };

  function conv(n: any, inherited: string): any {
    if (n.type === TEXT_NODE) {
      const raw = unescape(String(n.value));
      const had = SLOT.test(raw);
      SLOT.lastIndex = 0;
      const t = fill(raw).replace(/\s+/g, " ").trim();
      return t ? t : had ? { empty: true } : null;
    }
    if (n.type !== ELEMENT_NODE) return null;
    const a = n.attributes || {};
    const style = a.style ? css(fill(a.style)) : {};
    if (style.fontFamily) style.fontFamily = fontOf(style);
    const font = style.fontFamily || inherited;
    if (n.name === "img") {
      const m = String(a.src || "").match(/\{\{\s*([a-z0-9]+)\s*\}\}/);
      const src = m ? images[m[1]] : null;
      return src ? { type: "img", props: { src, style } } : null;
    }
    const raw = (n.children || []).map((c: any) => conv(c, font)).filter((c: any) => c !== null);
    const kids = raw.filter((c: any) => !(c && c.empty));
    if (!kids.length && raw.length) return null; // only empty placeholders → the element goes away
    if (a["data-fit"] && kids.length === 1 && typeof kids[0] === "string") {
      const f = parseFit(a["data-fit"]);
      const box = px(style.width) ?? px(style.maxWidth) ?? w * 0.9;
      const maxH = px(style.height) ?? px(style.maxHeight) ?? h;
      style.fontSize = fit(kids[0], { box, maxH, max: f.max, min: f.min, maxLines: f.lines }, measure[font] || measure[defaultFont]);
    }
    if (kids.length > 1 && !style.display) style.display = "flex";
    return { type: n.name === "p" ? "div" : n.name, props: { style, children: kids.length === 1 ? kids[0] : kids } };
  }

  const top = parse(html).children.map((c: any) => conv(c, defaultFont)).filter((c: any) => c && !c.empty && typeof c !== "string");
  let root = top.length === 1 ? top[0] : { type: "div", props: { style: { display: "flex" }, children: top } };
  root.props.style = { display: "flex", position: "relative", overflow: "hidden", fontFamily: defaultFont, ...root.props.style, width: w, height: h };
  return root;
}
```

In `cli.tsx`: add

```ts
import { htmlTree } from "./html";

async function htmlSvg(raw: any): Promise<string> {
  const fonts = (raw.fonts || []).map((f: any) => {
    const b = fs.readFileSync(f.path);
    return { name: f.name, weight: f.weight || 400, data: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer };
  });
  if (!fonts.length) throw new Error("html: no fonts");
  const measure: Record<string, any> = {};
  for (const f of fonts) measure[f.name] ??= measurer(f.data);
  const images: Record<string, string | null> = {};
  for (const [k, p] of Object.entries(raw.images || {})) images[k] = p ? dataUrl(p as string) : null;
  const tree = htmlTree(raw.html, raw.values || {}, images, measure, fonts[0].name, raw.width, raw.height);
  return satori(tree, { width: raw.width, height: raw.height, fonts: fonts.map((f: any) => ({ name: f.name, data: f.data, weight: f.weight, style: "normal" })) });
}
```

and dispatch: in `thumbnail` → `writePng(spec.html ? await htmlSvg(spec) : await thumbnailSvg(spec), …)`; in `preview` → `spec.kind === "thumbnail" ? (spec.html ? await htmlSvg(spec) : await thumbnailSvg(...)) : …`. Bump `--version` to `auto-edit-render 4`. Update the header comment (html field).

- [ ] **Step 4:** `bun test` → 5 pass. Manual: write a spec JSON with the reference-like HTML (title + small line + circle `{{frame2}}`) and `bun run src/cli.tsx thumbnail spec.json out.png`; look at the PNG.
- [ ] **Step 5:** commit `feat(renderer): thumbnail a partir do layout HTML do estilo`.

### Task 4: Python side of the HTML render (spec builder + previews)

**Files:**
- Modify: `auto_edit/styles.py` (`html_spec`, `html_fonts`, `preview_frame(at=)`, `preview`, `render_thumbnail`, `sample_texts`)
- Test: `tests/test_styles.py`

**Interfaces:**
- Produces:
  - `styles.html_fonts(tokens) -> list[dict]` → `[{"name": label, "path": str, "weight": 400|700}]`, title font first (both weights), then every other `FONTS` entry.
  - `styles.html_spec(tokens, *, title: str, sub: str | None, accent: list[int], images: dict[str, str|None], width=1280, height=720) -> dict` (the renderer spec; `values` include `titulo_inicio`/`titulo_fim`, `destaque` as `#rrggbb`).
  - `styles.render_thumbnail(tokens, *, title=SAMPLE_TITLE, sub=SAMPLE_SUB) -> bytes` (PNG; cached; raises StyleError) — `preview(tokens, "thumbnail")` calls it.
  - `styles.sample_texts() -> tuple[str, str | None]`: the newest workspace's `metadata.json` `thumbnail.main_text`/`sub_text` (fallback `youtube_title`), else `("SEU TÍTULO AQUI", None)`.
  - `styles.preview_frame(at: float = 0.3)`.
  - `preview()` raises `StyleError("layout inválido: …")` when the raw tokens carry a non-empty `thumbnail.html` that doesn't sanitize.

- [ ] **Step 1: failing tests**

```python
class TestHtmlSpec:
    def test_values_images_and_fonts(self):
        t = styles.validate({"fonts": {"title": "bangers"}, "thumbnail": {"html": "<div><span>{{titulo}}</span></div>"}})
        spec = styles.html_spec(t, title="Montei uma impressora", sub="DIY", accent=[255, 0, 0], images={"frame": "/f.jpg"})
        assert spec["html"] == t["thumbnail"]["html"]
        assert spec["values"]["titulo_fim"] == "impressora" and spec["values"]["titulo_inicio"] == "Montei uma"
        assert spec["values"]["destaque"] == "#ff0000" and spec["values"]["cor.panel"] == t["colors"]["panel"]
        assert spec["fonts"][0]["name"] == "Bangers"
        assert spec["images"] == {"frame": "/f.jpg", "frame2": None, "rosto": None, "logo": None}

    def test_preview_reports_invalid_layout(self):
        with pytest.raises(styles.StyleError, match="layout"):
            styles.preview({"thumbnail": {"html": "<script>x</script>"}}, "thumbnail")

    def test_sample_texts_without_videos(self, home):
        assert styles.sample_texts() == ("SEU TÍTULO AQUI", None)
```

Plus one integration test, skipped when `render.command()` is None:

```python
    @pytest.mark.skipif(render.command() is None, reason="renderer not available")
    def test_renders_html_png(self, home):
        t = styles.validate({"thumbnail": {"html": '<div style="background:{{cor.panel}}"><span data-fit="linhas:2;min:40;max:150" style="width:1000px;color:#fff">{{titulo}}</span></div>'}})
        assert styles.render_thumbnail(t)[:4] == b"\x89PNG"
```

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement.** `html_fonts`: for the title font emit `{"name": label, "path": bold, "weight": 700}` and `{…, "weight": 400}` (regular file if present else bold), then the same for each other font id. `html_spec` builds `values` with `_hex(accent)`; `images` default all four keys to None. `render_thumbnail` = today's thumbnail branch of `preview()` moved out: when `"html" in tokens["thumbnail"]`, spec = `{"kind": "thumbnail", **html_spec(tokens, title=…, sub=…, accent=thumbnail_accent(tokens, [55,224,160]), images={"frame": str(frame) if frame else None, "frame2": str(preview_frame(0.7) or frame or "") or None, "rosto": face, "logo": brand.get("logo")})}` (face = first PNG in `assets/thumbnails/faces/` or `$AUTO_EDIT_ASSETS_FACES`; small helper `face_asset()`), else today's React spec; same cache + subprocess code. `preview_frame(at)` uses `duration * at` and includes `at` in the cache key.
- [ ] **Step 4:** PASS; suite green.
- [ ] **Step 5:** commit `feat(styles): prévia da thumbnail desenha o layout HTML`.

### Task 5: Pipeline uses the layout

**Files:**
- Modify: `tools/thumbnailer.py` (`_render_react`, `_thumbnail_long`, new `_pick_second_frame`)
- Test: `tests/test_thumbnailer.py`

**Interfaces:**
- Consumes: `styles.html_spec`, `thumb_html.placeholders`.
- Produces: `_pick_second_frame(video_path, duration, workspace, main_ts: float) -> Path | None`; `_pick_best_frame(..., with_ts=False)` returns `(path, ts)` when `with_ts=True` (path only otherwise, as today).

- [ ] **Step 1: failing tests** — monkeypatch `styles.active` to a style with html, `subprocess.run` to capture the spec file content, and assert:
  - long with `{{frame2}}` in html → spec has `html` and `images.frame2` set to a different file than `images.frame`;
  - html without `{{frame2}}` → `_pick_second_frame` not called (monkeypatch it to raise);
  - renderer exit 1 on the html spec → a second call without `html` (React default) happens;
  - short (`kind == "short"`) never sends `html`.
  Model on the existing `_render_react` tests in `tests/test_thumbnailer.py` (same fakes).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement.** In `_render_react(spec, output, extra_images=None)`: after loading tokens, when `spec["kind"] == "long"` and `"html" in tokens["thumbnail"]`, build `hspec = {**styles.html_spec(tokens, title=spec["main_text"], sub=spec.get("sub_text"), accent=spec["accent"], images={"frame": spec.get("background"), "rosto": spec.get("face"), "logo": (spec.get("logos") or [None])[0], **(extra_images or {})})}`, run the renderer with it; on failure print `[thumbnailer] HTML layout failed: … — using the default layout` and continue with today's call. `_thumbnail_long`: if the active style's html uses `frame2` and a frame was picked, `_pick_second_frame` = score candidates whose timestamp is ≥ 15% of the duration away from the main one, prefer `_score_face_region < 0.2`, return best path or None; pass `extra_images={"frame2": str(p)}`; unlink it afterwards. Imagen background path: `frame2` stays None.
- [ ] **Step 4:** PASS; suite green.
- [ ] **Step 5:** commit `feat(thumbnailer): layout HTML do estilo, segundo frame, cai pro padrão se falhar`.

### Task 6: Agents that see images

**Files:**
- Modify: `auto_edit/agents.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces: `VISION = {"claude", "codex", "openrouter", "ollama"}`, `NO_VISION = "seu agente de IA não enxerga imagens — troque nas Configurações"`, `vision_ready(env: dict | None = None) -> bool` (primary or fallback in VISION), `complete(prompt, *, images: list[Path] | None = None, timeout=120)`. `run_codex/run_openrouter/run_ollama(..., images=None)`.

- [ ] **Step 1: failing tests** (monkeypatch `_run`, `_openrouter`, `_ollama`, `find_binary`, `settings.env_from_settings`):

```python
def test_claude_gets_read_access_to_the_images(monkeypatch, tmp_path):
    img = tmp_path / "ref.png"; img.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(agents, "find_binary", lambda a: "/bin/claude")
    monkeypatch.setattr(agents, "_run", lambda cmd, stdin, t, env=None, cwd=None: seen.update(cmd=cmd, stdin=stdin) or "ok")
    agents._complete_one("claude", "faça", 10, {}, images=[img])
    i = seen["cmd"].index("--add-dir")
    assert seen["cmd"][i + 2:i + 4] == ["--allowedTools", "Read"] and seen["cmd"][-1] == "-p"
    assert "ref.png" in seen["stdin"]

def test_codex_gets_image_flags_before_other_options(monkeypatch, tmp_path): ...  # cmd[2:4] == ["-i", str(img)]
def test_openrouter_sends_image_url_parts(monkeypatch, tmp_path): ...  # body["messages"][0]["content"][1]["type"] == "image_url" and url startswith "data:image/png;base64,"
def test_ollama_sends_images_only_to_a_vision_model(monkeypatch, tmp_path): ...  # /api/show capabilities without "vision" → AgentError; with → body["messages"][0]["images"] == [b64]

def test_complete_skips_agents_without_vision(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "env_from_settings", lambda: {"AUTO_EDIT_LLM": "cursor", "AUTO_EDIT_LLM_FALLBACK": "claude"})
    called = []
    monkeypatch.setattr(agents, "_complete_one", lambda n, p, t, e, images=None: called.append(n) or "ok")
    agents.complete("x", images=[tmp_path / "a.png"])
    assert called == ["claude"]

def test_complete_without_any_vision_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "env_from_settings", lambda: {"AUTO_EDIT_LLM": "cursor"})
    with pytest.raises(agents.AgentError, match="não enxerga"):
        agents.complete("x", images=[tmp_path / "a.png"])
```

(Write the three `...` tests fully in the same style when implementing; assertions as noted.)

- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement.** `_complete_one(name, prompt, timeout, env, images=None)`: claude → `tempfile.TemporaryDirectory()`, copy images, prompt += `"\n\n# IMAGENS (abra com a ferramenta Read)\n" + "\n".join(paths)`, cmd `[binary, *model, "--add-dir", td, "--allowedTools", "Read", "-p"]`; others pass `images=images` to RUNNERS when given. `run_codex`: `cmd = [binary, "exec", *sum((["-i", str(p)] for p in images or []), []), "--sandbox", …]`. `run_openrouter`: content list when images. `run_ollama`: when images, `caps = _ollama("/api/show", {"model": model}).get("capabilities") or []`; no `"vision"` → `AgentError(f"o modelo {model} não enxerga imagens")`; add `"images": [b64…]` to the message. `complete`: when images, `names = [n for n in names if n in VISION]`; empty → `AgentError(NO_VISION)`.
- [ ] **Step 4:** PASS; suite green.
- [ ] **Step 5:** commit `feat(agents): complete() com imagens (Claude, Codex, OpenRouter, Ollama de visão)`.

### Task 7: Generation with rounds

**Files:**
- Modify: `auto_edit/styles.py` (`generate`), `agents/stylist.md` (rewrite)
- Create: `agents/stylist_review.md`
- Test: `tests/test_styles.py`

**Interfaces:**
- Consumes: `agents.complete(prompt, images=…)`, `agents.vision_ready()`, `styles.render_thumbnail`, `thumb_html.sanitize`.
- Produces: `styles.generate(description, image: bytes | None = None, *, base: dict | None = None, complete=None, render=None, on_progress=None, rounds=3, vision: bool | None = None) -> {"name","description","tokens"}`. `complete(prompt, images: list[Path]) -> str`; `render(tokens) -> bytes`. Progress messages: `"desenhando o layout"`, `"conferindo (volta N/R)"`. Errors: `"descreva o estilo ou mande uma imagem"`, `"a IA não devolveu um layout válido"`, `f"a IA falhou: {exc}"`, `NO_VISION` (as StyleError) when `image` and not vision.

- [ ] **Step 1: failing tests** (fake `complete` returns queued answers and records images; fake `render` returns `b"PNG"`):

```python
GOOD = {"name": "Choque", "description": "d", "tokens": {"colors": {"accent": "#00d6ff"}, "thumbnail": {"html": "<div><span>{{titulo}}</span></div>"}}}

def fake(answers):
    calls = []
    def run(prompt, images):
        calls.append((prompt, [p.name for p in images]))
        return answers.pop(0)
    return run, calls

def test_first_answer_then_ok_stops(home):
    run, calls = fake([json.dumps(GOOD), '{"ok": true}'])
    d = styles.generate("tech", b"img", complete=run, render=lambda t: b"PNG", vision=True)
    assert d["name"] == "Choque" and "{{titulo}}" in d["tokens"]["thumbnail"]["html"] and len(calls) == 2
    assert len(calls[1][1]) == 2  # reference + render

def test_corrected_html_replaces_and_max_rounds(home):
    fix = '{"html": "<div><span style=\\"color:red\\">{{titulo}}</span></div>"}'
    run, calls = fake([json.dumps(GOOD), fix, fix])
    d = styles.generate("x", b"img", complete=run, render=lambda t: b"PNG", rounds=3, vision=True)
    assert "color:red" in d["tokens"]["thumbnail"]["html"] and len(calls) == 3

def test_bad_round_keeps_previous(home):
    run, _ = fake([json.dumps(GOOD), "não sei", '{"html": "<script>x</script>"}'])
    d = styles.generate("x", b"img", complete=run, render=lambda t: b"PNG", vision=True)
    assert d["tokens"]["thumbnail"]["html"] == styles.validate(GOOD["tokens"])["thumbnail"]["html"]

def test_first_answer_without_layout_fails(home):
    run, _ = fake(['{"tokens": {"colors": {"accent": "#ff0000"}}}'])
    with pytest.raises(styles.StyleError, match="layout"):
        styles.generate("x", None, complete=run, render=lambda t: b"PNG", vision=True)

def test_render_failure_stops_rounds(home):
    run, calls = fake([json.dumps(GOOD)])
    def boom(t): raise styles.StyleError("x")
    styles.generate("x", b"img", complete=run, render=boom, vision=True)
    assert len(calls) == 1

def test_no_vision_with_image_refuses_and_without_image_skips_rounds(home):
    run, calls = fake([json.dumps(GOOD)])
    with pytest.raises(styles.StyleError, match="enxerga"):
        styles.generate("x", b"img", complete=run, render=lambda t: b"PNG", vision=False)
    d = styles.generate("x", None, complete=run, render=lambda t: b"PNG", vision=False)
    assert len(calls) == 1 and "html" in d["tokens"]["thumbnail"]

def test_progress_and_base(home):
    msgs = []
    run, calls = fake([json.dumps(GOOD), '{"ok": true}'])
    base = styles.validate({"thumbnail": {"html": "<div><span>ANTIGO {{titulo}}</span></div>"}})
    styles.generate("título maior", None, base=base, complete=run, render=lambda t: b"PNG", on_progress=msgs.append, vision=True)
    assert "ANTIGO" in calls[0][0] and msgs[0] == "desenhando o layout" and msgs[1] == "conferindo (volta 2/3)"
```

Remove/adjust the old `generate` tests that relied on palette colors in the prompt (they now must include `thumbnail.html` in fake answers).

- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement.**
  - `agents/stylist.md`: role = designer of YouTube thumbnails + overlays; with a reference image, reproduce its layout faithfully (positions, sizes, title split, stroke/shadow, shapes, circular insets) with the person's content; contract: 1280×720 root `div` with `display:flex; position:relative`, absolute positioning allowed, every element with 2+ children `display:flex`, tags `div span p img` only, inline `style` only, no `url()`, images only via `<img src="{{frame}}">` etc., text only via placeholders (list + meaning), `data-fit="linhas:N;min:A;max:B"` on the title element with explicit `width`/`height`, outline via `-webkit-text-stroke`, hard `text-shadow` (no blur), fonts by label (list appended), `object-fit:cover` on images; output JSON `{"name","description","tokens":{colors, fonts, …, "thumbnail":{"accent_from":…, "html":"…"}}}` (keep the overlay part of today's contract).
  - `agents/stylist_review.md`: "image 1 = reference (if any), image 2 = your render with the person's frame and title. Compare layout, sizes, positions, colors, fonts, effects. If close enough answer `{"ok": true}`; else answer `{"html": "…"}` with the full corrected HTML (same rules)." Without a reference: compare with the request text.
  - `generate`: build images in a `TemporaryDirectory` (`ref.png` from bytes, `render.png` per round), prompt = stylist.md + options (fonts as labels) + channel + request + (base tokens JSON when `base`); parse; `tokens = validate(tokens)`; no `html` → StyleError layout. Rounds `2..rounds` only when `vision`; each: `on_progress(f"conferindo (volta {r}/{rounds})")`, `png = render(tokens)` (StyleError → break), answer → `{"ok": true}` break; `{"html"}` → sanitize → replace, else keep; AgentError in a round → break. Default `complete` = `lambda p, imgs: agents.complete(p, images=imgs or None, timeout=AI_TIMEOUT)`, `render` = `lambda t: render_thumbnail(t, title=…, sub=…)` with `sample_texts()`, `vision` default `agents.vision_ready()`. Drop the `palette.extract` call.
- [ ] **Step 4:** PASS; suite green.
- [ ] **Step 5:** commit `feat(styles): IA desenha o layout da thumbnail e corrige comparando com a referência`.

### Task 8: Engine task + API

**Files:**
- Modify: `auto_edit/engine.py` (`JobManager.run_task`), `auto_edit/api.py` (generate/adjust/styles list)
- Test: `tests/test_api.py` (or the file holding the styles API tests — `grep -l "styles/generate" tests/`)

**Interfaces:**
- Produces: `JobManager.run_task(kind: str, target: Callable[[Emit], None]) -> Job` (not tied to a video; `video_id = f"_{kind}"`, not in `_by_video`). Events: `{"type":"progress","message":…}`, `{"type":"done","status":"done","result":draft}`, `{"type":"error","message":…}`.
- `POST /api/styles/generate {description, image?}` → 202 `{job_id}`; `POST /api/styles/adjust {tokens, request, image?}` → 202 `{job_id}`; non-object body / non-string description|request / tokens not object → 400. `GET /api/styles` gains `"ai_vision": agents.vision_ready()`.

- [ ] **Step 1: failing tests** — with `create_app(jobs=engine.JobManager())` and `styles.generate` monkeypatched to call `on_progress("desenhando o layout")` and return a draft: POST → 202 with `job_id`; wait for the job (`jobs.get(id)` status poll ≤ 2s); history has progress then done with `result`. Generate raising StyleError → error event with the plain message (no "StyleError:" prefix). Body `[]` → 400; `{"description": 3}` → 400. Adjust passes `base=tokens`. `GET /api/styles` has `ai_vision`. Assert `run_task` jobs don't appear in `active_ids()`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement** `run_task` (same thread wrapper as `_spawn`, without `_by_video`), api routes: `def _style_job(**kw)`: `def target(emit): try: emit({"type":"done","status":"done","result": styles.generate(**kw, on_progress=lambda m: emit({"type":"progress","message":m}))}) except styles.StyleError as exc: emit({"type":"error","message":str(exc)})`. Validate image with `_image_bytes` before starting (ValueError → 400). Update the docstring route list.
- [ ] **Step 4:** PASS; suite green.
- [ ] **Step 5:** commit `feat(api): criar e ajustar estilo com IA viram job com progresso`.

### Task 9: App

**Files:**
- Modify: `desktop/ui/js/api.js`, `desktop/ui/js/styles.js`, `desktop/ui/index.html`, `desktop/ui/styles.css`

**Interfaces:**
- Consumes: API from Task 8.
- Produces: `api.styleAiJob(path, body, onProgress) -> Promise<draft>` (POST then `EventSource(/api/jobs/<id>/events)`; resolves on `done.result`, rejects on `error.message`, closes the source).

- [ ] **Step 1:** `api.js`: `generateStyle(description, image, onProgress)` and `adjustStyle(tokens, request, onProgress)` on top of `styleAiJob`.
- [ ] **Step 2:** `styles.js`:
  - `generateAi`: if `state.aiImage && !state.data.ai_vision` → `setError("seu agente de IA não enxerga imagens — troque nas Configurações")`, return. Status text from progress (`el("sty-ai-status").textContent = msg`).
  - `takeAiImage`: shrink to ≤1280px (the AI now sees the image), JPEG 0.9.
  - Editor: section "Layout da thumbnail" with input `sty-adjust-req` + button `btn-sty-adjust` ("Ajustar com IA"; runs `adjustStyle(state.draft, req)` → replaces `state.draft` with result tokens, keeps name; same `setGenerating` lock + status `sty-adjust-status`); `<details id="sty-adv"><summary>Avançado: editar HTML</summary><textarea id="sty-html" spellcheck="false">` bound to `state.draft.thumbnail.html` (input → debounce 600ms → `refreshPreviews()`); button `btn-sty-html-reset` "Voltar pro layout padrão" (deletes `html`, refresh). Errors from the preview already go to `setError`.
- [ ] **Step 3:** `index.html` markup for the above, inside `#sty-editor`; `styles.css`: textarea monospace, min-height 220px, full width.
- [ ] **Step 4:** browser check (served `desktop/ui` on :8799 against the engine on :8760): create with the reference image → status shows "volta 2/3" → draft opens with the HTML preview; adjust with "título maior"; edit HTML by hand updates preview; reset button returns to default. Clean up test styles; active style back to `padrao`.
- [ ] **Step 5:** commit `feat(app): progresso da IA, Ajustar com IA e editor de HTML da thumbnail`.

### Task 10: CLI, smoke, docs

**Files:**
- Modify: `auto_edit/style_cli.py`, `scripts/smoke_engine.py`, `README.md`, `CLAUDE.md`, `tests/test_style_cli.py` (or where `style generate` is tested)

**Interfaces:** `auto-edit style generate [desc] --image --rounds N --save --activate` (prints progress lines `· desenhando o layout`); `auto-edit style adjust <id> "pedido" [--image] [--rounds] [--activate]` → always saves as new style named "<nome> (ajustado)".

- [ ] **Step 1: failing tests** (CliRunner, `styles.generate` monkeypatched): `adjust` calls generate with `base=<style tokens>` and saves a new style; `--rounds 1` passes `rounds=1`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** implement; smoke: add step "thumbnail from an HTML layout" that renders `styles.render_thumbnail(validate({... html with {{titulo}} and data-fit ...}))` and checks the PNG header; replace the palette smoke step only if it depended on generate (keep it otherwise). Docs: CLAUDE.md Estilos line (layout HTML da IA, voltas de correção, agentes com visão), routes (`/api/styles/adjust`, generate as job), README CLI examples.
- [ ] **Step 4:** full suite, ruff, `bun test`, `python scripts/smoke_engine.py` (or how the script is run — check its header) green.
- [ ] **Step 5:** commit `feat(cli): style adjust e --rounds; docs e smoke do layout HTML`.
