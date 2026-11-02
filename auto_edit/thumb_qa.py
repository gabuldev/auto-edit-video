"""
Thumbnail QA — pure, dependency-light checks run after a thumbnail is produced.

Addresses the recurring problems with the generated thumbnails (see the
"Thumbnails A/B" task): text over the face, text too long / too technical, and
illegibility at feed size on a phone. Everything here is pure (Pillow + numpy
only, both already core deps) and unit-tested; the pipeline wiring in
``tools/thumbnailer.py`` calls :func:`run` and never fails the stage on a QA
problem — it writes a report and a feed-size preview for the creator to eyeball.

What each check needs:
- text rules (:func:`check_main_text`): just the string — always runs.
- feed preview (:func:`save_mobile_preview`): the output PNG — always runs.
- overlap (:func:`overlap_fraction`), contrast (:func:`contrast_ratio`),
  cap-height (:func:`cap_height_px`) and "fits without shrinking": the text
  box / colors / face box / line fit, which
  only the layout that drew the text knows. The Pillow path hands them in; the
  React renderer does not, so those checks are skipped there and the report
  comes back ``"parcial"`` (not ``"aprovada"``) whenever a check is skipped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

# ── Text rules (task item 5) ─────────────────────────────────────────────────

MAX_WORDS = 4
MAX_TECH_TERMS = 1

# Tokens that read as jargon on a thumbnail — they belong in the TITLE (which
# feeds YouTube search), not in the hero text. The heuristic is deliberately
# conservative: a warning, not a hard gate.
_TECH_VOCAB = {
    "esp32", "esp8266", "arduino", "raspberry", "firmware", "pcb", "gpio",
    "nfc", "rfid", "api", "sdk", "adk", "pdv", "bmcu", "ams", "sql", "css",
    "html", "json", "llm", "rag", "mcu", "i2c", "spi", "uart", "pwm", "oled",
    "mediapipe", "pytorch", "tensorflow", "kubernetes", "docker", "webhook",
}

# Looks like a spec code (letters + digits) but reads as plain language on a
# thumbnail — must NOT burn the technical-term quota.
_NOT_TECH = (
    re.compile(r"^\d+d$"),         # 3D, 4D, 2D — a dimension, not a part number
    re.compile(r"^r\$[\d.,]+$"),   # R$5, R$1.500 — a price, not a spec
)

_VERSUS = {"x", "vs", "versus"}
_PUNCT = ".,!?:;—-\"'“”…"


def _norm(token: str) -> str:
    """Token stripped of surrounding punctuation, lowercased."""
    return token.strip(_PUNCT).lower()


def word_count(text: str) -> int:
    """Words in the text, ignoring punctuation-only tokens (a lone ``—``)."""
    return sum(1 for tok in (text or "").split() if _norm(tok))


def is_technical(token: str) -> bool:
    """Whether one token reads as a technical term on a thumbnail.

    Deliberately NOT keyed on ALL-CAPS: thumbnail hero text is conventionally
    uppercase, so every word would look like an acronym. Two signals only:
    a known-jargon vocabulary, and model/spec codes (letters glued to digits).
    Everyday letter+digit tokens (``3D``, ``R$5``) are excluded — they read as
    plain language, not jargon.
    """
    raw = token.strip(_PUNCT)
    low = raw.lower()
    if not raw:
        return False
    if any(p.match(low) for p in _NOT_TECH):
        return False
    if low in _TECH_VOCAB:
        return True
    # model/spec codes: letters + digits glued together (ESP32, M4, GPT-4, RTX3060)
    return bool(re.search(r"[A-Za-z]", raw) and re.search(r"\d", raw))


def technical_terms(text: str) -> list[str]:
    """Distinct technical-looking tokens in the text, in order of appearance."""
    seen: list[str] = []
    seen_keys: set[str] = set()
    for tok in (text or "").split():
        if is_technical(tok):
            key = _norm(tok)
            if key not in seen_keys:
                seen_keys.add(key)
                seen.append(tok)
    return seen


def _has_versus(text: str) -> bool:
    """A standalone ``X`` / ``VS`` / ``VERSUS`` sitting between two words."""
    toks = [_norm(t) for t in (text or "").split()]
    for i, tok in enumerate(toks):
        if tok in _VERSUS and 0 < i < len(toks) - 1 and toks[i - 1] and toks[i + 1]:
            return True
    return False


def check_main_text(text: str, max_words: int = MAX_WORDS,
                    max_tech: int = MAX_TECH_TERMS) -> dict:
    """Validate hero text: at most ``max_words`` words and ``max_tech`` jargon terms."""
    wc = word_count(text)
    tech = technical_terms(text)
    reasons: list[str] = []
    if wc > max_words:
        reasons.append(f"main_text com {wc} palavras (máx {max_words})")
    if len(tech) > max_tech:
        reasons.append(
            f"{len(tech)} termos técnicos {tech} (máx {max_tech}; o resto vai pro título)"
        )
    # A versus construction ("A X B", "A VS B") with any spec term reads as a
    # technical comparison — it belongs in the title, not the hero text.
    if _has_versus(text) and tech:
        reasons.append("comparação técnica (X/VS) — melhor no título")
    return {"ok": not reasons, "word_count": wc, "technical_terms": tech, "reasons": reasons}


# ── WCAG contrast (task item 6) ──────────────────────────────────────────────

MIN_CONTRAST = 4.5  # WCAG AA for normal text


def _linearize(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB colour (0-255 per channel)."""
    r, g, b = (_linearize(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours (1.0 … 21.0)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ── Geometry: text / face overlap (task item 2) ──────────────────────────────

Box = tuple[int, int, int, int]  # (x0, y0, x1, y1)


def _area(box: Box) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersection(a: Box, b: Box) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return _area((x0, y0, x1, y1))


def overlap_fraction(a: Box, b: Box) -> float:
    """Fraction of box ``a`` covered by box ``b`` (0 … 1)."""
    aa = _area(a)
    return _intersection(a, b) / aa if aa else 0.0


def iou(a: Box, b: Box) -> float:
    inter = _intersection(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union else 0.0


# ── Mobile legibility (task item 6) ──────────────────────────────────────────

MOBILE_SIZE = (168, 94)  # how a long thumbnail shows in the YouTube feed
MIN_TEXT_PX = 12.0       # hero text smaller than this at feed size is unreadable
MAX_FACE_OVERLAP = 0.05  # hero text may cover at most this fraction of the face


def cap_height_px(text_box: Box, full_height: int,
                  preview_height: int = MOBILE_SIZE[1], lines: int = 1) -> float:
    """Height of a single line of hero text once shrunk to feed size.

    ``text_box`` is the whole hero block; dividing by ``lines`` recovers the
    per-line height, which is what actually has to stay legible (a two-line
    block twice as tall is not twice as readable)."""
    if full_height <= 0 or lines <= 0:
        return 0.0
    block = (text_box[3] - text_box[1]) * preview_height / full_height
    return block / lines


def _preview_size(width: int, height: int) -> tuple[int, int]:
    """Feed-size preview, keeping orientation: 168×94 landscape, 94×168 portrait."""
    return MOBILE_SIZE if width >= height else (MOBILE_SIZE[1], MOBILE_SIZE[0])


def save_mobile_preview(src_png: Path, dst_png: Path,
                        size: tuple[int, int] | None = None) -> Path:
    """Write a feed-size preview of the thumbnail for a quick phone-legibility look.

    When ``size`` is None the preview keeps the source orientation, so a
    vertical short (1080×1920) is not squashed into a landscape box."""
    with Image.open(src_png) as im:
        target = size or _preview_size(im.width, im.height)
        im.convert("RGB").resize(target, Image.LANCZOS).save(dst_png, "PNG")
    return dst_png


# ── Aggregate report ─────────────────────────────────────────────────────────


def evaluate(
    main_text: str,
    *,
    text_box: Box | None = None,
    face_box: Box | None = None,
    text_rgb: tuple[int, int, int] | None = None,
    bg_rgb: tuple[int, int, int] | None = None,
    full_height: int | None = None,
    text_lines: int = 1,
    text_fits: bool | None = None,
) -> dict:
    """Aggregate every check that has enough information into one report.

    A check that lacks its inputs is reported as ``null`` (skipped). ``approved``
    is False when a check that RAN failed, True when every check ran and passed,
    and None (``"parcial"``) when nothing failed but some check was skipped.
    """
    checks: dict[str, dict | None] = {}
    checks["text_rules"] = check_main_text(main_text)

    if text_box is not None and face_box is not None:
        # Fraction of the FACE the text covers — a big text box fully over a
        # small face must fail, which measuring the text's own coverage misses.
        frac = overlap_fraction(face_box, text_box)
        ok = frac < MAX_FACE_OVERLAP
        checks["text_not_over_face"] = {
            "ok": ok,
            "face_covered_fraction": round(frac, 3),
            "reasons": [] if ok else [f"texto cobre {frac:.0%} do rosto (máx {MAX_FACE_OVERLAP:.0%})"],
        }
    else:
        checks["text_not_over_face"] = None

    if text_rgb is not None and bg_rgb is not None:
        ratio = contrast_ratio(text_rgb, bg_rgb)
        ok = ratio >= MIN_CONTRAST
        checks["contrast"] = {
            "ok": ok,
            "ratio": round(ratio, 2),
            "reasons": [] if ok else [f"contraste {ratio:.1f}:1 (< {MIN_CONTRAST}:1)"],
        }
    else:
        checks["contrast"] = None

    if text_box is not None and full_height:
        px = cap_height_px(text_box, full_height, lines=max(1, text_lines))
        ok = px >= MIN_TEXT_PX
        checks["mobile_text_height"] = {
            "ok": ok,
            "px_at_feed": round(px, 1),
            "reasons": [] if ok else [f"texto com {px:.0f}px no feed (< {MIN_TEXT_PX:.0f}px)"],
        }
    else:
        checks["mobile_text_height"] = None

    # The font is never shrunk to make the hero text fit (tools/thumbnailer.py):
    # a text that still overflows its lines at the fixed size is a failure, not
    # something to paper over with a smaller font.
    if text_fits is not None:
        checks["fits_without_shrinking"] = {
            "ok": bool(text_fits),
            "reasons": [] if text_fits else ["texto não cabe no tamanho fixo — encurte, não encolha"],
        }
    else:
        checks["fits_without_shrinking"] = None

    ran = [c for c in checks.values() if c is not None]
    skipped = any(c is None for c in checks.values())
    if any(not c["ok"] for c in ran):
        approved: bool | None = False
    elif skipped:
        approved = None  # nothing failed, but we could not check everything → parcial
    else:
        approved = True
    reasons = [r for c in ran for r in c.get("reasons", [])]
    return {"approved": approved, "checks": checks, "reasons": reasons}


def run(workspace: Path, thumb_path: Path, main_text: str, *,
        rewrite: dict | None = None, name: str = "thumbnail", **boxes) -> dict:
    """Pipeline entry: evaluate, write a feed-size preview + thumbnail_qa.json.

    ``name`` prefixes the files: thumbnail_168.png / thumbnail_qa.json for the
    main thumbnail, thumbnail_b_168.png / thumbnail_b_qa.json for a variation.

    ``rewrite`` is what the thumbnailer changed before drawing (the original
    hero text, the shorter one, and why), so the report shows both. Never
    raises on a bad check; only writing the report itself can fail."""
    report: dict = {"thumbnail": thumb_path.name}
    if rewrite:
        report["main_text_rewrite"] = rewrite
    try:
        report.update(evaluate(main_text, **boxes))
    except (TypeError, ValueError, KeyError) as exc:  # malformed hints must never break the stage
        report.update({"approved": None, "error": f"{type(exc).__name__}: {exc}"})
    try:
        preview = save_mobile_preview(thumb_path, workspace / f"{name}_168.png")
        report["mobile_preview"] = preview.name
    except (OSError, ValueError) as exc:  # missing/unreadable PNG (PIL raises OSError): not fatal either
        report["mobile_preview_error"] = f"{type(exc).__name__}: {exc}"
    (workspace / f"{name}_qa.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    status = {True: "aprovada", False: "REPROVADA", None: "parcial"}.get(report.get("approved"))
    label = "" if name == "thumbnail" else f" ({name})"
    print(f"[thumbnailer] QA{label}: {status}" + (f" — {'; '.join(report['reasons'])}" if report.get("reasons") else ""))
    return report
