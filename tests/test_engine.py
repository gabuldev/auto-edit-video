"""Tests for auto_edit.engine — the headless facade over the pipeline.

Covers the pure read models (status derivation, library scan, detail), the
in-memory job/event plumbing, and run_workspace's event emission with an
injected fake process. No ffmpeg, ralph.sh, or Flask required.
"""
import json
import sys
import threading
import time

import pytest
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

    def test_failed_job_beats_untouched_stages(self):
        """A run that dies before ralph marks anything must not read as idle."""
        p = {"current_stage": "extract", "stages": {"extract": {"status": "pending"}}}
        assert engine.overall_status(p, failed=True) == "failed"

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

    def test_failed_id_marks_failed(self, tmp_path, monkeypatch):
        _mkws(tmp_path, "b")
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        assert engine.list_library(failed_ids={"b"})[0]["status"] == "failed"

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


# ── workspace root (library and start_edit must agree) ────────────────────────

class TestWorkspaceRoot:
    def test_defaults_to_workspace_dir(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_WORKSPACE", raising=False)
        assert engine.library_root() == Path("workspace")

    def test_started_edits_land_where_the_library_looks(self, tmp_path, monkeypatch):
        """Regression: start_edit used a hardcoded ./workspace, so an edit
        started through the API never showed up in the library."""
        from auto_edit import workspace as ws_mod

        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path / "elsewhere"))
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"x")
        ws = ws_mod.init_workspace(video, "short", "ctx")
        assert ws.parent == engine.library_root()
        assert engine.summarize(ws)["id"] == "clip"


class TestJobStatusSets:
    def test_failed_ids_tracks_the_latest_job(self):
        mgr = engine.JobManager()
        done = threading.Event()

        def boom(emit):
            emit({"type": "error", "message": "kaput"})
            done.set()
            return 1

        mgr._spawn("vid", "edit", boom)
        assert done.wait(2)
        time.sleep(0.05)
        assert mgr.failed_ids() == {"vid"}
        assert mgr.active_ids() == set()


# ── cut plan (read + edit) ────────────────────────────────────────────────────

class TestPlan:
    def _ws(self, tmp_path, monkeypatch, plan=None, transcription=True):
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        ws = _mkws(tmp_path, "vid")
        if plan is not None:
            (ws / "reviewed_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        if transcription:
            (ws / "transcription.json").write_text(
                json.dumps(
                    {
                        "duration": 120.0,
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "abertura do vídeo"},
                            {"start": 5.0, "end": 9.0, "text": "explicando o produto"},
                            {"start": 30.0, "end": 34.0, "text": "trecho descartado"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
        return ws

    def test_none_before_planning(self, tmp_path, monkeypatch):
        self._ws(tmp_path, monkeypatch)
        assert engine.read_plan("vid") is None

    def test_none_for_unknown_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        assert engine.read_plan("nope") is None

    def test_reads_segments_with_what_is_said(self, tmp_path, monkeypatch):
        self._ws(
            tmp_path,
            monkeypatch,
            plan={
                "kept_segments": [{"start": 0.0, "end": 9.0, "summary": "intro"}],
                "cuts": [{"start": 30.0, "end": 34.0, "reason": "tangente", "type": "content"}],
                "dropped_blocks": ["bloco sobre preço"],
            },
        )
        out = engine.read_plan("vid")
        assert out["duration"] == 120.0
        assert out["kept_total"] == 9.0
        seg = out["kept_segments"][0]
        assert seg["duration"] == 9.0 and seg["summary"] == "intro"
        assert seg["text"] == "abertura do vídeo explicando o produto"
        assert out["cuts"][0]["duration"] == 4.0
        assert out["dropped_blocks"] == ["bloco sobre preço"]

    def test_falls_back_to_the_planner_draft(self, tmp_path, monkeypatch):
        ws = self._ws(tmp_path, monkeypatch)
        (ws / "cut_plan.json").write_text(json.dumps({"kept_segments": [{"start": 1, "end": 2}]}))
        out = engine.read_plan("vid")
        assert out["source"] == "cut_plan.json" and out["editable"] is False

    def test_skips_malformed_segments(self, tmp_path, monkeypatch):
        self._ws(tmp_path, monkeypatch, plan={"kept_segments": [{"start": 1}, {"start": 2, "end": 4}]})
        assert len(engine.read_plan("vid")["kept_segments"]) == 1

    def test_write_replaces_kept_and_keeps_the_rest(self, tmp_path, monkeypatch):
        self._ws(
            tmp_path,
            monkeypatch,
            plan={"kept_segments": [{"start": 0, "end": 9}], "cuts": [{"start": 30, "end": 34}]},
        )
        out = engine.write_plan("vid", [{"start": 5, "end": 9, "summary": "só o miolo"}])
        assert [(s["start"], s["end"]) for s in out["kept_segments"]] == [(5.0, 9.0)]
        saved = json.loads((tmp_path / "vid" / "reviewed_plan.json").read_text(encoding="utf-8"))
        assert saved["cuts"] == [{"start": 30, "end": 34}]  # untouched

    def test_write_backs_up_the_agent_plan_once(self, tmp_path, monkeypatch):
        self._ws(tmp_path, monkeypatch, plan={"kept_segments": [{"start": 0, "end": 9}]})
        engine.write_plan("vid", [{"start": 1, "end": 2}])
        backup = tmp_path / "vid" / engine.AGENT_PLAN_BACKUP
        assert json.loads(backup.read_text(encoding="utf-8"))["kept_segments"][0]["end"] == 9
        engine.write_plan("vid", [{"start": 3, "end": 4}])
        assert json.loads(backup.read_text(encoding="utf-8"))["kept_segments"][0]["end"] == 9

    def test_write_sorts_by_start(self, tmp_path, monkeypatch):
        self._ws(tmp_path, monkeypatch, plan={"kept_segments": []})
        out = engine.write_plan("vid", [{"start": 9, "end": 12}, {"start": 1, "end": 3}])
        assert [s["start"] for s in out["kept_segments"]] == [1.0, 9.0]

    def test_write_rejects_garbage(self, tmp_path, monkeypatch):
        self._ws(tmp_path, monkeypatch, plan={"kept_segments": []})
        for bad in ([], None, [{"start": 5, "end": 5}], [{"start": -1, "end": 2}], [{"start": "a", "end": 2}]):
            with pytest.raises(ValueError):
                engine.write_plan("vid", bad)

    def test_write_needs_a_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        with pytest.raises(FileNotFoundError):
            engine.write_plan("nope", [{"start": 1, "end": 2}])


# ── browse (file picker source) ───────────────────────────────────────────────

class TestBrowse:
    def _tree(self, root: Path) -> Path:
        (root / "sub").mkdir()
        (root / ".hidden").mkdir()
        (root / "a.mp4").write_bytes(b"x" * 10)
        (root / "b.MOV").write_bytes(b"y" * 20)
        (root / "notes.txt").write_text("nope")
        return root

    def test_lists_videos_and_dirs(self, tmp_path):
        out = engine.browse(str(self._tree(tmp_path)))
        assert out["exists"] is True
        assert [d["name"] for d in out["dirs"]] == ["sub"]  # hidden folder skipped
        assert {v["name"] for v in out["videos"]} == {"a.mp4", "b.MOV"}  # .txt skipped
        assert all(v["size"] > 0 and v["path"] for v in out["videos"])

    def test_newest_video_first(self, tmp_path):
        import os
        self._tree(tmp_path)
        os.utime(tmp_path / "a.mp4", (1_600_000_000, 1_600_000_000))
        os.utime(tmp_path / "b.MOV", (1_700_000_000, 1_700_000_000))
        out = engine.browse(str(tmp_path))
        assert [v["name"] for v in out["videos"]] == ["b.MOV", "a.mp4"]

    def test_missing_dir_reports_not_exists(self, tmp_path):
        out = engine.browse(str(tmp_path / "nope"))
        assert out["exists"] is False and out["videos"] == [] and out["parent"]

    def test_defaults_to_inbox(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_INBOX", str(self._tree(tmp_path)))
        out = engine.browse()
        assert Path(out["dir"]) == tmp_path.resolve()
        assert len(out["videos"]) == 2


# ── HTTP surface (skipped where Flask isn't installed, e.g. CI) ───────────────

class TestBrowseEndpoint:
    def _client(self):
        import pytest
        pytest.importorskip("flask")
        return api.create_app().test_client()

    def test_browse_defaults_to_inbox(self, tmp_path, monkeypatch):
        (tmp_path / "clip.mp4").write_bytes(b"x")
        monkeypatch.setenv("AUTO_EDIT_INBOX", str(tmp_path))
        body = self._client().get("/api/browse").get_json()
        assert body["exists"] is True
        assert [v["name"] for v in body["videos"]] == ["clip.mp4"]

    def test_plan_404_before_planning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        _mkws(tmp_path, "vid")
        assert self._client().get("/api/videos/vid/plan").status_code == 404

    def test_put_plan_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        ws = _mkws(tmp_path, "vid")
        (ws / "reviewed_plan.json").write_text(json.dumps({"kept_segments": [{"start": 0, "end": 9}]}))
        client = self._client()
        r = client.put("/api/videos/vid/plan", json={"kept_segments": [{"start": 2, "end": 5}]})
        assert r.status_code == 200
        assert r.get_json()["kept_segments"][0]["start"] == 2.0
        assert client.get("/api/videos/vid/plan").get_json()["kept_total"] == 3.0

    def test_cors_allows_the_put(self, tmp_path, monkeypatch):
        """The browser preflights PUT: if the header lists only GET/POST the
        save silently fails with "Failed to fetch"."""
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        _mkws(tmp_path, "vid")
        r = self._client().options(
            "/api/videos/vid/plan",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"},
        )
        assert "PUT" in r.headers["Access-Control-Allow-Methods"]

    def test_put_plan_rejects_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path))
        _mkws(tmp_path, "vid")
        r = self._client().put("/api/videos/vid/plan", json={"kept_segments": []})
        assert r.status_code == 400

    def test_browse_honors_dir_param(self, tmp_path):
        (tmp_path / "other.mkv").write_bytes(b"x")
        body = self._client().get(f"/api/browse?dir={tmp_path}").get_json()
        assert [v["name"] for v in body["videos"]] == ["other.mkv"]


# ── api._sse (pure) ───────────────────────────────────────────────────────────

def test_sse_formats_events():
    out = list(api._sse([{"type": "log", "line": "x"}, {"type": "done"}]))
    assert out[0] == 'data: {"type": "log", "line": "x"}\n\n'
    assert out[1] == 'data: {"type": "done"}\n\n'
