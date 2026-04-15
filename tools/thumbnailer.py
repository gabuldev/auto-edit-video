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


def _stylize_frame_bg(img: Image.Image) -> Image.Image:
    """Turn a raw video frame into a styled thumbnail background.

    Applies blur, saturation boost, darkening, and vignette so the frame
    looks like a designed background rather than a screenshot.
    """
    # 1. Gaussian blur — bokeh effect
    img = img.filter(ImageFilter.GaussianBlur(radius=15))

    # 2. Boost saturation — more vivid colors
    img = ImageEnhance.Color(img).enhance(1.4)

    # 3. Darken — better contrast with white text
    img = ImageEnhance.Brightness(img).enhance(0.55)

    # 4. Vignette — darken edges via radial gradient mask
    w, h = img.size
    # Build small vignette mask then upscale (fast)
    sw, sh = 64, 64
    y_arr, x_arr = np.mgrid[0:sh, 0:sw]
    cx, cy = sw / 2, sh / 2
    dist = np.sqrt((x_arr - cx) ** 2 + (y_arr - cy) ** 2) / np.sqrt(cx ** 2 + cy ** 2)
    alpha = np.clip(180 * dist ** 1.8, 0, 255).astype(np.uint8)
    mask = Image.fromarray(alpha, mode="L").resize((w, h), Image.LANCZOS)
    black = Image.new("RGB", (w, h), (0, 0, 0))
    img = img.convert("RGB")
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
        alpha = int(160 * (1 - dist ** 1.5))
        alpha = max(0, min(255, alpha))
        draw.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(img, overlay)


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

    main_text = main_text.upper()
    max_text_width = int(w * 0.90)

    # Main text — auto-size with word wrap (up to 2 lines)
    main_font, main_lines = _auto_size_font(
        font_path, main_text, max_text_width,
        max_size=int(w * 0.14),  # ~150px on 1080w
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
        sub_font, sub_lines = _auto_size_font(
            font_path, sub_text, max_text_width,
            max_size=int(w * 0.07),
            min_size=int(w * 0.035),
            max_lines=1,
        )
        sub_bbox = sub_font.getbbox("Ag")
        sub_line_h = sub_bbox[3] - sub_bbox[1]

    # Total text block height
    gap = int(line_h * 0.3) if sub_lines else 0
    total_h = main_block_h + gap + (sub_line_h if sub_lines else 0)

    # Vertical position
    if position == "upper":
        block_top = int(h * 0.20)
    else:
        block_top = int(h * 0.45) - total_h // 2

    center_x = w // 2

    # Dark band behind text
    band_center = block_top + total_h // 2
    img = _draw_dark_band(img, band_center, total_h + int(line_h * 1.2))

    draw = ImageDraw.Draw(img)
    outline_w = max(6, int(line_h * 0.08))

    # Draw main text lines
    y = block_top
    for line in main_lines:
        _draw_text_with_outline(
            draw, (center_x, y + line_h // 2), line,
            main_font, (255, 255, 255), (0, 0, 0), outline_width=outline_w,
        )
        y += line_h + line_spacing

    # Draw sub text
    if sub_lines and sub_font:
        y += gap
        sub_outline = max(4, int(sub_line_h * 0.08))
        for line in sub_lines:
            _draw_text_with_outline(
                draw, (center_x, y + sub_line_h // 2), line,
                sub_font, (255, 255, 255), (0, 0, 0), outline_width=sub_outline,
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

    # Background: try Imagen → frame from video → gradient (last resort)
    bg = _generate_imagen_bg(w, h, style_hint, context)

    if bg is None:
        # Fallback: use a frame from the video (same as shorts)
        transcription_path = workspace / "transcription.json"
        transcription = json.loads(transcription_path.read_text()) if transcription_path.exists() else {}
        peak_time = _find_energy_peak(transcription)
        video_path = pipeline["video_path"]
        frame_path = workspace / "thumb_frame_long.jpg"

        try:
            _extract_frame(video_path, peak_time, frame_path)
            bg = _stylize_frame_bg(Image.open(frame_path))
            print("[thumbnailer] Using stylized video frame as background")
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
        face_h = int(h * 0.60)
        face_ratio = face.width / face.height
        face_w = int(face_h * face_ratio)
        face = face.resize((face_w, face_h), Image.LANCZOS)

        # Position: bottom-right
        face_x = w - face_w + int(face_w * 0.05)
        face_y = h - face_h
        img.paste(face, (face_x, face_y), face)
        has_face = True
        print(f"[thumbnailer] Face composited from {face_path.name}")

    # Text position: upper if face present, center otherwise
    text_pos = "upper" if has_face else "center"

    img_rgb = img.convert("RGB")
    img_rgb = _draw_thumbnail_text(img_rgb, main_text, sub_text, style_hint, position=text_pos)

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
