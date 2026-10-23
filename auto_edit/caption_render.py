"""Draw the short's burned-in captions from the caption tokens.

ASS in video pixels (PlayRes = W×H), burned by ffmpeg/libass with a fonts
folder that holds only the chosen TTF. No whisper here: the style preview
imports this module too.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pysubs2

from auto_edit import caption_style, probe, styles

MAX_GAP_FOR_GROUP = 0.6  # seconds — gap larger than this starts a new group
FONTS_DIR = ".caption-fonts"

# libass' implicit canvas when the ASS has no PlayRes: the old look lived there.
_BASE_W, _BASE_H = 384, 288
_FONT_SIZE = 14
_MARGIN_X = 10
_HIGHLIGHT_BORDER = 5 / 3  # highlight outline = outline × 5/3 (1.5 → 2.5)
_HIGHLIGHT_BLUR = 0.8
_BOX_PAD = 3  # box padding around the glyphs, at base size
# Today's captions asked for "Montserrat" and libass fell back to Helvetica
# Bold, whose (win ascent + descent)/em is 1.192: that is the em to keep.
_BASE_HEIGHT_RATIO = 1.192
_BLACK = "&H000000&"


# ── Grouping ──────────────────────────────────────────────────────────────────

def group_words(words: list[dict], max_words: int) -> list[list[dict]]:
    """Chunks of at most `max_words`; a large gap starts a new chunk."""
    if not words:
        return []
    groups: list[list[dict]] = []
    current: list[dict] = [words[0]]
    for w in words[1:]:
        gap = w["start"] - current[-1]["end"]
        if len(current) >= max_words or gap > MAX_GAP_FOR_GROUP:
            groups.append(current)
            current = [w]
        else:
            current.append(w)
    groups.append(current)
    return groups


# ── Fonts ─────────────────────────────────────────────────────────────────────

def _font_spec(font_id: str) -> dict:
    return styles.FONTS.get(font_id) or styles.FONTS[caption_style.DEFAULT["font"]]


def _tables(data: bytes) -> dict[bytes, int]:
    """sfnt table tag → offset."""
    (num_tables,) = struct.unpack(">H", data[4:6])
    out = {}
    for i in range(num_tables):
        tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag] = offset
    return out


def _name_table_family(path: Path) -> str | None:
    """Legacy family (name ID 1) of a TTF — the name libass matches.

    Not the typographic family (ID 16) that FreeType/PIL report: a static
    Montserrat-ExtraBold is "Montserrat ExtraBold" to libass, and asking for
    "Montserrat" falls back to a system font.
    """
    try:
        data = path.read_bytes()
        offset = _tables(data).get(b"name")
        if offset is None:
            return None
        _, count, strings = struct.unpack(">HHH", data[offset:offset + 6])
        found: dict[int, str] = {}
        for r in range(count):
            rec = offset + 6 + 12 * r
            platform, _, _, name_id, length, start = struct.unpack(">HHHHHH", data[rec:rec + 12])
            if name_id != 1 or platform not in (1, 3):
                continue
            raw = data[offset + strings + start:offset + strings + start + length]
            found.setdefault(platform, raw.decode("utf-16-be" if platform == 3 else "mac-roman"))
        return found.get(3) or found.get(1)
    except (OSError, struct.error, UnicodeDecodeError):
        return None


def _height_ratio(path: Path) -> float | None:
    """(ascent + descent) / unitsPerEm as libass sizes the font: OS/2 win
    metrics, hhea when they're missing. libass makes this height = Fontsize."""
    try:
        data = path.read_bytes()
        tables = _tables(data)
        (upem,) = struct.unpack(">H", data[tables[b"head"] + 18:tables[b"head"] + 20])
        os2 = tables.get(b"OS/2")
        if os2 is not None:
            win_ascent, win_descent = struct.unpack(">HH", data[os2 + 74:os2 + 78])
            if win_ascent + win_descent:
                return (win_ascent + win_descent) / upem
        ascent, descent = struct.unpack(">hh", data[tables[b"hhea"] + 4:tables[b"hhea"] + 8])
        return (ascent - descent) / upem if upem and ascent - descent else None
    except (OSError, KeyError, struct.error):
        return None


def size_factor(font_id: str) -> float:
    """Fontsize multiplier that gives every font the em of today's captions."""
    path = styles.font_file(_font_spec(font_id)["bold"])
    ratio = _height_ratio(path) if path else None
    return ratio / _BASE_HEIGHT_RATIO if ratio else 1.0


def font_family(font_id: str) -> str:
    """Family name libass must ask for, read from the TTF itself."""
    spec = _font_spec(font_id)
    path = styles.font_file(spec["bold"])
    return (_name_table_family(path) if path else None) or spec["label"]


def prepare_fonts(font_id: str, folder: Path) -> Path:
    """`folder/.caption-fonts/` with only the chosen bold TTF; returns its name."""
    target = Path(folder) / FONTS_DIR
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    path = styles.font_file(_font_spec(font_id)["bold"])
    if path is not None:
        shutil.copyfile(path, target / path.name)
    return Path(FONTS_DIR)


# ── ASS ───────────────────────────────────────────────────────────────────────

def _n(x: float) -> str:
    return f"{x:.2f}"


def _color(hex_color: str) -> pysubs2.Color:
    h = hex_color.lstrip("#")
    return pysubs2.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _word_end(group: list[dict], j: int) -> int:
    """Extend to the next word's start when the gap is small."""
    end = int(group[j]["end"] * 1000)
    if j < len(group) - 1:
        nxt = int(group[j + 1]["start"] * 1000)
        if nxt - end < 500:
            return nxt
    return end


def build_ass(groups: list[list[dict]], captions: dict, width: int, height: int) -> pysubs2.SSAFile:
    c = caption_style.validate(captions)
    s = height / _BASE_H
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(width)
    subs.info["PlayResY"] = str(height)
    subs.info["ScaledBorderAndShadow"] = "yes"

    fontsize = round(_FONT_SIZE * s * c["size"] / 100 * size_factor(c["font"]), 2)
    outline = round(c["outline"] * s, 2)
    st = pysubs2.SSAStyle()
    st.fontname = font_family(c["font"])
    st.fontsize = fontsize
    st.bold = False  # the TTF is already heavy; synthetic bold thickens Bebas/Anton
    st.primarycolor = _color(c["color"])
    st.outlinecolor = pysubs2.Color(0, 0, 0)
    st.outline = outline
    st.shadow = 0
    st.marginl = st.marginr = round(_MARGIN_X * width / _BASE_W)
    if c["position"] == "middle":
        st.alignment, st.marginv = pysubs2.Alignment(5), 0
    else:
        st.alignment = pysubs2.Alignment(8 if c["position"] == "top" else 2)
        st.marginv = round(c["offset"] / 100 * height)
    subs.styles["Default"] = st

    mode = c["highlight_mode"]
    with_box = mode == "box" or c["background"] == "box"
    if with_box:
        box = st.copy()
        box.borderstyle = 3
        box.outlinecolor = _color(c["highlight"])
        box.outline = round(_BOX_PAD * s * c["size"] / 100, 2)
        subs.styles["Box"] = box

    color = caption_style.ass_color(c["color"])
    hl = caption_style.ass_color(c["highlight"])
    normal = rf"{{\1c{color}\3c{_BLACK}\bord{_n(outline)}\blur0}}"
    if mode == "outline":
        spoken = (rf"{{\1c{color}\3c{hl}\bord{_n(outline * _HIGHLIGHT_BORDER)}"
                  rf"\blur{_n(_HIGHLIGHT_BLUR * s)}}}")
    elif mode == "fill":
        spoken = rf"{{\1c{hl}}}"
    else:  # box: the box layer paints the highlight; the word stays readable on it
        on_box = _BLACK if _luminance(c["highlight"]) > 0.6 else color
        spoken = rf"{{\1c{on_box}\bord0}}"  # no outline inside the box

    # One layer per event kind: libass pushes apart overlapping events of the
    # same layer (Collisions), which would move the boxes off the text.
    bg_layer = 0
    hl_layer = 1 if c["background"] == "box" else 0
    text_layer = (c["background"] == "box") + (mode == "box")

    for group in groups:
        display = [w["word"].strip() for w in group]
        if c["uppercase"]:
            display = [t.upper() for t in display]
        for j, word in enumerate(group):
            start, end = int(word["start"] * 1000), _word_end(group, j)
            if c["background"] == "box":
                subs.events.append(pysubs2.SSAEvent(
                    start=start, end=end, layer=bg_layer, style="Box",
                    text=rf"{{\1a&HFF&\3c{_BLACK}\3a&H60&}}" + " ".join(display)))
            if mode == "box":
                parts = []
                for k, txt in enumerate(display):
                    parts.append(rf"{{\3a&H00&}}{txt}{{\3a&HFF&}}" if k == j else txt)
                subs.events.append(pysubs2.SSAEvent(
                    start=start, end=end, layer=hl_layer, style="Box",
                    text=r"{\1a&HFF&\3a&HFF&}" + " ".join(parts)))
            parts = [f"{spoken}{txt}{normal}" if k == j else txt for k, txt in enumerate(display)]
            subs.events.append(pysubs2.SSAEvent(
                start=start, end=end, layer=text_layer, style="Default",
                text=" ".join(parts)))
    return subs


# ── Burning ───────────────────────────────────────────────────────────────────

def _subtitles_filter(ass_name: str, fonts_name: str) -> str:
    return f"subtitles={ass_name}:fontsdir={fonts_name}"


def burn_command(ffmpeg: str, video: Path, ass_name: str, fonts_name: str, output: Path) -> list[str]:
    """Run with cwd = the ASS folder: the filter only sees relative names, so
    drive letters, spaces and accents in the path never reach it."""
    return [
        ffmpeg, "-y",
        "-i", str(Path(video).absolute()),
        "-vf", _subtitles_filter(ass_name, fonts_name),
        "-c:a", "copy",
        "-movflags", "+faststart", "-brand", "mp42",
        str(Path(output).absolute()),
    ]


PREVIEW_SENTENCE = "Editei esse vídeo com IA"
_PREVIEW_AT = 1.5  # seconds into the 0-5s event


def preview_words(max_words: int) -> tuple[list[dict], int]:
    """The sample phrase cut to one caption line, and the index of the spoken
    word (the 3rd, or the last when the line is shorter)."""
    texts = PREVIEW_SENTENCE.split()[:max(1, max_words)]
    hl = min(2, len(texts) - 1)
    words = []
    for i, text in enumerate(texts):
        if i < hl:
            start = 1.0 - 0.1 * (hl - i)
            words.append({"word": text, "start": start, "end": start + 0.1})
        elif i == hl:
            words.append({"word": text, "start": 1.0, "end": 5.0})
        else:
            start = 5.0 + 0.1 * (i - hl - 1)  # right after: same line, shown but not yet spoken
            words.append({"word": text, "start": start, "end": start + 0.1})
    return words, hl


def render_preview(captions: dict, frame: Path | None, width: int, height: int) -> bytes:
    """PNG of one caption line burnt by the same ASS + libass path as a real
    video. No frame → a dark grey background. Raises RuntimeError on failure."""
    import tempfile

    ffmpeg = resolve_ffmpeg()
    c = caption_style.validate(captions)
    words, _ = preview_words(c["words"])
    groups = group_words(words, c["words"])[:1]  # close together: one line
    with tempfile.TemporaryDirectory(prefix="auto-edit-caption-") as tmp:
        folder = Path(tmp)
        build_ass(groups, c, width, height).save(str(folder / "captions.ass"))
        fonts = prepare_fonts(c["font"], folder)
        if frame is not None:
            source = ["-loop", "1", "-t", "5", "-i", str(Path(frame).absolute())]
        else:
            source = ["-f", "lavfi", "-i", f"color=c=0x303030:s={width}x{height}:d=5"]
        cmd = [ffmpeg, "-y", "-v", "error", *source,
               "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                      + _subtitles_filter("captions.ass", str(fonts)),
               "-ss", str(_PREVIEW_AT), "-frames:v", "1", "preview.png"]
        res = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, timeout=60)
        out = folder / "preview.png"
        if res.returncode != 0 or not out.is_file():
            raise RuntimeError(f"ffmpeg falhou na prévia da legenda: {(res.stderr or '').strip()[-300:]}")
        return out.read_bytes()


def video_size(path: Path) -> tuple[int, int]:
    return probe.video_size(path)


def _ffmpeg_has_subtitles(binary: str) -> bool:
    """True if this ffmpeg build exposes the libass 'subtitles' filter."""
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return " subtitles " in (result.stdout or "")


def _known_ffmpeg_locations() -> list[str]:
    """Where an ffmpeg with libass usually lives when it isn't on PATH.

    The desktop app runs the engine from the repo .venv, whose PATH only has
    Homebrew's ffmpeg (no libass) — the nix `ffmpeg-full` the CLI wrapper puts
    on PATH is not there. Last resort: the newest ffmpeg-full in the nix store.
    """
    home = Path.home()
    paths = [
        home / ".nix-profile/bin/ffmpeg",
        Path("/etc/profiles/per-user") / home.name / "bin/ffmpeg",
        Path("/run/current-system/sw/bin/ffmpeg"),
        Path("/nix/var/nix/profiles/default/bin/ffmpeg"),
        Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
        Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
    ]
    store = Path("/nix/store")
    if store.is_dir():
        try:
            full = sorted(
                store.glob("*-ffmpeg-full-*-bin/bin/ffmpeg"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            full = []
        paths.extend(full)
    return [str(p) for p in paths]


def resolve_ffmpeg() -> str:
    """Find an ffmpeg build with libass (the 'subtitles' filter) to burn captions.

    Order: AUTO_EDIT_FFMPEG override, each ffmpeg on PATH, then the usual
    nix/Homebrew ffmpeg-full spots. Raises with an actionable message if none
    has libass — many Homebrew builds ship without it.
    """
    candidates: list[str] = []
    env = os.environ.get("AUTO_EDIT_FFMPEG")
    if env:
        candidates.append(env)

    seen = set(candidates)
    on_path = [
        os.path.join(d, "ffmpeg")
        for d in os.environ.get("PATH", "").split(os.pathsep)
        if d
    ]
    for p in on_path + _known_ffmpeg_locations():
        if p not in seen and os.path.isfile(p) and os.access(p, os.X_OK):
            seen.add(p)
            candidates.append(p)

    for binary in candidates:
        if _ffmpeg_has_subtitles(binary):
            return binary

    raise RuntimeError(
        "Nenhum ffmpeg com libass encontrado (filtro 'subtitles' ausente) — "
        "necessário pra queimar legendas. Instale um ffmpeg com libass "
        "(ex: `brew reinstall ffmpeg`) ou aponte AUTO_EDIT_FFMPEG para um "
        "binário com libass."
    )
