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


# --- estilo gravado no vídeo quando a edição começa -------------------------

import json  # noqa: E402

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from auto_edit import cli, settings, shorts, workspace  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path / "ws"))
    return tmp_path / "home"


def _video(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_text("")
    return v


def _recorded(ws):
    return json.loads((ws / "pipeline.json").read_text())["captions"]


def test_new_workspace_records_active_style_captions(home, tmp_path):
    settings.save({**settings.load(), "style": "neon"})
    ws = workspace.init_workspace(_video(tmp_path), "short", "c")
    expected = caption_style.validate(styles.PRESETS["neon"]["tokens"]["captions"])
    assert _recorded(ws) == expected


def test_changing_active_style_later_does_not_touch_the_video(home, tmp_path):
    settings.save({**settings.load(), "style": "neon"})
    ws = workspace.init_workspace(_video(tmp_path), "short", "c")
    before = _recorded(ws)
    settings.save({**settings.load(), "style": "padrao"})
    assert _recorded(ws) == before


def test_broken_settings_records_default(home, tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("settings quebrado")

    monkeypatch.setattr(styles, "active", boom)
    ws = workspace.init_workspace(_video(tmp_path), "short", "c")
    assert _recorded(ws) == caption_style.DEFAULT


def test_derived_short_inherits_long_captions(home, tmp_path):
    long_ws = tmp_path / "L"
    long_ws.mkdir()
    (long_ws / "edited_video.mp4").write_text("")
    (long_ws / "post_cut_transcription.json").write_text(json.dumps({
        "duration": 60, "segments": [],
        "words": [{"word": "a", "start": 1.0, "end": 2.0}, {"word": "b", "start": 2.0, "end": 30.0}],
    }))
    cap = caption_style.validate({"font": "anton", "size": 120})
    lp = {"type": "long", "video_name": "L", "captions": cap, "context": "x"}
    ws = shorts.seed_short_workspace(long_ws, lp, {"start": 1.0, "end": 30.0, "hook": "h"}, 1)
    assert _recorded(ws) == cap


def _cli_style(monkeypatch, tmp_path, args):
    seen = {}
    monkeypatch.setattr(cli, "_run_pipeline", lambda *a, **k: seen.update(style=a[6]))
    r = CliRunner().invoke(cli.app, ["short", str(_video(tmp_path)), "-c", "x", "--plan-id", "none", *args])
    assert r.exit_code == 0, r.output
    return seen["style"]


def test_cli_short_without_flags_records_empty_caption_style(monkeypatch, tmp_path):
    assert _cli_style(monkeypatch, tmp_path, []) == {}


def test_cli_short_font_size_only_records_that(monkeypatch, tmp_path):
    assert _cli_style(monkeypatch, tmp_path, ["--font-size", "21"]) == {"font_size": 21}
