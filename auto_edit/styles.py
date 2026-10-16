"""Visual styles: how the thumbnail and the overlays look.

A style is data — colors, fonts, corners, positions, CTA texts — that the
React renderer (`renderer/`) applies to a layout. The presets live here; the
person's own styles in ``~/.auto-edit/styles/<id>.json``; the active one is
``settings["style"]``. Everything that comes in (a saved file, the app, an AI)
goes through :func:`validate`, which fills what's missing from the default and
drops what's invalid, so a style can never break a render.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from auto_edit import config as cfg
from auto_edit import overlay_assets
from auto_edit import thumb_html

DEFAULT_ID = "padrao"
POSITIONS_LT = ("bottom-left", "bottom-right", "top-left")
POSITIONS_CTA = ("bottom-center", "bottom-right", "top-right")
ICONS = ("like", "subscribe", "bell", "comment")
LAYOUTS = ("default",)

# Font id → files (static TTFs: Satori reads neither variable fonts nor WOFF2).
# `bold` draws titles and names; `regular` the handle (falls back to bold).
FONTS: dict[str, dict] = {
    "anton": {"label": "Anton", "bold": "Anton-Regular.ttf"},
    "bebas": {"label": "Bebas Neue", "bold": "BebasNeue-Regular.ttf"},
    "montserrat": {"label": "Montserrat", "bold": "Montserrat-ExtraBold.ttf", "regular": "Montserrat-SemiBold.ttf"},
    "poppins": {"label": "Poppins", "bold": "Poppins-ExtraBold.ttf", "regular": "Poppins-SemiBold.ttf"},
    # Display fonts for thumbnail layouts (auto_edit/thumb_html.py).
    "luckiest": {"label": "Luckiest Guy", "bold": "LuckiestGuy-Regular.ttf"},
    "lilita": {"label": "Lilita One", "bold": "LilitaOne-Regular.ttf"},
    "bangers": {"label": "Bangers", "bold": "Bangers-Regular.ttf"},
    "archivo": {"label": "Archivo Black", "bold": "ArchivoBlack-Regular.ttf"},
}

DEFAULT_TOKENS: dict = {
    "layout": "default",
    "colors": {"accent": "#00d6ff", "panel": "#140b2a", "text": "#ffffff"},
    "panel_opacity": 1.0,
    "radius": 22,
    "speed": 1.0,
    "fonts": {"title": "anton", "text": "montserrat"},
    "lower_third": {"position": "bottom-left", "avatar": True},
    "cta": {
        "position": "bottom-center",
        "steps": [
            {"icon": "like", "text": "DEIXE O LIKE!", "color": "#22d3ee"},
            {"icon": "subscribe", "text": "SE INSCREVA!", "color": "#ff3b3b"},
            {"icon": "bell", "text": "ATIVE O SINO!", "color": "#facc15"},
        ],
    },
    # "topic": the thumbnail's color follows the video's subject (the
    # thumbnail templates); "style": always this style's accent.
    "thumbnail": {"accent_from": "topic"},
}


def _preset(name: str, description: str, **changes) -> dict:
    tokens = copy.deepcopy(DEFAULT_TOKENS)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(tokens.get(key), dict):
            tokens[key].update(value)
        else:
            tokens[key] = value
    return {"name": name, "description": description, "tokens": tokens}


_PLAIN_STEPS = [
    {"icon": "like", "text": "DEIXE O LIKE!", "color": None},
    {"icon": "subscribe", "text": "SE INSCREVA!", "color": None},
    {"icon": "bell", "text": "ATIVE O SINO!", "color": None},
]

PRESETS: dict[str, dict] = {
    "padrao": _preset("Padrão", "Painel escuro, ícones coloridos, cor da thumbnail pelo assunto."),
    "minimal": _preset(
        "Minimal", "Discreto: branco sobre preto translúcido, cantos retos.",
        colors={"accent": "#f5f5f5", "panel": "#0a0a0a", "text": "#ffffff"},
        panel_opacity=0.72, radius=4, speed=0.85,
        fonts={"title": "bebas", "text": "poppins"},
        cta={"position": "bottom-right", "steps": _PLAIN_STEPS},
        thumbnail={"accent_from": "style"},
    ),
    "neon": _preset(
        "Neon", "Verde neon sobre preto, bem arredondado.",
        colors={"accent": "#39ff14", "panel": "#050805", "text": "#ffffff"},
        radius=34, fonts={"title": "anton", "text": "poppins"},
        cta={"position": "bottom-center", "steps": _PLAIN_STEPS},
        thumbnail={"accent_from": "style"},
    ),
    "impacto": _preset(
        "Impacto", "Amarelo e preto, chamativo, animação rápida.",
        colors={"accent": "#ffd400", "panel": "#000000", "text": "#ffffff"},
        radius=12, speed=1.3, fonts={"title": "anton", "text": "montserrat"},
        cta={"position": "bottom-center", "steps": [
            {"icon": "subscribe", "text": "SE INSCREVE AÍ!", "color": None},
            {"icon": "like", "text": "DEIXA O LIKE!", "color": None},
        ]},
        thumbnail={"accent_from": "style"},
    ),
}


class StyleError(ValueError):
    pass


# ── Tokens ────────────────────────────────────────────────────────────────────

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _color(value, fallback: str | None) -> str | None:
    m = _HEX.match(value.strip()) if isinstance(value, str) else None
    return f"#{m.group(1).lower()}" if m else fallback


def _number(value, lo: float, hi: float, fallback: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if x != x else max(lo, min(hi, x))


def _choice(value, options, fallback):
    return value if value in options else fallback


def validate(tokens) -> dict:
    """Complete, safe tokens: the default where something is missing or wrong."""
    t = tokens if isinstance(tokens, dict) else {}
    d = DEFAULT_TOKENS
    colors = t.get("colors") if isinstance(t.get("colors"), dict) else {}
    fonts = t.get("fonts") if isinstance(t.get("fonts"), dict) else {}
    lt = t.get("lower_third") if isinstance(t.get("lower_third"), dict) else {}
    cta = t.get("cta") if isinstance(t.get("cta"), dict) else {}
    thumb = t.get("thumbnail") if isinstance(t.get("thumbnail"), dict) else {}

    steps = []
    for s in cta.get("steps") if isinstance(cta.get("steps"), list) else []:
        if not isinstance(s, dict):
            continue
        text = s.get("text").strip()[:24] if isinstance(s.get("text"), str) else ""
        if not text:
            continue
        steps.append({"icon": _choice(s.get("icon"), ICONS, "subscribe"), "text": text, "color": _color(s.get("color"), None)})
    steps = steps[:3] or copy.deepcopy(d["cta"]["steps"])

    return {
        "layout": _choice(t.get("layout"), LAYOUTS, d["layout"]),
        "colors": {k: _color(colors.get(k), v) for k, v in d["colors"].items()},
        "panel_opacity": _number(t.get("panel_opacity"), 0.3, 1.0, d["panel_opacity"]),
        "radius": round(_number(t.get("radius"), 0, 60, d["radius"])),
        "speed": _number(t.get("speed"), 0.5, 2.0, d["speed"]),
        "fonts": {k: _choice(fonts.get(k), FONTS, v) for k, v in d["fonts"].items()},
        "lower_third": {
            "position": _choice(lt.get("position"), POSITIONS_LT, d["lower_third"]["position"]),
            "avatar": bool(lt.get("avatar", True)),
        },
        "cta": {"position": _choice(cta.get("position"), POSITIONS_CTA, d["cta"]["position"]), "steps": steps},
        "thumbnail": _thumbnail(thumb),
    }


def _thumbnail(thumb: dict) -> dict:
    out = {"accent_from": _choice(thumb.get("accent_from"), ("topic", "style"), DEFAULT_TOKENS["thumbnail"]["accent_from"])}
    if isinstance(thumb.get("html"), str) and thumb["html"].strip():
        try:
            out["html"] = thumb_html.sanitize(thumb["html"])
        except thumb_html.ThumbHtmlError:
            pass  # a broken layout: the default one draws the thumbnail
    return out


def _rgb(hex_color: str) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def thumbnail_accent(tokens: dict, template_accent) -> list[int]:
    """The thumbnail's accent: the topic template's, or the style's own."""
    if tokens["thumbnail"]["accent_from"] == "style" or not template_accent:
        return _rgb(tokens["colors"]["accent"])
    return list(template_accent)


# ── Fonts ─────────────────────────────────────────────────────────────────────

def _font_dirs() -> list[Path]:
    root = overlay_assets.default_repo_root() / "assets"
    return [root / "fonts", root / "thumbnails" / "fonts"]


def font_file(name: str) -> Path | None:
    for d in _font_dirs():
        p = d / name
        if p.is_file():
            return p
    return None


def _font(font_id: str, weight: str) -> Path | None:
    spec = FONTS.get(font_id) or FONTS[DEFAULT_TOKENS["fonts"]["text"]]
    return font_file(spec.get(weight) or spec["bold"]) or font_file(spec["bold"])


def overlay_fonts(tokens: dict) -> dict[str, str]:
    """{"Bold", "Regular"} → files, for the overlays (the style's text font)."""
    fid = tokens["fonts"]["text"]
    out = {"Bold": _font(fid, "bold"), "Regular": _font(fid, "regular")}
    if None in out.values():
        raise StyleError(f"fonte não encontrada: {FONTS.get(fid, {}).get('label', fid)}")
    return {k: str(v) for k, v in out.items()}


def title_font(tokens: dict) -> Path | None:
    return _font(tokens["fonts"]["title"], "bold")


# ── Storage ───────────────────────────────────────────────────────────────────

def user_dir() -> Path:
    return cfg.home_dir() / "styles"


def _user_file(style_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", style_id or ""):
        raise StyleError(f"estilo inválido: {style_id!r}")
    return user_dir() / f"{style_id}.json"


def list_styles() -> list[dict]:
    out = [
        {"id": sid, "name": p["name"], "description": p["description"], "builtin": True, "tokens": validate(p["tokens"])}
        for sid, p in PRESETS.items()
    ]
    d = user_dir()
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if f.stem in PRESETS or not isinstance(data, dict):
            continue
        out.append({
            "id": f.stem, "name": str(data.get("name") or f.stem)[:40], "description": str(data.get("description") or "")[:200],
            "builtin": False, "tokens": validate(data.get("tokens")),
        })
    return out


def get(style_id: str | None) -> dict | None:
    return next((s for s in list_styles() if s["id"] == style_id), None)


def active_id() -> str:
    from auto_edit import settings

    sid = settings.load().get("style") or DEFAULT_ID
    return sid if get(sid) else DEFAULT_ID


def active() -> dict:
    return get(active_id()) or get(DEFAULT_ID)  # type: ignore[return-value]


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "estilo"
    sid, n = base, 2
    while sid in PRESETS or (user_dir() / f"{sid}.json").exists():
        sid, n = f"{base}-{n}", n + 1
    return sid


def save(name: str, tokens, style_id: str | None = None, description: str = "") -> dict:
    """Create (no id, or a preset's id) or update one of the person's styles."""
    name = (name or "").strip()[:40]
    if not name:
        raise StyleError("dê um nome pro estilo")
    if not style_id or style_id in PRESETS:
        style_id = _slug(name)
    path = _user_file(style_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "description": (description or "").strip()[:200], "tokens": validate(tokens)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return get(style_id)  # type: ignore[return-value]


def delete(style_id: str) -> None:
    if style_id in PRESETS:
        raise StyleError("os estilos prontos não podem ser excluídos")
    path = _user_file(style_id)
    if not path.is_file():
        raise StyleError(f"estilo não encontrado: {style_id}")
    path.unlink()
    from auto_edit import settings

    if settings.load().get("style") == style_id:
        settings.save({"style": DEFAULT_ID})


def set_active(style_id: str) -> str:
    if not get(style_id):
        raise StyleError(f"estilo não encontrado: {style_id}")
    from auto_edit import settings

    settings.save({"style": style_id})
    return style_id


FILE_FORMAT = 1
FILE_SUFFIX = ".autoedit-style.json"
NOT_A_STYLE = "arquivo não é um estilo do Auto-Edit"


def export(style_id: str) -> dict:
    """The shareable file of a style: its look only, never the brand."""
    s = get(style_id)
    if not s:
        raise StyleError(f"estilo não encontrado: {style_id}")
    return {"format": FILE_FORMAT, "name": s["name"], "description": s["description"], "tokens": s["tokens"]}


def export_file(style_id: str, folder: Path) -> Path:
    data = export(style_id)
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{style_id}{FILE_SUFFIX}", 2
    while path.exists():
        path, n = folder / f"{style_id}-{n}{FILE_SUFFIX}", n + 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _unique_name(name: str) -> str:
    taken = {s["name"] for s in list_styles()}
    out, n = name, 2
    while out in taken:
        out, n = f"{name[:34]} ({n})", n + 1
    return out


def import_(data) -> dict:
    """Save a shared style as a new one of the person's (never overwrites)."""
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT or not isinstance(data.get("tokens"), dict):
        raise StyleError(NOT_A_STYLE)
    name = str(data.get("name") or "").strip()[:40] or "Estilo importado"
    return save(_unique_name(name), data["tokens"], None, str(data.get("description") or ""))


# ── AI ────────────────────────────────────────────────────────────────────────

AI_TIMEOUT = 120


def _first_json(text: str) -> dict | None:
    dec = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def _stylist_prompt(description: str, colors: list[str]) -> str:
    from auto_edit import render

    base = (overlay_assets.default_repo_root() / "agents" / "stylist.md").read_text(encoding="utf-8")
    name = render.brand().get("name") or "(sem nome ainda)"
    return (
        f"{base}\n\n---\n\n"
        f"# OPÇÕES\nFONTE: {', '.join(FONTS)}\nPOSICAO_LT: {', '.join(POSITIONS_LT)}\n"
        f"POSICAO_CTA: {', '.join(POSITIONS_CTA)}\nICONE: {', '.join(ICONS)}\n\n"
        f"# CANAL\n{name}\n\n"
        f"# PEDIDO\n{description or '(sem descrição: baseie-se nas cores da imagem)'}\n\n"
        + (f"# CORES DA IMAGEM (da mais presente pra menos)\n{', '.join(colors)}\n" if colors else "")
    )


def generate(description: str, image: bytes | None = None, *, complete=None) -> dict:
    """A draft style from a description and/or a reference image (its colors,
    as text). Never saved here; the answer goes through validate()."""
    from auto_edit import agents, palette

    description = (description or "").strip()[:500]
    if not description and not image:
        raise StyleError("descreva o estilo ou mande uma imagem")
    colors: list[str] = []
    if image:
        try:
            colors = palette.extract(image)
        except palette.PaletteError as exc:
            raise StyleError(str(exc)) from exc
    run = complete or (lambda p: agents.complete(p, timeout=AI_TIMEOUT))
    try:
        answer = run(_stylist_prompt(description, colors))
    except agents.AgentError as exc:
        raise StyleError(f"a IA falhou: {exc}") from exc
    data = _first_json(answer)
    tokens = None if data is None else data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    if not tokens or not set(tokens) & set(DEFAULT_TOKENS):
        raise StyleError("a IA não devolveu um estilo")
    name = data.get("name") if isinstance(data.get("name"), str) else ""
    desc = data.get("description") if isinstance(data.get("description"), str) else ""
    return {"name": name.strip()[:40] or "Estilo IA", "description": desc.strip()[:200], "tokens": validate(tokens)}


# ── Preview ───────────────────────────────────────────────────────────────────

PREVIEW_W, PREVIEW_H = 1280, 720
PREVIEW_KINDS = ("thumbnail", "lower_third", "cta")
SAMPLE_TITLE, SAMPLE_SUB = "Editei esse vídeo com IA", "Sem esforço"


def _cache_dir() -> Path:
    return cfg.home_dir() / "cache" / "styles"


def preview_frame() -> Path | None:
    """A frame from the newest edited video in the library (the previews show
    the style on the person's own footage); None → a neutral background."""
    from auto_edit import engine

    try:
        root = engine.library_root()
    except Exception:
        return None
    videos = [p for p in root.glob("*/edited_video.mp4") if p.is_file()] if root.is_dir() else []
    if not videos:
        return None
    src = max(videos, key=lambda p: p.stat().st_mtime)
    key = hashlib.sha1(f"{src}:{src.stat().st_mtime}".encode()).hexdigest()[:16]
    out = _cache_dir() / f"frame-{key}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        duration = 0.0
    res = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, duration * 0.3):.2f}", "-i", str(src),
         "-frames:v", "1", "-vf", f"scale={PREVIEW_W}:{PREVIEW_H}:force_original_aspect_ratio=increase,crop={PREVIEW_W}:{PREVIEW_H}",
         "-q:v", "3", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    return out if res.returncode == 0 and out.is_file() else None


def preview(tokens, kind: str) -> bytes:
    """PNG of one part of a style (cached by everything that changes it)."""
    from auto_edit import render

    if kind not in PREVIEW_KINDS:
        raise StyleError(f"prévia desconhecida: {kind}")
    tokens = validate(tokens)
    cmd = render.command()
    if cmd is None:
        raise StyleError("renderizador (auto-edit-render) não encontrado")
    brand = render.brand()
    if not brand.get("name"):  # show the shape even before the brand is set
        brand = {**brand, "name": "Seu nome", "handle": brand.get("handle") or "@seucanal"}
    frame = preview_frame()

    if kind == "thumbnail":
        font = title_font(tokens)
        if font is None:
            raise StyleError("fonte do título não encontrada")
        spec = {
            "kind": "thumbnail", "thumbnail_kind": "long", "width": PREVIEW_W, "height": PREVIEW_H,
            "main_text": SAMPLE_TITLE, "sub_text": SAMPLE_SUB,
            "accent": thumbnail_accent(tokens, [55, 224, 160]),
            "background": str(frame) if frame else None, "font": str(font),
        }
    else:
        spec = {
            "kind": kind, "width": PREVIEW_W, "height": PREVIEW_H,
            "background": str(frame) if frame else None,
            "style": tokens, "brand": brand, "fonts": overlay_fonts(tokens),
        }

    key = hashlib.sha1(json.dumps(spec, sort_keys=True).encode() + str(_mtime(brand.get("logo"))).encode()).hexdigest()[:20]
    cached = _cache_dir() / f"{kind}-{key}.png"
    if cached.is_file():
        return cached.read_bytes()
    cached.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="auto-edit-style-") as tmp:
        spec_file = Path(tmp) / "spec.json"
        out = Path(tmp) / "out.png"
        spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        try:
            res = subprocess.run([*cmd, "preview", str(spec_file), str(out)],
                                 capture_output=True, text=True, timeout=render.TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StyleError(f"falhou ao desenhar a prévia: {exc}") from exc
        if res.returncode != 0 or not out.is_file():
            raise StyleError(f"falhou ao desenhar a prévia: {(res.stderr or res.stdout).strip()[-300:]}")
        data = out.read_bytes()
    cached.write_bytes(data)
    return data


def _mtime(path) -> float:
    try:
        return Path(path).stat().st_mtime if path else 0
    except OSError:
        return 0
