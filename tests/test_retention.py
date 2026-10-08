"""Retention curve → where viewers left, with what was said; the workspace
file; the planner's prompt block; and the engine/API around it."""
import json
from pathlib import Path

import pytest

from auto_edit import api, engine, retention, runner
from auto_edit.insights.youtube import parse_retention

DURATION = 200.0


def _points(cliff_at=None, cliff=0.0):
    """Linear decay from 1.0 to 0.5 over the video, plus an optional cliff."""
    pts = []
    for i in range(1, 101):
        r = i / 100
        w = 1.0 - 0.5 * r
        if cliff_at is not None and r * DURATION >= cliff_at:
            w -= cliff
        pts.append({"ratio": r, "watch": round(w, 4), "relative": 0.5})
    return pts


TRANSCRIPT = {
    "duration": DURATION,
    "segments": [
        {"start": 0.0, "end": 5.0, "text": "Olha o resultado"},
        {"start": 46.0, "end": 52.0, "text": "Para quem não me conhece, eu sou dev"},
        {"start": 120.0, "end": 125.0, "text": "O teste final"},
    ],
}


class TestCurve:
    def test_to_seconds_and_interpolation(self):
        curve = retention.to_seconds([{"ratio": 0.5, "watch": 0.6}, {"ratio": 0.25, "watch": 0.8}], 100)
        assert curve == [(25.0, 0.8), (50.0, 0.6)]
        assert retention.watch_at(curve, 37.5) == pytest.approx(0.7)
        assert retention.watch_at(curve, 0) == 0.8
        assert retention.watch_at(curve, 99) == 0.6

    def test_steady_decay_has_no_drops(self):
        curve = retention.to_seconds(_points(), DURATION)
        assert retention.find_drops(curve) == []

    def test_cliff_is_found_where_it_happens(self):
        curve = retention.to_seconds(_points(cliff_at=50, cliff=0.15), DURATION)
        drops = retention.find_drops(curve)
        assert len(drops) == 1
        assert 40 <= drops[0]["start"] <= 50 <= drops[0]["end"]
        assert drops[0]["excess"] >= 0.1

    def test_drops_do_not_overlap_and_are_in_time_order(self):
        pts = _points(cliff_at=50, cliff=0.1)
        for p in pts:
            if p["ratio"] * DURATION >= 150:
                p["watch"] -= 0.08
        drops = retention.find_drops(retention.to_seconds(pts, DURATION))
        assert [d["start"] for d in drops] == sorted(d["start"] for d in drops)
        assert len(drops) == 2
        assert drops[1]["start"] - drops[0]["start"] >= retention.DROP_WINDOW


class TestAnalyze:
    def test_drop_carries_what_was_said_and_its_kind(self):
        data = retention.analyze(_points(cliff_at=50, cliff=0.15), DURATION, TRANSCRIPT)
        drop = data["drops"][0]
        assert "não me conhece" in drop["text"]
        assert drop["preamble"] == "apresentação"
        assert data["at_30s"] == pytest.approx(1.0 - 0.5 * 30 / DURATION, abs=0.01)
        assert data["at_half"] is not None and data["relative_median"] == 0.5
        assert len(data["curve"]) == 100

    def test_parse_retention_rows(self):
        headers = [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}, {"name": "relativeRetentionPerformance"}]
        assert parse_retention(headers, [[0.01, 1.2, 0.6]]) == [{"ratio": 0.01, "watch": 1.2, "relative": 0.6}]
        assert parse_retention([{"name": "x"}], [[1]]) == []


def _ws(root: Path, wid="vid", vtype="long", published=True, title="Meu vídeo"):
    ws = root / wid
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({"video_name": wid, "type": vtype, "current_stage": "done", "stages": {}}))
    (ws / "post_cut_transcription.json").write_text(json.dumps(TRANSCRIPT))
    (ws / "metadata.json").write_text(json.dumps({"youtube_title": title}))
    if published:
        (ws / "publish.json").write_text(json.dumps({"youtube": [{"video_id": "old"}, {"video_id": "abc"}]}))
    return ws


class TestRefresh:
    def test_saves_the_analysis_of_the_last_upload(self, tmp_path):
        ws = _ws(tmp_path)
        asked = []
        data = retention.refresh(ws, lambda vid: asked.append(vid) or _points(cliff_at=50, cliff=0.15))
        assert asked == ["abc"]
        assert data["video_id"] == "abc"
        assert retention.load(ws)["drops"][0]["preamble"] == "apresentação"

    def test_not_published(self, tmp_path):
        with pytest.raises(retention.RetentionError, match="URL"):
            retention.refresh(_ws(tmp_path, published=False), lambda vid: [])

    def test_explicit_id_wins(self, tmp_path):
        asked = []
        retention.refresh(_ws(tmp_path, published=False), lambda vid: asked.append(vid) or _points(), video_id="xyz")
        assert asked == ["xyz"]

    def test_no_curve_yet(self, tmp_path):
        with pytest.raises(retention.RetentionError, match="24–48h"):
            retention.refresh(_ws(tmp_path), lambda vid: [])


class TestLessons:
    def test_block_for_the_planner(self, tmp_path):
        ws = _ws(tmp_path, "a", title="Vídeo da interface")
        retention.refresh(ws, lambda vid: _points(cliff_at=50, cliff=0.15))
        short = _ws(tmp_path, "b", vtype="short")
        retention.refresh(short, lambda vid: _points(cliff_at=50, cliff=0.15))

        block = retention.lessons(tmp_path, "long")
        assert '"Vídeo da interface"' in block
        assert "[apresentação]" in block and "não me conhece" in block
        assert block.count("###") == 1  # the short is not a lesson for a long

    def test_empty_without_data(self, tmp_path):
        _ws(tmp_path)
        assert retention.lessons(tmp_path, "long") == ""

    def test_plan_prompt_carries_it(self, tmp_path):
        retention.refresh(_ws(tmp_path, "old"), lambda vid: _points(cliff_at=50, cliff=0.15))
        new = tmp_path / "new"
        new.mkdir()
        (new / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c", "stages": {}}))
        (new / "transcription.json").write_text(json.dumps({"duration": 10, "segments": [], "words": []}))
        prompt = runner.build_prompt("plan", new, Path("agents/planner.md"))
        assert "Onde o público saiu nos teus vídeos recentes" in prompt
        assert "não me conhece" in prompt


class TestEngineAndApi:
    @pytest.fixture
    def lib(self, tmp_path, monkeypatch):
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
        return tmp_path

    def test_state_and_refresh(self, lib):
        _ws(lib)
        assert engine.retention_state("vid")["data"] is None
        st = engine.refresh_retention("vid", fetch=lambda vid: _points(cliff_at=50, cliff=0.15))
        assert st["youtube_id"] == "abc" and st["data"]["drops"]
        assert engine.retention_state("nope") is None

    def test_api(self, lib):
        pytest.importorskip("flask")
        _ws(lib, published=False)
        client = api.create_app(engine.JobManager()).test_client()
        assert client.get("/api/videos/vid/retention").get_json()["youtube_id"] is None
        assert client.get("/api/videos/nope/retention").status_code == 404
        r = client.post("/api/videos/vid/retention")
        assert r.status_code == 400  # not connected / not published: shown, not a 500


def test_steep_natural_start_is_not_a_drop():
    """Everyone loses viewers fast at first; only flag it when YouTube says the
    video is worse than similar ones there."""
    import math

    def pts(rel):
        return [{"ratio": i / 100, "watch": 0.4 + 0.6 * math.exp(-(i / 100 * DURATION) / 15), "relative": rel}
                for i in range(1, 101)]

    good = retention.analyze(pts(0.6), DURATION, TRANSCRIPT)
    assert all(d["start"] >= retention.EARLY for d in good["drops"])
    bad = retention.analyze(pts(0.3), DURATION, TRANSCRIPT)
    assert any(d["start"] < retention.EARLY for d in bad["drops"])


def test_hand_published_video_keeps_its_id(tmp_path):
    """Published outside auto-edit: the --url id is remembered for the next refresh."""
    ws = _ws(tmp_path, published=False)
    retention.refresh(ws, lambda vid: _points(), video_id="manual1")
    assert retention.youtube_id(ws) == "manual1"
    asked = []
    retention.refresh(ws, lambda vid: asked.append(vid) or _points())
    assert asked == ["manual1"]
