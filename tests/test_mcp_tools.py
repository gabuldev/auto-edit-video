"""As ferramentas do MCP que deixam o Claude dirigir o motor pela conversa."""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.fastmcp")

from auto_edit import effects as fx, engine, mcp_server as m  # noqa: E402
from auto_edit.publish import youtube as yt  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    ws = tmp_path / "vid"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({
        "video_path": str(tmp_path / "orig.mp4"), "video_name": "vid", "type": "long",
        "language": "pt", "current_stage": "done", "stages": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }))
    (ws / "reviewed_plan.json").write_text(json.dumps({
        "kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}))
    (ws / "transcription.json").write_text(json.dumps({"duration": 40, "segments": [
        {"start": 1, "end": 4, "text": "fala do começo"},
        {"start": 21, "end": 24, "text": "fala depois do corte"},
    ]}))
    (ws / "applied_intervals.json").write_text(json.dumps(
        {"intervals": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}))
    return tmp_path


def test_every_new_tool_is_registered():
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert {
        "list_videos", "get_plan", "cut_section", "update_plan", "rerender", "list_effects",
        "add_zoom", "add_broll", "remove_effect", "adjust_captions", "publish_info",
        "publish_youtube", "retention", "retention_trend",
    } <= names


def test_get_plan_shows_original_and_edited_times(lib):
    out = m.get_plan("vid")
    assert "[1] 0:20.0–0:30.0 → 0:10.0–0:20.0: fala depois do corte" in out


def test_video_by_original_path(lib):
    assert "fala do começo" in m.get_plan(str(lib / "orig.mp4"))
    assert m.get_plan("nada").startswith("Erro:")


def test_cut_section_without_rerender(lib, monkeypatch):
    monkeypatch.setattr(m, "_run_ralph", lambda *a, **k: pytest.fail("não devia renderizar"))
    out = m.cut_section("vid", 12, 14)
    assert "original 0:22.0–0:24.0" in out and "rerender" in out


def test_cut_section_with_rerender_resumes_from_execute(lib, monkeypatch):
    seen = {}
    monkeypatch.setattr(m, "_run_ralph", lambda ws, **k: seen.setdefault("stage", json.loads(
        (ws / "pipeline.json").read_text())["current_stage"]) and "ok")
    m.cut_section("vid", 12, 14, rerender=True)
    assert seen["stage"] == "execute"


def test_zoom_and_errors_come_back_as_text(lib):
    out = m.add_zoom("vid", 12, 15, scale=1.3)
    assert "zoom 1.3x · no editado 0:12.0–0:15.0" in out
    assert fx.load(lib / "vid")[0]["start"] == 22.0
    assert m.add_zoom("vid", 12, 15).startswith("Erro: já tem um zoom")
    assert m.add_broll("vid", 1, 3, "nao-existe.png").startswith("Erro:")
    assert "Nenhum efeito" in m.remove_effect("vid")


def test_rerender_rejects_unknown_stage(lib):
    assert m.rerender("vid", "nope").startswith("Erro")


def test_publish_youtube_uses_defaults_and_chosen_thumbnail(lib, monkeypatch):
    out_dir = lib / "output"
    out_dir.mkdir()
    (out_dir / "vid_final.mp4").write_bytes(b"\0" * 1024)
    (out_dir / "vid_thumbnail.png").write_bytes(b"a")
    (out_dir / "vid_thumbnail_b.png").write_bytes(b"b")
    (lib / "vid" / "metadata.json").write_text(json.dumps(
        {"youtube_title": "Título bom", "youtube_description": "Desc", "tags": ["x"]}))
    monkeypatch.setattr(yt, "is_connected", lambda: True)
    seen = {}

    def fake_run(ws, body, *, video, thumbnail, emit, **_):
        seen["title"], seen["thumb"] = body["snippet"]["title"], thumbnail
        return {"url": "https://youtu.be/x", "privacy": body["status"]["privacyStatus"], "warnings": []}

    monkeypatch.setattr(engine, "run_publish_youtube", fake_run)
    out = m.publish_youtube("vid", privacy="unlisted", thumbnail="B")
    assert out == "Enviado: https://youtu.be/x (unlisted)"
    assert seen == {"title": "Título bom", "thumb": out_dir / "vid_thumbnail_b.png"}


def test_publish_youtube_not_connected(lib, monkeypatch):
    (lib / "output").mkdir()
    (lib / "output" / "vid_final.mp4").write_bytes(b"\0")
    monkeypatch.setattr(yt, "is_connected", lambda: False)
    assert m.publish_youtube("vid").startswith("Erro ao publicar")


def test_retention_trend_tool(lib):
    assert "Nenhum vídeo" in m.retention_trend()
    assert m.retention_trend("x").startswith("Erro")
