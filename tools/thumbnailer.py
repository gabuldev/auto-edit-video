"""
THUMBNAILER stage — generates a thumbnail image for the final video.

Short: extracts best frame (energy peak) + overlays bold text via Pillow.
Long:  generates AI background via Gemini Imagen + composites face asset + styled title.

Output: workspace/thumbnail.png

Usage: python tools/thumbnailer.py <workspace_dir>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont

# ── Dimensions ──────────────────────────────────────────────────────────────

SHORT_SIZE = (1080, 1920)   # 9:16 portrait
LONG_SIZE = (1280, 720)     # 16:9 landscape

ENERGY_RESOLUTION = 0.5     # must match extract.py

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

# ── Style mapping ───────────────────────────────────────────────────────────

STYLE_MAP = {
    "bold-energy": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "accent": (255, 220, 0),
        "tint": (255, 50, 0, 80),
        "gradient": ((200, 30, 0), (255, 100, 0)),
    },
    "clean-minimal": {
        "text": (255, 255, 255),
        "outline": (40, 40, 40),
        "accent": (0, 255, 140),
        "tint": (0, 0, 0, 60),
        "gradient": ((30, 30, 50), (60, 60, 80)),
    },
    "dramatic": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "accent": (255, 50, 50),
        "tint": (0, 0, 0, 120),
        "gradient": ((10, 10, 30), (40, 20, 60)),
    },
    "fun-colorful": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "accent": (255, 150, 0),
        "tint": (255, 200, 0, 80),
        "gradient": ((255, 100, 50), (255, 200, 0)),
    },
}

DEFAULT_STYLE = "clean-minimal"

# ── Template registry ───────────────────────────────────────────────────────

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

# ── Asset helpers ───────────────────────────────────────────────────────────


def _repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


PREFERRED_FONTS = [
    "Montserrat",         # Modern geometric bold
    "ProtestGuerrilla",   # Bold display (CapCut style)
    "BebasNeue",          # Tall condensed display
    "Anton",              # Heavy impact
    "Oswald",             # Clean condensed
]


def _find_font() -> Path | None:
    """Find a bold TTF font in assets/thumbnails/fonts/, preferring display fonts."""
    dirs = []
    env = os.environ.get("AUTO_EDIT_ASSETS_FONTS")
    if env:
        dirs.append(Path(env))
    dirs.append(_repo_root() / "assets" / "thumbnails" / "fonts")

    all_fonts: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        all_fonts.extend(d.glob("*.ttf"))
        all_fonts.extend(d.glob("*.otf"))

    if not all_fonts:
        return None

    # Try preferred fonts first
    for pref in PREFERRED_FONTS:
        for f in all_fonts:
            if pref.lower() in f.stem.lower():
                return f

    return sorted(all_fonts)[0]


def _find_logo_assets(names: list[str] | None = None) -> list[Path]:
    """Find logo PNGs in assets/thumbnails/logos/. If names given, return only matching."""
    dirs = []
    env = os.environ.get("AUTO_EDIT_ASSETS_LOGOS")
    if env:
        dirs.append(Path(env))
    dirs.append(_repo_root() / "assets" / "thumbnails" / "logos")

    all_logos: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        all_logos.extend(sorted(d.glob("*.png")))

    if not all_logos:
        return []

    if not names:
        return []

    matched = []
    for name in names:
        for logo in all_logos:
            if name.lower() in logo.stem.lower():
                matched.append(logo)
                break
    return matched


def _composite_logos(
    img: Image.Image, logo_paths: list[Path], position: str = "top-left",
) -> Image.Image:
    """Composite logo icons onto the thumbnail."""
    if not logo_paths:
        return img

    img = img.convert("RGBA")
    w, h = img.size
    logo_size = int(h * 0.08)
    padding = int(logo_size * 0.4)
    margin = int(w * 0.03)

    logos = []
    for lp in logo_paths:
        logo = Image.open(lp).convert("RGBA")
        ratio = logo.width / logo.height
        lw = int(logo_size * ratio)
        logo = logo.resize((lw, logo_size), Image.LANCZOS)
        logos.append(logo)

    total_w = sum(lg.width for lg in logos) + padding * (len(logos) - 1)

    if "right" in position:
        x = w - margin - total_w
    else:
        x = margin

    if "bottom" in position:
        y = h - margin - logo_size
    else:
        y = margin

    for logo in logos:
        img.paste(logo, (x, y), logo)
        x += logo.width + padding

    print(f"[thumbnailer] {len(logos)} logo(s) composited")
    return img


def _find_face_asset() -> Path | None:
    """Find a face PNG in assets/thumbnails/faces/."""
    dirs = []
    env = os.environ.get("AUTO_EDIT_ASSETS_FACES")
    if env:
        dirs.append(Path(env))
    dirs.append(_repo_root() / "assets" / "thumbnails" / "faces")

    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.png")):
            return f
    return None


# ── Frame extraction & scoring ─────────────────────────────────────────────

NUM_CANDIDATES = 12


def _find_energy_peak(transcription: dict) -> float:
    """Return timestamp (seconds) of the energy peak in the transcription."""
    energy_db = transcription.get("energy_db", [])
    if not energy_db:
        duration = transcription.get("duration", 10.0)
        return duration * 0.25

    peak_idx = max(range(len(energy_db)), key=lambda i: energy_db[i])
    return peak_idx * ENERGY_RESOLUTION


def _extract_frame(video_path: str, timestamp: float, output: Path) -> Path:
    """Extract a single frame from the video at the given timestamp."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.2f}",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output


def _score_sharpness(gray: np.ndarray) -> float:
    """Laplacian variance — higher = sharper image."""
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    h, w = gray.shape
    pad = np.pad(gray, 1, mode="edge")
    lap = np.zeros_like(gray, dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            lap += pad[dy:dy + h, dx:dx + w] * kernel[dy, dx]
    return float(np.var(lap))


def _score_face_region(rgb: np.ndarray) -> float:
    """Skin-tone ratio in the upper-center region where faces typically are.

    High ratio = face likely visible. Low ratio = face blocked or absent.
    """
    h, w = rgb.shape[:2]
    # Upper-center crop (face zone in selfie/vlog framing)
    y0, y1 = int(h * 0.15), int(h * 0.65)
    x0, x1 = int(w * 0.20), int(w * 0.80)
    roi = rgb[y0:y1, x0:x1].astype(np.float32)

    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    # Skin-tone heuristic (works across skin tones)
    skin = (
        (r > 60) & (g > 40) & (b > 20)
        & (r > g) & (r > b)
        & ((r - g) > 10)
        & (np.abs(r - g) < 120)
        & (r < 240) & (g < 230) & (b < 220)
    )
    return float(skin.sum()) / max(roi.shape[0] * roi.shape[1], 1)


def _score_center_clarity(gray: np.ndarray) -> float:
    """Variance in center region — low = uniform object blocking the view."""
    h, w = gray.shape
    y0, y1 = int(h * 0.25), int(h * 0.75)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    center = gray[y0:y1, x0:x1]
    return float(np.std(center))


def _score_brightness(gray: np.ndarray) -> float:
    """Penalize too dark or too bright — optimal around 100-160."""
    mean = float(np.mean(gray))
    optimal = 130.0
    return max(0.0, 1.0 - abs(mean - optimal) / optimal)


def _score_frame(img: Image.Image) -> dict:
    """Score a frame across multiple quality dimensions."""
    small = img.resize((320, int(320 * img.height / img.width)), Image.LANCZOS)
    rgb = np.array(small)
    gray = np.mean(rgb, axis=2).astype(np.float32)

    sharpness = _score_sharpness(gray)
    face = _score_face_region(rgb)
    clarity = _score_center_clarity(gray)
    brightness = _score_brightness(gray)

    return {
        "sharpness": sharpness,
        "face": face,
        "clarity": clarity,
        "brightness": brightness,
    }


def _pick_best_frame(
    video_path: str, duration: float, workspace: Path,
    energy_peak: float | None = None,
) -> Path:
    """Extract multiple candidate frames, score them, and return the best one."""
    # Generate candidate timestamps: regular intervals + energy peak
    margin = max(1.0, duration * 0.05)
    usable = duration - 2 * margin
    step = usable / max(NUM_CANDIDATES - 1, 1)
    timestamps = [margin + i * step for i in range(NUM_CANDIDATES)]

    if energy_peak is not None and margin < energy_peak < duration - margin:
        timestamps.append(energy_peak)

    candidates: list[tuple[float, float, Path]] = []
    for i, ts in enumerate(timestamps):
        path = workspace / f"_thumb_cand_{i}.jpg"
        try:
            _extract_frame(video_path, ts, path)
        except Exception:
            continue
        img = Image.open(path)
        scores = _score_frame(img)

        # Weighted combination (face visibility is most important for thumbnails)
        combined = (
            scores["face"] * 50.0
            + scores["sharpness"] / 500.0
            + scores["clarity"] / 10.0
            + scores["brightness"] * 5.0
        )
        candidates.append((combined, ts, path))

    if not candidates:
        fallback = workspace / "_thumb_cand_fallback.jpg"
        _extract_frame(video_path, duration * 0.25, fallback)
        return fallback

    candidates.sort(key=lambda c: c[0], reverse=True)
    best_score, best_ts, best_path = candidates[0]
    print(f"[thumbnailer] Best frame at {best_ts:.1f}s (score={best_score:.1f})")

    # Cleanup losers
    for _, _, path in candidates[1:]:
        path.unlink(missing_ok=True)

    return best_path


def _crop_center(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop image to target dimensions."""
    target_ratio = target_w / target_h
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        # Image is wider — fit by height, crop width
        new_h = target_h
        new_w = int(img_ratio * target_h)
    else:
        # Image is taller — fit by width, crop height
        new_w = target_w
        new_h = int(target_w / img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


# ── Background generators ──────────────────────────────────────────────────


def _stylize_frame_bg(img: Image.Image) -> Image.Image:
    """Turn a raw video frame into a styled thumbnail background.

    Center stays sharp (subject/face), edges get blur + darkening.
    """
    w, h = img.size
    img = img.convert("RGB")

    # 1. Create blurred version for edges
    blurred = img.filter(ImageFilter.GaussianBlur(radius=12))

    # 2. Radial mask: center = sharp (white), edges = blurred (black)
    sw, sh = 128, 128
    y_arr, x_arr = np.mgrid[0:sh, 0:sw]
    cx, cy = sw / 2, sh * 0.55  # slightly below center (faces are usually there)
    # Elliptical: wider horizontally to cover shoulders
    dist = np.sqrt(((x_arr - cx) / (sw * 0.35)) ** 2 + ((y_arr - cy) / (sh * 0.30)) ** 2)
    # Smooth falloff: 0 = sharp center, 1 = fully blurred edge
    blend = np.clip(dist - 0.3, 0, 1)
    blend = (blend / blend.max() * 255).astype(np.uint8)
    blur_mask = Image.fromarray(blend, mode="L").resize((w, h), Image.LANCZOS)

    # 3. Composite: sharp center + blurred edges
    img = Image.composite(blurred, img, blur_mask)

    # 4. Boost saturation
    img = ImageEnhance.Color(img).enhance(1.4)

    # 5. Vignette — darken edges only, center untouched
    dist_vig = np.sqrt((x_arr - sw / 2) ** 2 + (y_arr - sh / 2) ** 2) / np.sqrt((sw / 2) ** 2 + (sh / 2) ** 2)
    alpha = np.clip(160 * dist_vig ** 2.2, 0, 255).astype(np.uint8)
    mask = Image.fromarray(alpha, mode="L").resize((w, h), Image.LANCZOS)
    black = Image.new("RGB", (w, h), (0, 0, 0))
    img = Image.composite(black, img, mask)
    return img


def _generate_gradient_bg(width: int, height: int, style_hint: str) -> Image.Image:
    """Generate a vertical gradient background as fallback."""
    style = STYLE_MAP.get(style_hint, STYLE_MAP[DEFAULT_STYLE])
    c1, c2 = style["gradient"]

    img = Image.new("RGB", (width, height))
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(c1[0] + (c2[0] - c1[0]) * ratio)
        g = int(c1[1] + (c2[1] - c1[1]) * ratio)
        b = int(c1[2] + (c2[2] - c1[2]) * ratio)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    return img


def _generate_imagen_bg(
    width: int, height: int, style_hint: str, context: str
) -> Image.Image | None:
    """Generate background via Gemini Imagen API. Returns None on failure."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[thumbnailer] No GEMINI_API_KEY — skipping Imagen")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        style_desc = {
            "bold-energy": "vibrant, high-energy, dynamic colors, action feel",
            "clean-minimal": "clean, modern, subtle tech aesthetic, soft gradients",
            "dramatic": "moody, cinematic, dark tones, dramatic lighting",
            "fun-colorful": "bright, playful, colorful, cheerful vibes",
        }.get(style_hint, "modern, clean aesthetic")

        prompt = (
            f"Abstract background for a YouTube thumbnail, {style_desc}, "
            f"related to: {context}. "
            f"No text, no people, no faces. Visually striking, high contrast."
        )

        print("[thumbnailer] Generating Imagen background...")
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=genai.types.GenerateImagesConfig(
                number_of_images=1,
            ),
        )

        if response.generated_images:
            img_data = response.generated_images[0].image.image_bytes
            from io import BytesIO
            img = Image.open(BytesIO(img_data)).convert("RGB")
            img = _crop_center(img, width, height)
            print("[thumbnailer] Imagen background generated")
            return img

    except Exception as e:
        print(f"[thumbnailer] Imagen failed: {e}")

    return None


# ── Text rendering ──────────────────────────────────────────────────────────


def _load_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    """Load font at given size, setting bold weight for variable fonts."""
    if font_path:
        font = ImageFont.truetype(str(font_path), size)
        # Set variable font to bold/extrabold weight if supported
        try:
            axes = font.get_variation_axes()
            for axis in axes:
                if axis["name"] == b"Weight":
                    # Use 800 (ExtraBold) or max available
                    bold_weight = min(800, axis["maximum"])
                    font.set_variation_by_axes([bold_weight])
                    break
        except Exception:
            pass
        return font
    try:
        return ImageFont.truetype("Arial Bold", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Split text into lines that fit within max_width."""
    words = text.split()
    if not words:
        return [text]

    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _auto_size_font(
    font_path: Path | None, text: str, max_width: int,
    max_size: int = 120, min_size: int = 32, max_lines: int = 2,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Find the largest font size where text fits within max_width in max_lines lines.
    Returns (font, lines)."""
    for size in range(max_size, min_size - 1, -2):
        font = _load_font(font_path, size)
        lines = _wrap_text(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines

    # Return minimum size
    font = _load_font(font_path, min_size)
    lines = _wrap_text(text, font, max_width)
    return font, lines


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color: tuple[int, int, int],
    outline_color: tuple[int, int, int],
    outline_width: int = 4,
    anchor: str = "mm",
) -> None:
    """Draw text with outline effect (stroke in 8 directions + shadow)."""
    x, y = position

    # Drop shadow
    shadow_offset = max(2, outline_width // 2)
    draw.text(
        (x + shadow_offset, y + shadow_offset),
        text, font=font, fill=(0, 0, 0, 160), anchor=anchor,
    )

    # Outline via stroke
    draw.text(
        (x, y), text, font=font, fill=text_color, anchor=anchor,
        stroke_width=outline_width, stroke_fill=outline_color,
    )


def _draw_dark_band(img: Image.Image, center_y: int, band_height: int) -> Image.Image:
    """Draw a horizontal dark gradient band behind text for readability."""
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    half = band_height // 2
    top = max(0, center_y - half)
    bottom = min(img.height, center_y + half)

    for y in range(top, bottom):
        dist = abs(y - center_y) / max(half, 1)
        alpha = int(110 * (1 - dist ** 2.0))
        alpha = max(0, min(255, alpha))
        draw.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(img, overlay)


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


def _draw_thumbnail_text(
    img: Image.Image,
    main_text: str,
    sub_text: str | None,
    style_hint: str,
    position: str = "center",
) -> Image.Image:
    """Overlay main_text (and optional sub_text) onto the image."""
    img = img.convert("RGBA")
    font_path = _find_font()
    w, h = img.size

    style = STYLE_MAP.get(style_hint, STYLE_MAP[DEFAULT_STYLE])
    accent_color = style.get("accent", (255, 220, 0))

    main_text = main_text.upper()
    if position in ("left", "right"):
        max_text_width = int(w * 0.55)
    else:
        max_text_width = int(w * 0.65)

    # Main text — auto-size with word wrap (up to 2 lines)
    main_font, main_lines = _auto_size_font(
        font_path, main_text, max_text_width,
        max_size=int(w * 0.12),  # slightly smaller for cleaner look
        min_size=int(w * 0.05),
        max_lines=2,
    )

    # Measure line height
    sample_bbox = main_font.getbbox("Ag")
    line_h = sample_bbox[3] - sample_bbox[1]
    line_spacing = int(line_h * 0.15)

    # Total main block height
    main_block_h = line_h * len(main_lines) + line_spacing * (len(main_lines) - 1)

    # Sub text
    sub_font = None
    sub_lines = []
    sub_line_h = 0
    if sub_text:
        sub_text = sub_text.upper()
        sub_max_width = int(w * 0.80)  # sub_text gets more room to be prominent
        sub_font, sub_lines = _auto_size_font(
            font_path, sub_text, sub_max_width,
            max_size=int(w * 0.09),
            min_size=int(w * 0.035),
            max_lines=1,
        )
        sub_bbox = sub_font.getbbox("Ag")
        sub_line_h = sub_bbox[3] - sub_bbox[1]

    # Total text block height
    gap = int(line_h * 0.3) if sub_lines else 0
    total_h = main_block_h + gap + (sub_line_h if sub_lines else 0)

    # Vertical position — text goes upper to leave room for face/subject below
    if position == "upper":
        block_top = int(h * 0.15)
    elif position in ("left", "right"):
        block_top = int(h * 0.35) - total_h // 2
    else:
        # Center-top: text in upper third, subject visible in lower half
        block_top = int(h * 0.08)

    # Horizontal position — rule of thirds
    if position == "left":
        text_x = int(w * 0.05)
        anchor = "lm"
    elif position == "right":
        text_x = int(w * 0.95)
        anchor = "rm"
    else:
        text_x = w // 2
        anchor = "mm"

    # Dark band behind text — tight to text area only
    band_center = block_top + total_h // 2
    img = _draw_dark_band(img, band_center, total_h + int(line_h * 0.6))

    draw = ImageDraw.Draw(img)
    outline_w = max(6, int(line_h * 0.08))

    # Draw main text lines
    y = block_top
    for line in main_lines:
        _draw_text_with_outline(
            draw, (text_x, y + line_h // 2), line,
            main_font, (255, 255, 255), (0, 0, 0),
            outline_width=outline_w, anchor=anchor,
        )
        y += line_h + line_spacing

    # Draw sub text with accent color
    if sub_lines and sub_font:
        y += gap
        sub_outline = max(4, int(sub_line_h * 0.08))
        for line in sub_lines:
            _draw_text_with_outline(
                draw, (text_x, y + sub_line_h // 2), line,
                sub_font, accent_color, (0, 0, 0),
                outline_width=sub_outline, anchor=anchor,
            )
            y += sub_line_h

    return img.convert("RGB")


# ── Thumbnail flows ─────────────────────────────────────────────────────────


def _thumbnail_short(workspace: Path, metadata: dict, pipeline: dict) -> Path:
    """Generate thumbnail for short video: best frame + bold text."""
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("short_title", ""))
    sub_text = thumb_data.get("sub_text")
    style_hint = thumb_data.get("style_hint", DEFAULT_STYLE)

    w, h = SHORT_SIZE

    transcription_path = workspace / "transcription.json"
    transcription = json.loads(transcription_path.read_text()) if transcription_path.exists() else {}

    duration = transcription.get("duration", 30.0)
    energy_peak = _find_energy_peak(transcription)
    video_path = pipeline["video_path"]

    frame_path = _pick_best_frame(video_path, duration, workspace, energy_peak)

    img = Image.open(frame_path)
    img = _crop_center(img, w, h)

    # Overlay text
    img = _draw_thumbnail_text(img, main_text, sub_text, style_hint, position="center")

    # Composite logos if specified
    logo_names = thumb_data.get("logos")
    logo_paths = _find_logo_assets(logo_names)
    if logo_paths:
        img = _composite_logos(img, logo_paths, "top-left")
        img = img.convert("RGB")

    output = workspace / "thumbnail.png"
    img.save(output, "PNG", quality=95)
    print(f"[thumbnailer] Short thumbnail → {output}")

    # Cleanup temp frame
    frame_path.unlink(missing_ok=True)
    return output


def _thumbnail_long(workspace: Path, metadata: dict, pipeline: dict) -> Path:
    """Generate thumbnail for long video: AI background + face + title."""
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("youtube_title", ""))
    sub_text = thumb_data.get("sub_text")
    style_hint = thumb_data.get("style_hint", DEFAULT_STYLE)
    context = pipeline.get("context", "")

    w, h = LONG_SIZE

    # Background: try Imagen → frame from video → gradient (last resort)
    bg = _generate_imagen_bg(w, h, style_hint, context)

    if bg is None:
        transcription_path = workspace / "transcription.json"
        transcription = json.loads(transcription_path.read_text()) if transcription_path.exists() else {}
        duration = transcription.get("duration", 30.0)
        energy_peak = _find_energy_peak(transcription)
        video_path = pipeline["video_path"]

        try:
            frame_path = _pick_best_frame(video_path, duration, workspace, energy_peak)
            bg = _stylize_frame_bg(Image.open(frame_path))
            print("[thumbnailer] Using best-scored video frame as background")
            frame_path.unlink(missing_ok=True)
        except Exception:
            print("[thumbnailer] Frame extraction failed — using gradient fallback")
            bg = _generate_gradient_bg(w, h, style_hint)

    bg = _crop_center(bg, w, h)
    img = bg.convert("RGBA")

    # Composite face asset if available
    face_path = _find_face_asset()
    has_face = False
    if face_path:
        face = Image.open(face_path).convert("RGBA")
        face_h = int(h * 0.75)
        face_ratio = face.width / face.height
        face_w = int(face_h * face_ratio)
        face = face.resize((face_w, face_h), Image.LANCZOS)

        # Position: bottom-right, flush
        face_x = w - face_w
        face_y = h - face_h
        img.paste(face, (face_x, face_y), face)
        has_face = True
        print(f"[thumbnailer] Face composited from {face_path.name}")

    # Text position: left (rule of thirds) if face on right, center otherwise
    text_pos = "left" if has_face else "center"

    img_rgb = img.convert("RGB")
    img_rgb = _draw_thumbnail_text(img_rgb, main_text, sub_text, style_hint, position=text_pos)

    # Composite logos if specified
    logo_names = thumb_data.get("logos")
    logo_paths = _find_logo_assets(logo_names)
    if logo_paths:
        logo_pos = "top-left" if has_face else "top-right"
        img_rgb = _composite_logos(img_rgb, logo_paths, logo_pos)
        img_rgb = img_rgb.convert("RGB")

    output = workspace / "thumbnail.png"
    img_rgb.save(output, "PNG", quality=95)
    print(f"[thumbnailer] Long thumbnail → {output}")
    return output


# ── Cover frame embedding ───────────────────────────────────────────────────


def _embed_cover_frame(workspace: Path, thumb_path: Path) -> None:
    """Prepend the thumbnail as a brief still frame at the start of the final video.

    This makes platforms like YouTube Shorts and Instagram pick it up
    as the cover/thumbnail automatically (since they use the first frame).
    """
    # Find the final video (captioned > overlaid > edited)
    for name in ["captioned_video.mp4", "overlaid_video.mp4", "edited_video.mp4"]:
        video_path = workspace / name
        if video_path.exists():
            break
    else:
        print("[thumbnailer] No video found to embed cover frame — skipping")
        return

    # Get video specs (fps, resolution, audio sample rate) to match
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,width,height",
        "-of", "csv=p=0", str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    parts = result.stdout.strip().split(",")
    vid_w, vid_h = int(parts[0]), int(parts[1])
    fps_str = parts[2]  # e.g. "30/1"

    # Create a short video clip from the thumbnail image (0.1s)
    cover_clip = workspace / "thumb_cover.mp4"
    # Scale thumbnail to match video dimensions, generate 0.1s of silent video
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(thumb_path),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "0.1",
        "-vf", f"scale={vid_w}:{vid_h}:flags=lanczos,format=yuv420p",
        "-r", fps_str,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(cover_clip),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Concat: cover clip + original video
    concat_list = workspace / "thumb_concat.txt"
    concat_list.write_text(
        f"file '{cover_clip.resolve()}'\nfile '{video_path.resolve()}'\n"
    )

    output = workspace / "cover_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Replace the original video with the cover version
    output.replace(video_path)
    print(f"[thumbnailer] Cover frame embedded into {video_path.name}")

    # Cleanup temp files
    cover_clip.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)


# ── Entry point ─────────────────────────────────────────────────────────────


def thumbnail(workspace: Path) -> None:
    """Main entry point — called by ralph.sh via run_python_tool."""
    pipeline = json.loads((workspace / "pipeline.json").read_text())

    metadata_path = workspace / "metadata.json"
    if not metadata_path.exists():
        print("[thumbnailer] WARNING: metadata.json not found — skipping thumbnail")
        return

    metadata = json.loads(metadata_path.read_text())

    video_type = pipeline.get("type", "short")

    if video_type == "short":
        thumb = _thumbnail_short(workspace, metadata, pipeline)
    else:
        thumb = _thumbnail_long(workspace, metadata, pipeline)

    # Embed thumbnail as first frame so platforms pick it up as cover
    _embed_cover_frame(workspace, thumb)


if __name__ == "__main__":
    ws = Path(sys.argv[1])
    thumbnail(ws)
