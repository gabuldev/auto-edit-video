"""Caption tokens: the look of the burned-in short captions.

Lives in the style (`tokens.captions`); a video may adjust only
ADJUST_KEYS on top of it (pipeline `caption_style`).
"""
from __future__ import annotations

import copy
import re

POSITIONS = ("top", "middle", "bottom")
HIGHLIGHT_MODES = ("outline", "fill", "box")
BACKGROUNDS = ("none", "box")
ADJUST_KEYS = ("position", "offset", "size", "hidden")

# Today's look (offset = % of the video height, size = % of the base size).
DEFAULT: dict = {
    "position": "bottom",
    "offset": 33,
    "size": 100,
    "font": "montserrat",
    "color": "#ffffff",
    "highlight": "#ff4500",
    "highlight_mode": "outline",
    "outline": 1.5,
    "background": "none",
    "words": 4,
    "uppercase": True,
    "hidden": False,
}

_ASS = re.compile(r"^&H([0-9a-fA-F]{2})?([0-9a-fA-F]{6})&?$")


def validate(raw) -> dict:
    """Complete, safe tokens: the default where something is missing or wrong."""
    from auto_edit import styles  # lazy: styles imports this module

    t = raw if isinstance(raw, dict) else {}
    d = DEFAULT
    return {
        "position": styles._choice(t.get("position"), POSITIONS, d["position"]),
        "offset": styles._number(t.get("offset"), 0, 40, d["offset"]),
        "size": styles._number(t.get("size"), 50, 200, d["size"]),
        "font": styles._choice(t.get("font"), styles.FONTS, d["font"]),
        "color": styles._color(t.get("color"), d["color"]),
        "highlight": styles._color(t.get("highlight"), d["highlight"]),
        "highlight_mode": styles._choice(t.get("highlight_mode"), HIGHLIGHT_MODES, d["highlight_mode"]),
        "outline": styles._number(t.get("outline"), 0, 6, d["outline"]),
        "background": styles._choice(t.get("background"), BACKGROUNDS, d["background"]),
        "words": round(styles._number(t.get("words"), 1, 4, d["words"])),
        "uppercase": t["uppercase"] if isinstance(t.get("uppercase"), bool) else d["uppercase"],
        "hidden": t["hidden"] if isinstance(t.get("hidden"), bool) else d["hidden"],
    }


def _from_ass(value) -> str | None:
    m = _ASS.match(value.strip()) if isinstance(value, str) else None
    if not m:
        return None
    bb, gg, rr = m.group(2)[0:2], m.group(2)[2:4], m.group(2)[4:6]
    return f"#{rr}{gg}{bb}".lower()


def ass_color(hex_color: str) -> str:
    """'#ff4500' → '&H0045FF&' (ASS is BGR)."""
    h = hex_color.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _num(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def from_legacy(caption_style) -> dict:
    """Translate the old CLI `caption_style` (ASS units at 384x288) to tokens."""
    from auto_edit import styles

    cs = caption_style if isinstance(caption_style, dict) else {}
    out: dict = {}
    for src, dst in (("color_highlight", "highlight"), ("color_text", "color")):
        c = _from_ass(cs.get(src))
        if c:
            out[dst] = c
    border, border_hl = _num(cs.get("border_normal")), _num(cs.get("border_highlight"))
    if border is not None:
        out["outline"] = round(border, 2)
    elif border_hl is not None:
        out["outline"] = round(border_hl * 0.6, 2)
    size = _num(cs.get("font_size"))
    if size is not None:
        out["size"] = round(size / 14 * 100, 1)
    margin = _num(cs.get("margin_v"))
    if margin is not None:
        out["position"] = "bottom"
        out["offset"] = round(margin / 288 * 100, 1)
    name = cs.get("font_name")
    if isinstance(name, str):
        for fid, spec in styles.FONTS.items():
            if spec["label"].lower() == name.strip().lower():
                out["font"] = fid
                break
    return out


def resolve(pipeline: dict) -> dict:
    """Saved style tokens, then the old CLI options, then the per-video adjust."""
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    cs = pipeline.get("caption_style")
    cs = cs if isinstance(cs, dict) else {}
    merged = {**validate(pipeline.get("captions")), **from_legacy(cs), **{k: cs[k] for k in ADJUST_KEYS if k in cs}}
    return validate(merged)


def default() -> dict:
    return copy.deepcopy(DEFAULT)
