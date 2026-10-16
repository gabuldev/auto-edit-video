"""A style's thumbnail layout: HTML + inline CSS (written by the AI), made
safe before it is saved — only layout tags, no scripts, nothing external.

The renderer (renderer/src/html.ts) fills the placeholders: {{titulo}},
{{etiqueta}}, images like <img src="{{frame}}">, colors like {{destaque}}.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

TAGS = {"div", "span", "p", "img"}
# Dropped with everything inside them.
DROP = {"script", "style", "iframe", "object", "svg", "head", "title", "template", "noscript", "textarea", "select"}
VOID = {"img", "br", "hr", "link", "meta", "input", "source", "embed", "base"}
ATTRS = {"style", "src", "data-fit"}
IMAGE_SLOTS = ("frame", "frame2", "rosto", "logo")
TEXT_SLOTS = ("titulo", "titulo_inicio", "titulo_fim", "etiqueta")
COLOR_SLOTS = ("destaque", "cor.accent", "cor.panel", "cor.text")
MAX_CHARS = 20000
_SLOT = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")
_IMAGE_SRC = re.compile(r"\{\{\s*(%s)\s*\}\}" % "|".join(IMAGE_SLOTS))


class ThumbHtmlError(ValueError):
    pass


def _clean_style(css: str) -> str:
    keep = []
    for d in css.split(";"):
        d = d.strip()
        low = d.lower()
        if d and ":" in d and "url(" not in low and "expression" not in low and "@import" not in low:
            keep.append(d)
    return ";".join(keep)


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0  # depth inside a dropped element
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
            if k == "src":
                if tag != "img":
                    continue
                if not _IMAGE_SRC.fullmatch(v.strip()):
                    return  # an image from anywhere else: drop the element
                v = v.strip()
            if k == "style":
                v = _clean_style(v)
            kept.append(f'{k}="{_html.escape(v, quote=True)}"')
        attr = (" " + " ".join(kept)) if kept else ""
        if tag == "img":
            if any(a.startswith("src=") for a in kept):
                self.out.append(f"<img{attr}/>")
            return
        self.out.append(f"<{tag}{attr}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in TAGS or tag in VOID:
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
    """Safe layout HTML, or ThumbHtmlError when nothing usable is left."""
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
