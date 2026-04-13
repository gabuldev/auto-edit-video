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

from PIL import Image, ImageDraw, ImageFont

# ── Dimensions ──────────────────────────────────────────────────────────────

SHORT_SIZE = (1080, 1920)   # 9:16 portrait
LONG_SIZE = (1280, 720)     # 16:9 landscape

ENERGY_RESOLUTION = 0.5     # must match extract.py

# ── Style mapping ───────────────────────────────────────────────────────────

STYLE_MAP = {
    "bold-energy": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "tint": (255, 50, 0, 80),
        "gradient": ((200, 30, 0), (255, 100, 0)),
    },
    "clean-minimal": {
        "text": (255, 255, 255),
        "outline": (40, 40, 40),
        "tint": (0, 0, 0, 60),
        "gradient": ((30, 30, 50), (60, 60, 80)),
    },
    "dramatic": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "tint": (0, 0, 0, 120),
        "gradient": ((10, 10, 30), (40, 20, 60)),
    },
    "fun-colorful": {
        "text": (255, 255, 255),
        "outline": (0, 0, 0),
        "tint": (255, 200, 0, 80),
        "gradient": ((255, 100, 50), (255, 200, 0)),
    },
}

DEFAULT_STYLE = "clean-minimal"

# ── Asset helpers ───────────────────────────────────────────────────────────


def _repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _find_font() -> Path | None:
    """Find a bold TTF font in assets/thumbnails/fonts/."""
    dirs = []
    env = os.environ.get("AUTO_EDIT_ASSETS_FONTS")
    if env:
        dirs.append(Path(env))
    dirs.append(_repo_root() / "assets" / "thumbnails" / "fonts")

    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.ttf")):
            return f
        for f in sorted(d.glob("*.otf")):
            return f
    return None


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


# ── Frame extraction ────────────────────────────────────────────────────────


def _find_energy_peak(transcription: dict) -> float:
    """Return timestamp (seconds) of the energy peak in the transcription."""
    energy_db = transcription.get("energy_db", [])
    if not energy_db:
        # Fallback: use 25% of video duration (usually an interesting moment)
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

        print(f"[thumbnailer] Generating Imagen background...")
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


def _auto_size_font(
    font_path: Path | None, text: str, max_width: int, max_size: int = 120, min_size: int = 32
) -> ImageFont.FreeTypeFont:
    """Find the largest font size where text fits within max_width."""
    for size in range(max_size, min_size - 1, -2):
        if font_path:
            font = ImageFont.truetype(str(font_path), size)
        else:
            try:
                font = ImageFont.truetype("Arial Bold", size)
            except OSError:
                font = ImageFont.load_default(size=size)
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        if text_width <= max_width:
            return font

    # Return minimum size
    if font_path:
        return ImageFont.truetype(str(font_path), min_size)
    return ImageFont.load_default(size=min_size)


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color: tuple[int, int, int],
    outline_color: tuple[int, int, int],
    outline_width: int = 4,
) -> None:
    """Draw text with outline effect (stroke in 8 directions + shadow)."""
    x, y = position

    # Drop shadow
    shadow_offset = max(2, outline_width // 2)
    draw.text(
        (x + shadow_offset, y + shadow_offset),
        text, font=font, fill=(0, 0, 0, 160), anchor="mm",
    )

    # Outline via stroke
    draw.text(
        (x, y), text, font=font, fill=text_color, anchor="mm",
        stroke_width=outline_width, stroke_fill=outline_color,
    )


def _draw_thumbnail_text(
    img: Image.Image,
    main_text: str,
    sub_text: str | None,
    style_hint: str,
    position: str = "center",
) -> Image.Image:
    """Overlay main_text (and optional sub_text) onto the image.

    position: "center" (for shorts) or "upper" (for longs, to avoid face area)
    """
    style = STYLE_MAP.get(style_hint, STYLE_MAP[DEFAULT_STYLE])
    img = img.convert("RGBA")

    # Apply tint overlay for better text readability
    tint = Image.new("RGBA", img.size, style["tint"])
    img = Image.alpha_composite(img, tint)

    draw = ImageDraw.Draw(img)
    font_path = _find_font()

    main_text = main_text.upper()
    max_text_width = int(img.width * 0.80)

    # Main text
    main_font = _auto_size_font(font_path, main_text, max_text_width, max_size=120, min_size=36)

    if position == "upper":
        main_y = int(img.height * 0.30)
    else:
        main_y = int(img.height * 0.45)

    main_x = img.width // 2

    _draw_text_with_outline(
        draw, (main_x, main_y), main_text,
        main_font, style["text"], style["outline"], outline_width=5,
    )

    # Sub text
    if sub_text:
        sub_text = sub_text.upper()
        sub_font = _auto_size_font(font_path, sub_text, max_text_width, max_size=60, min_size=24)
        main_bbox = main_font.getbbox(main_text)
        main_height = main_bbox[3] - main_bbox[1]
        sub_y = main_y + main_height // 2 + 30

        _draw_text_with_outline(
            draw, (main_x, sub_y), sub_text,
            sub_font, style["text"], style["outline"], outline_width=3,
        )

    return img.convert("RGB")


# ── Thumbnail flows ─────────────────────────────────────────────────────────


def _thumbnail_short(workspace: Path, metadata: dict, pipeline: dict) -> Path:
    """Generate thumbnail for short video: best frame + bold text."""
    thumb_data = metadata.get("thumbnail", {})
    main_text = thumb_data.get("main_text", metadata.get("short_title", ""))
    sub_text = thumb_data.get("sub_text")
    style_hint = thumb_data.get("style_hint", DEFAULT_STYLE)

    w, h = SHORT_SIZE

    # Extract best frame from original video
    transcription_path = workspace / "transcription.json"
    transcription = json.loads(transcription_path.read_text()) if transcription_path.exists() else {}

    peak_time = _find_energy_peak(transcription)
    video_path = pipeline["video_path"]

    frame_path = workspace / "thumb_frame.jpg"
    _extract_frame(video_path, peak_time, frame_path)

    img = Image.open(frame_path)
    img = _crop_center(img, w, h)

    # Overlay text
    img = _draw_thumbnail_text(img, main_text, sub_text, style_hint, position="center")

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

    # Try Gemini Imagen, fallback to gradient
    bg = _generate_imagen_bg(w, h, style_hint, context)
    if bg is None:
        print("[thumbnailer] Using gradient fallback for background")
        bg = _generate_gradient_bg(w, h, style_hint)

    img = bg.convert("RGBA")

    # Composite face asset if available
    face_path = _find_face_asset()
    if face_path:
        face = Image.open(face_path).convert("RGBA")
        # Resize face to ~45% of thumbnail height
        face_h = int(h * 0.45)
        face_ratio = face.width / face.height
        face_w = int(face_h * face_ratio)
        face = face.resize((face_w, face_h), Image.LANCZOS)

        # Position: bottom-right
        face_x = w - face_w + int(face_w * 0.05)  # slight overflow right
        face_y = h - face_h
        img.paste(face, (face_x, face_y), face)
        print(f"[thumbnailer] Face composited from {face_path.name}")
    else:
        print("[thumbnailer] No face asset found — skipping face composite")

    # Overlay title text in upper area (avoid face)
    img_rgb = img.convert("RGB")
    img_rgb = _draw_thumbnail_text(img_rgb, main_text, sub_text, style_hint, position="upper")

    output = workspace / "thumbnail.png"
    img_rgb.save(output, "PNG", quality=95)
    print(f"[thumbnailer] Long thumbnail → {output}")
    return output


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
        _thumbnail_short(workspace, metadata, pipeline)
    else:
        _thumbnail_long(workspace, metadata, pipeline)


if __name__ == "__main__":
    ws = Path(sys.argv[1])
    thumbnail(ws)
