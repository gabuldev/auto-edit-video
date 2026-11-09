"""A/B/C da thumbnail no app: o Resultado lista as variações e a escolhida é
a que vai junto no upload do YouTube."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_edit import api, engine
from auto_edit.publish import youtube as yt


def _ws(root: Path, *, variants=("A", "B", "C"), vtype="long", metadata=None) -> Path:
    ws = root / "vid"
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({
        "video_name": "vid", "type": vtype, "language": "pt", "current_stage": "done",
        "created_at": "2026-01-01T00:00:00+00:00", "stages": {},
    }))
    if metadata is None:
        metadata = {
            "youtube_title": "Título",
            "thumbnail_variants": [
                {"id": "A", "layout": "atual (estilo ativo)", "file": "thumbnail.png", "qa": "aprovada"},
                {"id": "B", "layout": "rosto à esquerda, texto à direita", "file": "thumbnail_b.png",
                 "qa": "reprovada", "qa_reasons": ["texto sobre o rosto"]},
                {"id": "C", "layout": "objeto em destaque, rosto menor", "file": "thumbnail_c.png", "qa": "aprovada"},
            ],
        }
    (ws / "metadata.json").write_text(json.dumps(metadata))
    out = root / "output"
    out.mkdir(exist_ok=True)
    (out / "vid_final.mp4").write_bytes(b"\0" * 2048)
    names = {"A": "vid_thumbnail.png", "B": "vid_thumbnail_b.png", "C": "vid_thumbnail_c.png"}
    for v in variants:
        (out / names[v]).write_bytes(b"png")
    return ws


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    return tmp_path


def test_result_lists_variants_with_qa_and_a_chosen_by_default(lib):
    _ws(lib)
    thumbs = engine.result("vid")["thumbnails"]
    assert [t["id"] for t in thumbs] == ["A", "B", "C"]
    assert [t["kind"] for t in thumbs] == ["thumbnail", "thumbnail_b", "thumbnail_c"]
    assert thumbs[1]["qa"] == "reprovada" and thumbs[1]["qa_reasons"] == ["texto sobre o rosto"]
    assert [t["chosen"] for t in thumbs] == [True, False, False]


def test_only_files_that_exist_are_listed(lib):
    _ws(lib, variants=("A", "C"))  # B reprovou e foi descartada
    assert [t["id"] for t in engine.thumbnail_options("vid")] == ["A", "C"]


def test_old_workspace_without_variants_has_just_a(lib):
    _ws(lib, variants=("A",), metadata={"youtube_title": "T"})
    thumbs = engine.thumbnail_options("vid")
    assert len(thumbs) == 1 and thumbs[0]["id"] == "A" and thumbs[0]["chosen"]
    assert thumbs[0]["layout"]  # cai no rótulo padrão


def test_choice_is_saved_and_survives(lib):
    ws = _ws(lib)
    thumbs = engine.set_thumbnail_choice("vid", "c")
    assert [t["chosen"] for t in thumbs] == [False, False, True]
    assert json.loads((ws / "pipeline.json").read_text())["thumbnail_choice"] == "C"
    assert engine.chosen_thumbnail("vid") == "C"


def test_choice_of_missing_file_is_refused(lib):
    _ws(lib, variants=("A", "B"))
    with pytest.raises(ValueError):
        engine.set_thumbnail_choice("vid", "C")
    with pytest.raises(ValueError):
        engine.set_thumbnail_choice("vid", "Z")
    with pytest.raises(FileNotFoundError):
        engine.set_thumbnail_choice("nope", "A")


def test_choice_whose_file_vanished_falls_back_to_a(lib):
    _ws(lib)
    engine.set_thumbnail_choice("vid", "B")
    (lib / "output" / "vid_thumbnail_b.png").unlink()
    assert engine.chosen_thumbnail("vid") == "A"


def test_publish_state_says_which_goes(lib):
    _ws(lib)
    engine.set_thumbnail_choice("vid", "B")
    st = engine.publish_state("vid")
    assert st["thumbnail"] is True and st["thumbnail_variant"] == "B"


def test_short_has_no_thumbnail_variant(lib):
    _ws(lib, vtype="short", variants=("A",))
    st = engine.publish_state("vid")
    assert st["thumbnail"] is False and st["thumbnail_variant"] is None


def test_publish_job_uploads_the_chosen_one(lib, monkeypatch):
    _ws(lib)
    engine.set_thumbnail_choice("vid", "C")
    monkeypatch.setattr(yt, "is_connected", lambda: True)
    seen = {}

    def fake_run(ws, body, *, video, thumbnail, emit, **_):
        seen["thumbnail"] = thumbnail

    monkeypatch.setattr(engine, "run_publish_youtube", fake_run)
    mgr = engine.JobManager()
    monkeypatch.setattr(mgr, "_spawn", lambda vid, kind, target: target(lambda e: None))
    mgr.publish_youtube("vid", {"title": "T"})
    assert seen["thumbnail"] == lib / "output" / "vid_thumbnail_c.png"


def test_api_put_thumbnail(lib):
    _ws(lib)
    client = api.create_app().test_client()
    r = client.put("/api/videos/vid/thumbnail", json={"variant": "B"})
    assert r.status_code == 200
    assert [t["chosen"] for t in r.get_json()["thumbnails"]] == [False, True, False]
    assert client.put("/api/videos/vid/thumbnail", json={"variant": "X"}).status_code == 400
    assert client.put("/api/videos/nope/thumbnail", json={"variant": "A"}).status_code == 404
    assert client.get("/api/videos/vid/file/thumbnail_c").status_code == 200
