"""The thumbnail's B and C variations for YouTube's "Testar e comparar" (Test &
Compare), and how they are recorded.

A is the thumbnail exactly as the thumbnailer always made it (thumbnail.png).
B and C are drawn by tools/thumbnailer.py with the layouts below (HTML + inline
CSS, the format auto_edit/thumb_html.py documents and renderer/src/html.ts
draws), in the active style's title font and colors:

- B — the person cut out of the video on the left ({{rosto_contorno}}), the
  text on the right, over the main frame: the mirror of the usual face-right
  layout of A, so the test really compares two compositions.
- C — the object: the second frame ({{frame2}}, in a maker video the one that
  shows the printer / AMS / part) big, a smaller face (the frame picked for
  its expression), the text on top.

The titles use ``data-fit`` with ``min`` at the thumbnailer's fixed hero size
(128px = HERO_SIZE_FRAC of 1280): the text may grow, never shrink below it —
the renderer reports a text that doesn't fit and the QA fails that variation.

The YouTube API has no Test & Compare endpoint: the thumbnailer registers the
three in metadata.json (``thumbnail_variants``) and the delivered .txt lists
the files to upload in the Studio.
"""
from __future__ import annotations

from pathlib import Path

IDS = ("A", "B", "C")
LABELS = {
    "A": "atual (estilo ativo)",
    "B": "rosto à esquerda, texto à direita",
    "C": "objeto em destaque, rosto menor",
}
HERO_MIN = 128  # px on a 1280-wide thumbnail: tools/thumbnailer.py HERO_SIZE_FRAC

_FRAME = '<img src="{{frame}}" style="position:absolute;left:0;top:0;width:1280px;height:720px;object-fit:cover"/>'
_TITLE = ("text-transform:uppercase;color:#fff;line-height:1.02;"
          "-webkit-text-stroke:6px #000;text-shadow:6px 6px 0 #000")
_TAG = ('<div style="display:flex;margin-top:18px;padding:6px 22px 8px 22px;border-radius:12px;'
        'background-color:{{destaque}};font-size:44px;line-height:1.1;color:#000;text-transform:uppercase">'
        "{{etiqueta}}</div>")

LAYOUT_B = (
    '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
    + _FRAME
    + '<div style="position:absolute;left:0;top:0;width:1280px;height:720px;'
      'background-image:linear-gradient(270deg,rgba(0,0,0,0.92) 0%,rgba(0,0,0,0.8) 45%,rgba(0,0,0,0.15) 75%,rgba(0,0,0,0) 100%)"></div>'
    + '<img src="{{rosto_contorno}}" style="position:absolute;left:0;bottom:0;width:620px;height:700px;'
      'object-fit:contain;object-position:bottom"/>'
    + '<div style="position:absolute;right:48px;top:0;width:704px;height:720px;display:flex;'
      'flex-direction:column;justify-content:center;align-items:flex-end">'
    + f'<div data-fit="linhas:2;min:{HERO_MIN};max:160" style="width:704px;max-height:340px;display:flex;'
      f'justify-content:flex-end;text-align:right;font-size:160px;{_TITLE}">'
      "{{titulo}}</div>"
    + _TAG
    + "</div>"
    + '<div style="position:absolute;right:0;top:0;width:14px;height:720px;background-color:{{destaque}}"></div>'
    + "</div>"
)

LAYOUT_C = (
    '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
    + '<img src="{{frame2}}" style="position:absolute;left:0;top:0;width:1280px;height:720px;object-fit:cover"/>'
    + '<div style="position:absolute;left:0;top:0;width:1280px;height:720px;'
      'background-image:linear-gradient(180deg,rgba(0,0,0,0.88) 0%,rgba(0,0,0,0.55) 38%,rgba(0,0,0,0) 62%)"></div>'
    + '<div style="position:absolute;right:28px;bottom:0;width:360px;height:400px;display:flex;'
      'align-items:flex-end;justify-content:center">'
    + '<img src="{{rosto_contorno}}" style="width:360px;height:400px;object-fit:contain;object-position:bottom"/>'
    + "</div>"
    + '<div style="position:absolute;left:48px;top:30px;width:900px;display:flex;flex-direction:column;align-items:flex-start">'
    + f'<div data-fit="linhas:2;min:{HERO_MIN};max:150" style="width:900px;max-height:310px;font-size:150px;{_TITLE}">'
      "{{titulo}}</div>"
    + _TAG
    + "</div>"
    + '<div style="position:absolute;left:0;bottom:0;width:1280px;height:14px;background-color:{{destaque}}"></div>'
    + "</div>"
)

LAYOUTS = {"B": LAYOUT_B, "C": LAYOUT_C}


def file_name(variant: str) -> str:
    """thumbnail.png for A (unchanged), thumbnail_b.png / thumbnail_c.png."""
    return "thumbnail.png" if variant == "A" else f"thumbnail_{variant.lower()}.png"


def qa_stem(variant: str) -> str:
    """Prefix of the QA files: thumbnail_qa.json for A (as before), thumbnail_b_qa.json…"""
    return Path(file_name(variant)).stem


def qa_status(approved) -> str:
    return {True: "aprovada", False: "reprovada"}.get(approved, "parcial")


def entry(variant: str, report: dict | None = None, *, skipped: str | None = None) -> dict:
    """One item of metadata.json's ``thumbnail_variants``."""
    item: dict = {"id": variant, "layout": LABELS[variant]}
    if skipped:
        item["skipped"] = skipped
        return item
    item["file"] = file_name(variant)
    report = report or {}
    item["qa"] = qa_status(report.get("approved"))
    if report.get("reasons"):
        item["qa_reasons"] = list(report["reasons"])
    return item


def generated(metadata: dict) -> list[dict]:
    """The variations that exist (have a file), in A/B/C order."""
    items = metadata.get("thumbnail_variants")
    if not isinstance(items, list):
        return []
    return [v for v in items if isinstance(v, dict) and v.get("file") and v.get("id") in IDS]


def delivered_name(video_name: str, variant: str) -> str:
    """Name in the output folder: <video>_thumbnail.png, <video>_thumbnail_b.png…"""
    return f"{video_name}_{file_name(variant)}"


def txt_lines(metadata: dict, video_name: str) -> list[str]:
    """The delivered .txt section listing the files for Testar e comparar
    (only when there is something to compare: two or more)."""
    items = generated(metadata)
    if len(items) < 2:
        return []
    lines = ["", "THUMBNAILS (Testar e comparar no Studio — suba todas):"]
    for v in items:
        line = f"- {v['id']}: {delivered_name(video_name, v['id'])} — {v.get('layout', '')} (QA {v.get('qa', 'parcial')})"
        lines.append(line)
    return lines
