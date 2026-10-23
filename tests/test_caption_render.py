"""Tests for auto_edit/caption_render.py — ASS from the caption tokens."""
import subprocess

import pytest

from auto_edit import caption_render, caption_style

W1 = {"word": "hello", "start": 0.0, "end": 0.4}
W2 = {"word": "world", "start": 0.5, "end": 0.9}


def _style(ass):
    return ass.styles["Default"]


def test_default_matches_todays_geometry_on_1080x1920():
    ass = caption_render.build_ass([[W1, W2]], caption_style.DEFAULT, 1080, 1920)
    s = _style(ass)
    assert ass.info["PlayResX"] == "1080" and ass.info["PlayResY"] == "1920"
    assert ass.info["ScaledBorderAndShadow"] == "yes"
    assert s.alignment == 2 and s.marginv == pytest.approx(95 / 288 * 1920, abs=2)
    # libass sizes Montserrat by its win ascent+descent (1.562 em); today's
    # captions rendered in Helvetica Bold (1.192 em) — keep that em
    assert s.fontsize == pytest.approx(14 / 288 * 1920 * 1.562 / 1.192, abs=0.5)
    assert s.outline == pytest.approx(1.5 / 288 * 1920, abs=0.05)
    assert s.marginl == s.marginr == round(10 * 1080 / 384)
    assert s.fontname == "Montserrat ExtraBold" and s.bold is False
    text = ass.events[0].text
    assert "\\3c&H0045FF&" in text and "HELLO" in text
    assert f"\\bord{2.5 / 288 * 1920:.2f}" in text
    assert f"\\blur{0.8 / 288 * 1920:.2f}" in text
    assert len(ass.events) == 2  # one event per spoken word


def test_scales_with_resolution():
    small = _style(caption_render.build_ass([[W1]], caption_style.DEFAULT, 1080, 1920))
    big = _style(caption_render.build_ass([[W1]], caption_style.DEFAULT, 2160, 3840))
    assert big.fontsize == pytest.approx(2 * small.fontsize, abs=0.05)
    assert big.marginv == pytest.approx(2 * small.marginv, abs=1)
    assert big.outline == pytest.approx(2 * small.outline, abs=0.05)


def test_top_and_middle():
    top = caption_style.validate({"position": "top", "offset": 10})
    s = _style(caption_render.build_ass([[W1]], top, 1080, 1920))
    assert s.alignment == 8 and s.marginv == pytest.approx(192, abs=1)
    mid = caption_style.validate({"position": "middle", "offset": 10})
    s = _style(caption_render.build_ass([[W1]], mid, 1080, 1920))
    assert s.alignment == 5 and s.marginv == 0


def test_size_font_colors_words_uppercase():
    c = caption_style.validate({"size": 150, "font": "bangers", "color": "#ffff00", "words": 2,
                                "uppercase": False, "highlight_mode": "fill"})
    ass = caption_render.build_ass([[W1, W2]], c, 1080, 1920)
    s = _style(ass)
    assert s.fontname == "Bangers"
    assert s.fontsize == pytest.approx(1.5 * 14 / 288 * 1920 * 1.757 / 1.192, abs=0.5)
    first = ass.events[0].text
    assert "hello" in first and "HELLO" not in first
    assert "\\1c&H0045FF&" in first  # spoken word filled with the highlight
    assert "\\1c&H00FFFF&" in first  # normal text back to the chosen color
    assert "\\3c&H0045FF&" not in first  # fill keeps the normal outline


def test_words_token_drives_grouping():
    words = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(5)]
    assert [len(g) for g in caption_render.group_words(words, 2)] == [2, 2, 1]
    assert [len(g) for g in caption_render.group_words(words, 4)] == [4, 1]


def test_box_mode_adds_a_box_layer():
    c = caption_style.validate({"highlight_mode": "box"})
    ass = caption_render.build_ass([[W1, W2]], c, 1080, 1920)
    assert ass.styles["Box"].borderstyle == 3
    boxes = [e for e in ass.events if e.style == "Box"]
    texts = [e for e in ass.events if e.style == "Default"]
    assert len(boxes) == len(texts) == 2
    assert all(e.layer == 0 for e in boxes) and all(e.layer == 1 for e in texts)
    # the box line hides the text and every outline except the spoken word's
    assert "\\1a&HFF&" in boxes[0].text
    assert boxes[0].text.count("\\3a&HFF&") >= 1
    # orange (#ff4500) is dark enough → spoken word keeps the text color
    assert "\\1c&HFFFFFF&" in texts[0].text


def test_box_mode_black_text_on_bright_highlight():
    c = caption_style.validate({"highlight_mode": "box", "highlight": "#ffff00"})
    ass = caption_render.build_ass([[W1, W2]], c, 1080, 1920)
    texts = [e for e in ass.events if e.style == "Default"]
    assert "\\1c&H000000&" in texts[0].text


def test_background_box_layer():
    c = caption_style.validate({"background": "box"})
    ass = caption_render.build_ass([[W1, W2]], c, 1080, 1920)
    bg = [e for e in ass.events if e.style == "Box"]
    assert len(bg) == 2 and all(e.layer == 0 for e in bg)
    assert "\\3c&H000000&" in bg[0].text and "\\3a&H60&" in bg[0].text and "\\1a&HFF&" in bg[0].text
    assert all(e.layer == 1 for e in ass.events if e.style == "Default")


def test_burn_command_uses_only_relative_paths(tmp_path):
    cmd = caption_render.burn_command("ffmpeg", tmp_path / "v.mp4", "captions.ass", ".caption-fonts", tmp_path / "o.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "subtitles=captions.ass:fontsdir=.caption-fonts"
    assert cmd[0] == "ffmpeg" and str(tmp_path / "o.mp4") == cmd[-1]


def test_prepare_fonts_has_only_the_chosen_file(tmp_path):
    name = caption_render.prepare_fonts("montserrat", tmp_path)
    assert str(name) == ".caption-fonts"
    assert [p.name for p in (tmp_path / name).iterdir()] == ["Montserrat-ExtraBold.ttf"]
    # switching font leaves only the new one
    caption_render.prepare_fonts("bangers", tmp_path)
    assert [p.name for p in (tmp_path / name).iterdir()] == ["Bangers-Regular.ttf"]


def test_size_factor_gives_every_font_the_same_em():
    assert caption_render.size_factor("montserrat") == pytest.approx(1.562 / 1.192, abs=0.001)
    assert caption_render.size_factor("anton") == pytest.approx(3550 / 2048 / 1.192, abs=0.001)
    assert caption_render.size_factor("nope") == caption_render.size_factor("montserrat")


def test_font_family_is_the_name_libass_matches():
    # legacy family (name ID 1): a static ExtraBold is its own family to libass
    assert caption_render.font_family("montserrat") == "Montserrat ExtraBold"
    assert caption_render.font_family("poppins") == "Poppins ExtraBold"
    assert caption_render.font_family("bebas") == "Bebas Neue"
    assert caption_render.font_family("nope") == "Montserrat ExtraBold"  # default font


# ── real burn (needs an ffmpeg with libass) ───────────────────────────────────


def _libass_ffmpeg():
    try:
        return caption_render.resolve_ffmpeg()
    except RuntimeError:
        return None


_FFMPEG = _libass_ffmpeg()


def _prepare(folder, font):
    folder.mkdir(parents=True, exist_ok=True)
    tokens = caption_style.validate({"font": font})
    words = [{"word": "Legenda", "start": 0.0, "end": 1.0}, {"word": "teste", "start": 1.0, "end": 2.0}]
    ass = caption_render.build_ass(caption_render.group_words(words, 4), tokens, 540, 960)
    ass.save(str(folder / "captions.ass"))
    return f"subtitles=captions.ass:fontsdir={caption_render.prepare_fonts(font, folder)}"


def _burn_frame(ffmpeg, folder, font):
    vf = _prepare(folder, font)
    out = folder / "frame.png"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=gray:s=540x960:d=1",
         "-vf", vf, "-frames:v", "1", "frame.png"],
        cwd=folder, check=True,
    )
    return out.read_bytes()


@pytest.mark.skipif(_FFMPEG is None, reason="sem ffmpeg com libass")
def test_real_burn_uses_the_chosen_font(tmp_path):
    montserrat = _burn_frame(_FFMPEG, tmp_path / "m", "montserrat")
    bangers = _burn_frame(_FFMPEG, tmp_path / "b", "bangers")
    anton = _burn_frame(_FFMPEG, tmp_path / "a", "anton")
    assert montserrat != bangers
    assert anton != bangers


@pytest.mark.skipif(_FFMPEG is None, reason="sem ffmpeg com libass")
@pytest.mark.parametrize("font,face", [("montserrat", "Montserrat-ExtraBold"), ("poppins", "Poppins-ExtraBold"),
                                       ("bangers", "Bangers-Regular")])
def test_libass_picks_the_app_font_not_a_fallback(tmp_path, font, face):
    vf = _prepare(tmp_path, font)
    log = subprocess.run(
        [_FFMPEG, "-v", "debug", "-f", "lavfi", "-i", "color=gray:s=540x960:d=1",
         "-vf", vf, "-frames:v", "1", "-f", "null", "-"],
        cwd=tmp_path, capture_output=True, text=True,
    ).stderr
    picked = [line for line in log.splitlines() if "fontselect:" in line]
    assert picked and all(f"-> {face}," in line for line in picked), picked


def test_background_and_box_highlight_get_their_own_layers():
    # libass pushes apart overlapping events on the same layer
    c = caption_style.validate({"background": "box", "highlight_mode": "box"})
    ass = caption_render.build_ass([[W1, W2]], c, 1080, 1920)
    first = ass.events[:3]
    assert [e.layer for e in first] == [0, 1, 2]
    assert "\\3a&H60&" in first[0].text and "\\3a&H00&" in first[1].text
    assert first[2].style == "Default"


def _cap_height(png: bytes) -> int:
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("L").point(lambda v: 255 if v > 128 else 0)
    box = im.getbbox()
    return box[3] - box[1]


@pytest.mark.skipif(_FFMPEG is None, reason="sem ffmpeg com libass")
def test_default_keeps_todays_caption_size(tmp_path):
    """Old ASS (no PlayRes, "Montserrat" bold → system fallback) vs the new
    default: same cap height within 5%."""
    old = tmp_path / "old"
    old.mkdir()
    (old / "fonts").mkdir()
    (old / "captions.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        "Style: Default,Montserrat,14,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,10,10,95,1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,HHH\n"
    )
    run = [_FFMPEG, "-y", "-v", "debug", "-f", "lavfi", "-i", "color=black:s=540x960:d=1",
           "-vf", "subtitles=captions.ass:fontsdir=fonts", "-frames:v", "1", "frame.png"]
    log = subprocess.run(run, cwd=old, capture_output=True, text=True).stderr
    if "Helvetica-Bold" not in log:
        pytest.skip("fallback do sistema não é a Helvetica Bold")

    new = tmp_path / "new"
    new.mkdir()
    tokens = caption_style.validate({"outline": 0})
    caption_render.build_ass([[{"word": "HHH", "start": 0.0, "end": 5.0}]], tokens, 540, 960).save(
        str(new / "captions.ass"))
    vf = f"subtitles=captions.ass:fontsdir={caption_render.prepare_fonts('montserrat', new)}"
    subprocess.run([_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=540x960:d=1",
                    "-vf", vf, "-frames:v", "1", "frame.png"], cwd=new, check=True)

    before = _cap_height((old / "frame.png").read_bytes())
    after = _cap_height((new / "frame.png").read_bytes())
    assert after == pytest.approx(before, rel=0.05), (before, after)
