"""Pedidos livres: zoom / b-roll validados, presos ao tempo do original e
levados pro tempo do vídeo editado; e "tira o trecho X" pelo tempo do editado."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_edit import api, effects as fx, engine


# ── validation ────────────────────────────────────────────────────────────────

def test_zoom_defaults_and_bounds():
    assert fx.clean({"type": "zoom", "start": 1, "end": 3}) == {"type": "zoom", "start": 1.0, "end": 3.0, "scale": 1.2}
    for bad in (
        {"type": "zoom", "start": 3, "end": 1},
        {"type": "zoom", "start": 1, "end": 1.2},           # < 0.5s
        {"type": "zoom", "start": 0, "end": 31},            # > 30s
        {"type": "zoom", "start": 0, "end": 2, "scale": 3},
        {"type": "zoom", "start": -1, "end": 2},
        {"type": "blur", "start": 0, "end": 2},
        {"type": "zoom", "start": "x", "end": 2},
    ):
        with pytest.raises(fx.EffectError):
            fx.clean(bad)


def test_broll_needs_an_existing_media_file(tmp_path):
    img = tmp_path / "tela.png"
    img.write_bytes(b"png")
    out = fx.clean({"type": "broll", "start": 0, "end": 2, "file": "tela.png"}, tmp_path)
    assert out["file"] == str(img)
    with pytest.raises(fx.EffectError, match="não encontrado"):
        fx.clean({"type": "broll", "start": 0, "end": 2, "file": "nada.png"}, tmp_path)
    (tmp_path / "doc.pdf").write_bytes(b"x")
    with pytest.raises(fx.EffectError, match="formato"):
        fx.clean({"type": "broll", "start": 0, "end": 2, "file": "doc.pdf"}, tmp_path)
    with pytest.raises(fx.EffectError):
        fx.clean({"type": "broll", "start": 0, "end": 2})


def test_validate_drops_overlaps_of_the_same_kind_only(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    valid, notes = fx.validate([
        {"type": "zoom", "start": 0, "end": 4},
        {"type": "zoom", "start": 3, "end": 5},             # overlaps the first zoom
        {"type": "broll", "start": 2, "end": 4, "file": str(img)},  # other kind: fine
        {"type": "nope", "start": 0, "end": 1},
    ])
    assert [e["type"] for e in valid] == ["zoom", "broll"]
    assert len(notes) == 2 and "sobrepõe" in notes[0]


# ── timelines ─────────────────────────────────────────────────────────────────

PLAY = [(0.0, 10.0), (20.0, 30.0)]  # 10s cut out between 10 and 20


def test_place_maps_original_to_edited_and_splits_on_a_cut():
    assert fx.place({"start": 22, "end": 25}, PLAY) == [{"t0": 12.0, "t1": 15.0, "src": 0.0}]
    # spans the cut: shows 8–10 and 20–22 of the original, contiguous in the edit
    assert fx.place({"start": 8, "end": 22}, PLAY) == [{"t0": 8.0, "t1": 12.0, "src": 0.0}]
    assert fx.place({"start": 12, "end": 18}, PLAY) == []


def test_place_follows_a_reordered_playback_and_teasers_twice():
    play = [(22.0, 26.0), (0.0, 10.0), (20.0, 30.0)]  # teaser 22–26 first
    windows = fx.place({"start": 23, "end": 25}, play)
    assert windows == [{"t0": 1.0, "t1": 3.0, "src": 0.0}, {"t0": 17.0, "t1": 19.0, "src": 0.0}]


def test_to_original_of_an_edited_window():
    assert fx.to_original(12, 15, PLAY) == [(22.0, 25.0)]
    assert fx.to_original(8, 12, PLAY) == [(8.0, 10.0), (20.0, 22.0)]
    assert fx.to_original(50, 60, PLAY) == []


def test_plan_effects_drops_what_lands_on_a_cut():
    placed, notes = fx.plan_effects(
        [{"type": "zoom", "start": 12, "end": 18, "scale": 1.2},
         {"type": "zoom", "start": 2, "end": 4, "scale": 1.2}], PLAY)
    assert len(placed) == 1 and placed[0]["windows"][0]["t0"] == 2.0
    assert "trecho cortado" in notes[0]


def test_build_command_overlays_each_window(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    placed = [
        {"type": "zoom", "start": 2, "end": 4, "scale": 1.25, "windows": [{"t0": 2.0, "t1": 4.0, "src": 0.0}]},
        {"type": "broll", "start": 5, "end": 7, "file": str(img), "windows": [{"t0": 5.0, "t1": 7.0, "src": 0.0}]},
    ]
    cmd = fx.build_command(tmp_path / "in.mp4", tmp_path / "out.mp4", placed, (1920, 1080), ("libx264", ["-crf", "23"]))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=2.000:end=4.000" in graph and "between(t,2.000,4.000)" in graph
    assert "[1:v]scale=1920:1080" in graph and "between(t,5.000,7.000)" in graph
    assert cmd[cmd.index("-loop") + 1] == "1" and str(img) in cmd
    assert cmd[cmd.index("-map") + 1] == "[v1]"
    assert ["-map", "0:a", "-c:a", "copy"] == cmd[cmd.index("0:a") - 1: cmd.index("0:a") + 3]


# ── apply (in the executor) ───────────────────────────────────────────────────

def _render_ws(root: Path, effects=None) -> Path:
    ws = root / "vid"
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({
        "video_path": str(root / "orig.mp4"), "video_name": "vid", "type": "long",
        "language": "pt", "current_stage": "execute", "stages": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }))
    (ws / "edited_video.mp4").write_bytes(b"cut")
    (ws / "applied_intervals.json").write_text(json.dumps(
        {"intervals": [{"start": s, "end": e} for s, e in PLAY]}))
    if effects is not None:
        fx.save(ws, effects)
    return ws


def test_apply_replaces_the_video_when_ffmpeg_works(tmp_path, monkeypatch):
    from auto_edit import probe

    ws = _render_ws(tmp_path, [{"type": "zoom", "start": 22, "end": 25, "scale": 1.2}])
    monkeypatch.setattr(probe, "video_size", lambda _p: (1280, 720))
    monkeypatch.setattr(probe, "has_audio_stream", lambda _p: True)

    def run(cmd):
        Path(cmd[-1]).write_bytes(b"with fx")
        return SimpleNamespace(returncode=0)

    lines = fx.apply(ws, ("libx264", []), run=run)
    assert (ws / "edited_video.mp4").read_bytes() == b"with fx"
    assert any("zoom 1.2x em 12.0–15.0s" in x for x in lines)


def test_apply_keeps_the_cut_when_ffmpeg_fails(tmp_path, monkeypatch):
    from auto_edit import probe

    ws = _render_ws(tmp_path, [{"type": "zoom", "start": 22, "end": 25}])
    monkeypatch.setattr(probe, "video_size", lambda _p: (1280, 720))
    monkeypatch.setattr(probe, "has_audio_stream", lambda _p: True)
    lines = fx.apply(ws, ("libx264", []), run=lambda cmd: SimpleNamespace(returncode=1))
    assert (ws / "edited_video.mp4").read_bytes() == b"cut"
    assert any("FFmpeg falhou" in x for x in lines)


def test_apply_without_valid_effects_never_runs_ffmpeg(tmp_path):
    ws = _render_ws(tmp_path, [{"type": "zoom", "start": 12, "end": 18}])  # on the cut
    called = []
    lines = fx.apply(ws, ("libx264", []), run=lambda cmd: called.append(cmd))
    assert called == [] and (ws / "edited_video.mp4").read_bytes() == b"cut"
    assert any("trecho cortado" in x for x in lines)
    assert fx.apply(_render_ws(tmp_path / "b"), ("libx264", []), run=lambda c: called.append(c)) == []


# ── engine ────────────────────────────────────────────────────────────────────

@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    ws = _render_ws(tmp_path)
    (ws / "reviewed_plan.json").write_text(json.dumps({
        "kept_segments": [{"start": 0, "end": 10, "summary": "intro"}, {"start": 20, "end": 30}],
        "cuts": [{"start": 10, "end": 20, "reason": "tangente"}],
    }))
    (ws / "transcription.json").write_text(json.dumps({"duration": 40, "segments": []}))
    return tmp_path


def test_add_effect_in_edited_time_is_stored_in_original_time(lib):
    data = engine.add_effect("vid", {"type": "zoom", "start": 12, "end": 15, "scale": 1.3})
    assert fx.load(lib / "vid") == [{"type": "zoom", "start": 22.0, "end": 25.0, "scale": 1.3}]
    assert data["effects"][0]["windows"] == [{"t0": 12.0, "t1": 15.0, "src": 0.0}]
    assert data["rerender_from"] == "execute"


def test_add_broll_across_a_cut_continues_the_clip(lib):
    clip = lib / "broll.mp4"
    clip.write_bytes(b"mp4")
    engine.add_effect("vid", {"type": "broll", "start": 8, "end": 12, "file": "broll.mp4"})
    stored = fx.load(lib / "vid")
    assert [(e["start"], e["end"]) for e in stored] == [(8.0, 10.0), (20.0, 22.0)]
    assert stored[1]["offset"] == 2.0 and stored[0]["file"] == str(clip)


def test_add_effect_refusals(lib):
    with pytest.raises(ValueError, match="fora do vídeo"):
        engine.add_effect("vid", {"type": "zoom", "start": 50, "end": 55})
    with pytest.raises(ValueError, match="cortado"):
        engine.add_effect("vid", {"type": "zoom", "start": 12, "end": 18}, timeline="original")
    engine.add_effect("vid", {"type": "zoom", "start": 1, "end": 3})
    with pytest.raises(ValueError, match="já tem"):
        engine.add_effect("vid", {"type": "zoom", "start": 2, "end": 4})
    with pytest.raises(FileNotFoundError):
        engine.add_effect("nope", {"type": "zoom", "start": 1, "end": 3})


def test_remove_effect(lib):
    engine.add_effect("vid", {"type": "zoom", "start": 1, "end": 3})
    engine.add_effect("vid", {"type": "zoom", "start": 5, "end": 7})
    assert len(engine.remove_effect("vid", 0)["effects"]) == 1
    assert fx.load(lib / "vid")[0]["start"] == 5.0
    with pytest.raises(ValueError):
        engine.remove_effect("vid", 9)
    assert engine.remove_effect("vid")["effects"] == []
    assert not (lib / "vid" / fx.FILE_NAME).exists()


def test_cut_range_in_edited_time(lib):
    # edited 8–12 = original 8–10 and 20–22
    data = engine.cut_range("vid", 8, 12)
    assert [(k["start"], k["end"]) for k in data["kept_segments"]] == [(0.0, 8.0), (22.0, 30.0)]
    assert data["kept_segments"][0]["summary"] == "intro"
    assert data["removed_windows"] == [{"start": 8.0, "end": 10.0}, {"start": 20.0, "end": 22.0}]
    plan = json.loads((lib / "vid" / "reviewed_plan.json").read_text())
    assert plan["cuts"][0]["reason"] == "tangente"  # the rest of the plan stays
    assert (lib / "vid" / "reviewed_plan.agent.json").exists()


def test_cut_range_original_and_refusals(lib):
    data = engine.cut_range("vid", 2, 4, timeline="original")
    assert [(k["start"], k["end"]) for k in data["kept_segments"]] == [(0.0, 2.0), (4.0, 10.0), (20.0, 30.0)]
    with pytest.raises(ValueError):
        engine.cut_range("vid", 0, 100, timeline="original")  # everything
    with pytest.raises(ValueError):
        engine.cut_range("vid", 5, 4)


def test_resolve_video_by_id_and_by_path(lib):
    assert engine.resolve_video("vid") == "vid"
    assert engine.resolve_video(str(lib / "orig.mp4")) == "vid"
    assert engine.resolve_video(str(lib / "other.mp4")) is None
    assert engine.resolve_video("") is None


def test_api_effects_and_cut(lib):
    pytest.importorskip("flask")
    c = api.create_app().test_client()
    r = c.post("/api/videos/vid/effects", json={"type": "zoom", "start": 12, "end": 15})
    assert r.status_code == 200 and len(r.get_json()["effects"]) == 1
    assert c.post("/api/videos/vid/effects", json={"type": "zoom", "start": 50, "end": 55}).status_code == 400
    assert c.get("/api/videos/vid/effects").get_json()["effects"][0]["start"] == 22.0
    assert c.delete("/api/videos/vid/effects/0").get_json()["effects"] == []
    assert c.delete("/api/videos/vid/effects").status_code == 200
    r = c.post("/api/videos/vid/plan/cut", json={"start": 2, "end": 4})
    assert r.status_code == 200 and len(r.get_json()["kept_segments"]) == 3
    assert c.post("/api/videos/vid/plan/cut", json={"start": "a", "end": 4}).status_code == 400
    assert c.get("/api/videos/nope/effects").status_code == 404
