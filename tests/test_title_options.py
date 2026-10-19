"""Títulos alternativos e próximo vídeo (tela final) que o metadata gera."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_edit import engine, pipeline, runner
from auto_edit.insights import service as isvc
from auto_edit.insights import store as ist
from tests.test_publish_youtube import _done_ws, lib  # noqa: F401 (fixture)
from tools.overlayer import END_SCREEN_SEC, _outside_end_screen


class TestTitleOptions:
    def test_main_title_first_then_alternatives(self):
        meta = {"youtube_title": "A", "title_options": ["A", "B", "C"]}
        assert pipeline.title_options(meta) == ["A", "B", "C"]

    def test_dedupes_blanks_and_caps_at_three(self):
        meta = {"youtube_title": "Título", "title_options": ["título", "", None, "B", "C", "D"]}
        assert pipeline.title_options(meta) == ["Título", "B", "C"]

    def test_old_metadata_without_options(self):
        assert pipeline.title_options({"youtube_title": "T"}) == ["T"]
        assert pipeline.title_options(None) == []


class TestNextVideo:
    def test_needs_a_url(self):
        assert pipeline.next_video({"next_video": {"title": "X"}}) is None
        assert pipeline.next_video({"next_video": None}) is None
        assert pipeline.next_video({}) is None

    def test_cleans_fields(self):
        nv = pipeline.next_video({"next_video": {"title": " X ", "url": "https://youtu.be/a"}})
        assert nv == {"title": "X", "url": "https://youtu.be/a", "reason": ""}


def test_metadata_txt_lists_alternatives_and_next_video(tmp_path):
    txt = tmp_path / "m.txt"
    pipeline._write_metadata_txt(txt, {
        "youtube_title": "A", "title_options": ["A", "B"],
        "next_video": {"title": "Outro", "url": "https://youtu.be/x", "reason": "continua"},
    }, "long")
    out = txt.read_text(encoding="utf-8")
    assert "TÍTULOS ALTERNATIVOS" in out and "- B" in out
    assert "- A" not in out  # o principal já está em TÍTULO
    assert "PRÓXIMO VÍDEO" in out and "Outro — https://youtu.be/x" in out


def test_metadata_txt_without_extras(tmp_path):
    txt = tmp_path / "m.txt"
    pipeline._write_metadata_txt(txt, {"youtube_title": "A"}, "long")
    out = txt.read_text(encoding="utf-8")
    assert "ALTERNATIVOS" not in out and "PRÓXIMO VÍDEO" not in out


def test_publish_state_carries_options_and_next_video(lib):  # noqa: F811
    _done_ws(lib, metadata={
        "youtube_title": "A", "title_options": ["A", "B"], "youtube_description": "", "tags": [],
        "next_video": {"title": "Outro", "url": "https://youtu.be/x"},
    })
    st = engine.publish_state("vid")
    assert st["title_options"] == ["A", "B"]
    assert st["next_video"]["url"] == "https://youtu.be/x"


def _seed(tmp_path, monkeypatch):
    from auto_edit import config as cfg

    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    conn = ist.connect(cfg.insights_db_path())
    for vid, title, when, dur in [
        ("l1", "Velho", "2026-01-01", 600), ("l2", "Novo", "2026-09-01", 700),
        ("s1", "Short", "2026-09-02", 30),
    ]:
        ist.upsert_video(conn, "youtube", vid, title=title, url=f"https://youtu.be/{vid}",
                         thumbnail_url="t", published_at=when, duration_sec=dur)
        ist.add_snapshot(conn, "youtube", vid, {"avg_view_pct": 40.0, "views": 10})
    return conn


def test_channel_videos_newest_first_and_by_kind(tmp_path, monkeypatch):
    conn = _seed(tmp_path, monkeypatch)
    lines = isvc.channel_videos(conn, kind="long").splitlines()
    assert len(lines) == 2
    assert '"Novo"' in lines[0] and "https://youtu.be/l2" in lines[0]
    assert '"Velho"' in lines[1]


def test_metadata_prompt_lists_channel_videos_for_long(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch).close()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c"}), encoding="utf-8")
    (ws / "transcription.json").write_text(json.dumps(
        {"duration": 60.0, "segments": [{"start": 0.0, "end": 2.0, "text": "oi"}]}), encoding="utf-8")
    prompt = runner.build_prompt("metadata", ws, Path("agents/metadata.md"))
    assert "## Vídeos do canal" in prompt and "https://youtu.be/l2" in prompt
    assert "youtu.be/s1" not in prompt


def test_metadata_prompt_without_insights_has_no_channel_section(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c"}), encoding="utf-8")
    (ws / "transcription.json").write_text(json.dumps(
        {"duration": 60.0, "segments": [{"start": 0.0, "end": 2.0, "text": "oi"}]}), encoding="utf-8")
    prompt = runner.build_prompt("metadata", ws, Path("agents/metadata.md"))
    assert "## Vídeos do canal" not in prompt


class TestEndScreen:
    def _f(self, start):
        return ({"overlay": "cta"}, "cta", None, start)

    def test_drops_overlays_in_the_last_seconds(self):
        kept, dropped = _outside_end_screen([self._f(10.0), self._f(100.0 - END_SCREEN_SEC + 1)], 100.0)
        assert [f[3] for f in kept] == [10.0]
        assert len(dropped) == 1

    def test_short_video_has_no_end_screen(self):
        kept, dropped = _outside_end_screen([self._f(15.0)], 20.0)
        assert len(kept) == 1 and not dropped

    @pytest.mark.parametrize("start", [0.0, 79.9])
    def test_keeps_before_the_zone(self, start):
        kept, _ = _outside_end_screen([self._f(start)], 100.0)
        assert len(kept) == 1
