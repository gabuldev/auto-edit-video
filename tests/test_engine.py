"""Tests for auto_edit.engine — the headless facade over the pipeline.

Covers the pure read models (status derivation, library scan, detail), the
in-memory job/event plumbing, and run_workspace's event emission with an
injected fake process. No ffmpeg, ralph.sh, or Flask required.
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import engine
from auto_edit import api


def _mkws(root: Path, wid: str, **over) -> Path:
    ws = root / wid
    ws.mkdir(parents=True)
    data = {
        "video_path": f"/videos/{wid}.mp4",
        "video_name": wid,
        "type": "long",
        "language": "pt",
        "current_stage": "extract",
        "iteration": 1,
        "max_iterations": 3,
        "plan_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "stages": {"extract": {"status": "pending"}},
    }
    data.update(over)
    (ws / "pipeline.json").write_text(json.dumps(data))
    return ws


# ── overall_status ────────────────────────────────────────────────────────────

class TestOverallStatus:
    def test_done(self):
        assert engine.overall_status({"current_stage": "done", "stages": {}}) == "done"

    def test_failed_wins_over_running(self):
        p = {"current_stage": "execute", "stages": {"execute": {"status": "failed"}}}
        assert engine.overall_status(p, active=True) == "failed"

    def test_running_when_active(self):
        p = {"current_stage": "extract", "stages": {"extract": {"status": "pending"}}}
        assert engine.overall_status(p, active=True) == "running"

    def test_running_when_a_stage_is_running(self):
        p = {"current_stage": "plan", "stages": {"plan": {"status": "running"}}}
        assert engine.overall_status(p) == "running"

    def test_idle_otherwise(self):
        p = {"current_stage": "extract", "stages": {"extract": {"status": "pending"}}}
        assert engine.overall_status(p) == "idle"


# ── library / summarize / detail ─────────────────────────────────────────────

class TestLibrary:
    def test_list_sorted_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        _mkws(tmp_path, "old", created_at="2026-01-01T00:00:00+00:00")
        _mkws(tmp_path, "new", created_at="2026-06-01T00:00:00+00:00")
        lib = engine.list_library()
        assert [v["id"] for v in lib] == ["new", "old"]

    def test_active_id_marks_running(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        _mkws(tmp_path, "vid")
        assert engine.list_library()[0]["status"] == "idle"
        assert engine.list_library(active_ids={"vid"})[0]["status"] == "running"

    def test_missing_root_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path / "nope"))
        assert engine.list_library() == []

    def test_detail_includes_plan_and_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        ws = _mkws(tmp_path, "vid", context="tutorial")
        (ws / "reviewed_plan.json").write_text(json.dumps(
            {"kept_segments": [{"start": 0, "end": 5}, {"start": 9, "end": 12}],
             "dropped_blocks": ["intro arrastada"]}
        ))
        (ws / "metadata.json").write_text(json.dumps({"youtube_title": "T"}))
        d = engine.detail("vid")
        assert d["context"] == "tutorial"
        assert d["plan"]["kept_segments"] == 2
        assert d["plan"]["dropped_blocks"] == ["intro arrastada"]
        assert d["metadata"]["youtube_title"] == "T"

    def test_detail_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        assert engine.detail("ghost") is None


# ── Job / event plumbing ──────────────────────────────────────────────────────

class TestJobEvents:
    def test_backlog_then_finished_short_circuits(self):
        job = engine.Job(id="x", video_id="v", kind="edit")
        job.emit({"type": "log", "line": "a"})
        job.emit({"type": "done", "status": "done"})
        job.close()
        got = list(job.subscribe())
        assert [e["type"] for e in got] == ["log", "done"]
        assert job.status == "done"

    def test_error_event_sets_failed(self):
        job = engine.Job(id="x", video_id="v", kind="edit")
        job.emit({"type": "error", "message": "boom"})
        assert job.status == "failed"

    def test_live_delivery_to_subscriber(self):
        job = engine.Job(id="x", video_id="v", kind="edit")
        collected: list[dict] = []
        ready = threading.Event()

        def consume():
            ready.set()
            for ev in job.subscribe():
                collected.append(ev)

        t = threading.Thread(target=consume)
        t.start()
        ready.wait(1)
        time.sleep(0.05)  # let subscribe register before we emit
        job.emit({"type": "log", "line": "live"})
        job.emit({"type": "done"})
        job.close()
        t.join(2)
        assert {"type": "log", "line": "live"} in collected


class TestJobManager:
    def test_spawn_tracks_and_completes(self):
        mgr = engine.JobManager()
        release = threading.Event()

        def target(emit):
            emit({"type": "log", "line": "hi"})
            release.wait(1)

        job = mgr._spawn("vid", "edit", target)
        assert mgr.get(job.id) is job
        assert mgr.job_for_video("vid") is job
        assert "vid" in mgr.active_ids()
        release.set()
        for _ in range(100):
            if not mgr.active_ids():
                break
            time.sleep(0.01)
        assert mgr.active_ids() == set()
        assert job.status == "done"  # auto-emitted on clean finish


# ── run_workspace ─────────────────────────────────────────────────────────────

class _FakeProc:
    def __init__(self, lines, rc, ws=None, flip_to=None):
        self._it = iter(lines)
        self._rc = rc
        self._ws = ws
        self._flip_to = flip_to
        self.stdout = self._gen(lines)

    def _gen(self, lines):
        for i, ln in enumerate(lines):
            if i == 1 and self._ws and self._flip_to:
                p = json.loads((self._ws / "pipeline.json").read_text())
                p["current_stage"] = self._flip_to
                (self._ws / "pipeline.json").write_text(json.dumps(p))
            yield ln

    def wait(self):
        return self._rc


class TestRunWorkspace:
    def test_emits_log_stage_and_done(self, tmp_path, monkeypatch):
        ws = _mkws(tmp_path, "vid", current_stage="extract")
        ralph = tmp_path / "ralph.sh"
        ralph.write_text("#!/bin/bash\n")
        monkeypatch.setattr(engine, "ralph_path", lambda: ralph)

        def fake_popen(*a, **k):
            return _FakeProc(["extract go\n", "plan go\n"], 0, ws=ws, flip_to="plan")

        evs: list[dict] = []
        rc = engine.run_workspace(ws, emit=evs.append, popen=fake_popen)
        types = [e["type"] for e in evs]
        assert rc == 0
        assert types.count("log") == 2
        assert "stage" in types
        stages = [e["stage"] for e in evs if e["type"] == "stage"]
        assert "extract" in stages and "plan" in stages
        assert evs[-1]["type"] == "done"

    def test_nonzero_rc_emits_error(self, tmp_path, monkeypatch):
        ws = _mkws(tmp_path, "vid")
        ralph = tmp_path / "ralph.sh"
        ralph.write_text("#!/bin/bash\n")
        monkeypatch.setattr(engine, "ralph_path", lambda: ralph)
        monkeypatch.setattr(engine, "_current_stage", lambda w: "execute")

        def fake_popen(*a, **k):
            return _FakeProc(["boom\n"], 1)

        evs: list[dict] = []
        rc = engine.run_workspace(ws, emit=evs.append, popen=fake_popen)
        assert rc == 1
        assert evs[-1]["type"] == "error"
        assert evs[-1]["stage"] == "execute"

    def test_missing_ralph_errors(self, tmp_path, monkeypatch):
        ws = _mkws(tmp_path, "vid")
        monkeypatch.setattr(engine, "ralph_path", lambda: tmp_path / "nope.sh")
        evs: list[dict] = []
        rc = engine.run_workspace(ws, emit=evs.append, popen=lambda *a, **k: None)
        assert rc == 1
        assert len(evs) == 1 and evs[0]["type"] == "error"


# ── api._sse (pure) ───────────────────────────────────────────────────────────

def test_sse_formats_events():
    out = list(api._sse([{"type": "log", "line": "x"}, {"type": "done"}]))
    assert out[0] == 'data: {"type": "log", "line": "x"}\n\n'
    assert out[1] == 'data: {"type": "done"}\n\n'
