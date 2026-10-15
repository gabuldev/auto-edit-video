"""The colors of an image (a logo, a reference thumbnail) and a style's
colors from them. Pillow only, no model: an agent never sees the image, it
gets these colors as text, so it works with every agent."""
from __future__ import annotations

import colorsys
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class PaletteError(ValueError):
    pass


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(c) for c in rgb[:3]))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _hsv(rgb) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb[:3]))


def _vivid(rgb) -> bool:
    _, s, v = _hsv(rgb)
    return s >= 0.15 and v >= 0.12


def _open(image: Path | str | bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image)) if isinstance(image, (bytes, bytearray)) else Image.open(image)
        img = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PaletteError("não consegui ler a imagem") from exc
    img.thumbnail((128, 128))
    return img


def extract(image: Path | str | bytes, n: int = 5) -> list[str]:
    """Up to `n` vivid colors, most present first. Transparent, gray,
    near-white and near-black pixels don't count; [] when nothing is left."""
    img = _open(image)
    pixels = getattr(img, "get_flattened_data", img.getdata)()  # getdata: Pillow < 12
    vivid = [p[:3] for p in pixels if p[3] >= 128 and _vivid(p)]
    if not vivid:
        return []
    strip = Image.new("RGB", (len(vivid), 1))
    strip.putdata(vivid)
    q = strip.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    scored = []
    for count, idx in q.getcolors() or []:
        rgb = tuple(pal[idx * 3:idx * 3 + 3])
        scored.append((count / len(vivid) * (0.5 + _hsv(rgb)[1]), rgb))
    out: list[tuple] = []
    for _, rgb in sorted(scored, reverse=True):
        if all(sum(abs(a - b) for a, b in zip(rgb, o)) > 40 for o in out):
            out.append(rgb)
    return [_hex(c) for c in out[:n]]


def _luminance(rgb) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def suggest(colors: list[str]) -> dict | None:
    """A style's colors from a palette: the most saturated as the accent, a
    dark panel of its hue, and the text color that reads best on the panel."""
    if not colors:
        return None
    accent = max(colors, key=lambda c: _hsv(_rgb(c))[1])
    h = _hsv(_rgb(accent))[0]
    panel = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, 0.6, 0.12))
    text = max(("#ffffff", "#111111"), key=lambda t: _contrast(_rgb(t), panel))
    return {"accent": accent, "panel": _hex(panel), "text": text}
