"""Caption tokens: validation, legacy translation and precedence."""
from auto_edit import caption_style, styles


def test_default_is_todays_look():
    assert caption_style.validate(None) == caption_style.DEFAULT


def test_bad_values_fall_back():
    v = caption_style.validate({"position": "left", "offset": 99, "size": "x", "font": "comic", "color": "red", "words": 9, "highlight_mode": "glow"})
    assert v["position"] == "bottom" and v["offset"] == 40 and v["size"] == 100
    assert v["font"] == "montserrat" and v["color"] == "#ffffff" and v["words"] == 4 and v["highlight_mode"] == "outline"


def test_old_cli_caption_style_is_the_default():
    pl = {"caption_style": {"border_highlight": 2.5, "color_highlight": "&H0045FF&", "font_size": 14}}
    assert caption_style.resolve(pl) == caption_style.DEFAULT


def test_legacy_translation():
    out = caption_style.from_legacy({"color_highlight": "&H00FF00&", "font_size": 21, "margin_v": 144, "font_name": "bangers"})
    assert out == {"highlight": "#00ff00", "size": 150, "position": "bottom", "offset": 50, "font": "bangers"}
    assert caption_style.validate(out)["offset"] == 40


def test_precedence_default_style_adjust():
    pl = {"captions": {"font": "anton", "position": "bottom"}, "caption_style": {"position": "top", "offset": 10, "font": "bebas"}}
    r = caption_style.resolve(pl)
    assert r["font"] == "anton"
    assert (r["position"], r["offset"]) == ("top", 10)


def test_no_saved_style_uses_default_not_active(monkeypatch):
    monkeypatch.setattr(styles, "active", lambda: {"tokens": {"captions": {"font": "bangers"}}})
    assert caption_style.resolve({})["font"] == "montserrat"


def test_ass_color():
    assert caption_style.ass_color("#ff4500") == "&H0045FF&"
