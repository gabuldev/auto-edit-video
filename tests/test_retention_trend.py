"""A retenção melhorando: vídeos analisados em ordem de publicação, antigos vs
recentes, e planejados com vs sem as lições de retenção."""
from __future__ import annotations

import json
from pathlib import Path

from auto_edit import api, engine, retention as ret, runner


def _video(root: Path, wid: str, *, when: str, at_30s: float, kind="long", lessons=None, title=None):
    ws = root / wid
    ws.mkdir(parents=True)
    p = {"type": kind, "created_at": when, "stages": {}}
    if lessons is not None:
        p[ret.LESSONS_KEY] = lessons
    (ws / "pipeline.json").write_text(json.dumps(p))
    (ws / "metadata.json").write_text(json.dumps({"youtube_title": title or wid}))
    (ws / "publish.json").write_text(json.dumps({"youtube": [{"video_id": wid, "published_at": when}]}))
    (ws / ret.RETENTION_NAME).write_text(json.dumps({
        "video_id": wid, "duration": 600, "at_30s": at_30s, "at_60s": at_30s - 0.1,
        "at_half": 0.3, "relative_median": 0.5, "drops": [{"start": 40}],
    }))
    return ws


def _channel(root):
    _video(root, "v1", when="2026-01-01", at_30s=0.50)
    _video(root, "v2", when="2026-02-01", at_30s=0.52)
    _video(root, "v3", when="2026-03-01", at_30s=0.60, lessons=2)
    _video(root, "v4", when="2026-04-01", at_30s=0.62, lessons=3)
    _video(root, "s1", when="2026-03-15", at_30s=0.8, kind="short")


def test_trend_orders_by_publication_and_compares(tmp_path):
    _channel(tmp_path)
    data = ret.trend(tmp_path, "long")
    assert [r["id"] for r in data["videos"]] == ["v1", "v2", "v3", "v4"]
    s = data["summary"]["long"]
    assert s["count"] == 4
    assert s["older_vs_newer"]["at_30s"] == {"before": 0.51, "after": 0.61, "delta": 0.1}
    assert s["with_vs_without_lessons"]["with"] == 2
    assert s["with_vs_without_lessons"]["at_30s"]["delta"] == 0.1
    assert "short" not in data["summary"]
    assert set(ret.trend(tmp_path)["summary"]) == {"long", "short"}


def test_single_video_has_no_comparison(tmp_path):
    _video(tmp_path, "v1", when="2026-01-01", at_30s=0.5)
    s = ret.trend(tmp_path)["summary"]["long"]
    assert s == {"count": 1}


def test_versus_previous(tmp_path):
    _channel(tmp_path)
    vp = ret.versus_previous(tmp_path, tmp_path / "v3")
    assert vp["previous"] == 2 and vp["lessons"] == 2
    assert vp["at_30s"]["before"] == 0.51 and vp["at_30s"]["after"] == 0.6
    assert ret.versus_previous(tmp_path, tmp_path / "v1") is None


def test_format_trend(tmp_path):
    assert "Nenhum vídeo" in ret.format_trend(ret.trend(tmp_path))
    _channel(tmp_path)
    text = ret.format_trend(ret.trend(tmp_path, "long"))
    assert "51% → 61% (+10.0 pp)" in text
    assert "com as lições de retenção (2) vs sem (2)" in text
    assert "com lições" in text


def test_runner_records_how_many_lessons_the_plan_saw(tmp_path):
    ws = tmp_path / "new"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "stages": {}}))
    runner._note_lessons(ws, '### "A" — aos 30s\n- x\n### "B" — aos 30s\n- y')
    assert json.loads((ws / "pipeline.json").read_text())[ret.LESSONS_KEY] == 2
    runner._note_lessons(ws, "")
    assert json.loads((ws / "pipeline.json").read_text())[ret.LESSONS_KEY] == 0


def test_engine_and_api(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    _channel(tmp_path)
    c = api.create_app().test_client()
    r = c.get("/api/insights/trend?type=long")
    assert r.status_code == 200 and len(r.get_json()["videos"]) == 4
    assert c.get("/api/insights/trend?type=x").status_code == 400
    st = engine.retention_state("v4")
    assert st["versus_previous"]["previous"] == 3
