"""Stopping an edit, telling a dead run from a live one, and the library
naming videos by their title."""
import json
import subprocess
import sys
import time

import pytest

from auto_edit import api, engine


def _ws(root, wid="vid", stage_status="running", metadata=None):
    ws = root / wid
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({
        "video_name": wid, "type": "long", "current_stage": "execute", "context": "Falando do Rodar",
        "created_at": "2026-01-01T00:00:00+00:00",
        "stages": {"plan": {"status": "complete"}, "execute": {"status": stage_status}},
    }), encoding="utf-8")
    if metadata:
        (ws / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return ws


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    return tmp_path


class TestInterrupted:
    def test_running_stage_with_nothing_behind_it(self):
        p = {"current_stage": "execute", "stages": {"execute": {"status": "running"}}}
        assert engine.overall_status(p, alive=False) == "interrupted"
        assert engine.overall_status(p, alive=True) == "running"
        assert engine.overall_status(p, alive=None) == "running"  # can't tell (Windows)
        assert engine.overall_status(p, active=True, alive=False) == "running"

    def test_library_uses_the_live_process_list(self, lib, monkeypatch):
        _ws(lib, "dead")
        _ws(lib, "cli_run")
        monkeypatch.setattr(engine, "live_ralph_workspaces", lambda: {"cli_run"})
        status = {v["id"]: v["status"] for v in engine.list_library()}
        assert status == {"dead": "interrupted", "cli_run": "running"}


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
class TestStop:
    def test_stops_the_job_and_everything_it_started(self, lib):
        ws = _ws(lib)
        mgr = engine.JobManager()
        started = {}

        def target(emit):
            # bash → sleep: the child must die too, not just the shell.
            proc = subprocess.Popen(["bash", "-c", "sleep 30 & wait"], **engine._own_process_group())
            engine._register(proc)
            started["proc"] = proc
            proc.wait()
            if engine._was_cancelled():
                emit({"type": "error", "status": "cancelled"})

        job = mgr._spawn("vid", "edit", target)
        for _ in range(100):
            if "proc" in started:
                break
            time.sleep(0.02)
        result = mgr.stop("vid")
        started["proc"].wait(timeout=5)
        for _ in range(100):
            if job.status != "running":
                break
            time.sleep(0.02)

        assert "job" in result["stopped"]
        assert result["reset_stages"] == ["execute"]
        assert job.status == "cancelled"
        assert json.loads((ws / "pipeline.json").read_text(encoding="utf-8"))["stages"]["execute"]["status"] == "pending"
        assert vid_not_failed(mgr)

    def test_stopping_a_dead_run_just_resets_it(self, lib, monkeypatch):
        ws = _ws(lib)
        monkeypatch.setattr(engine, "_ralph_pids", lambda ws: [])
        result = engine.JobManager().stop("vid")
        assert result == {"id": "vid", "stopped": [], "reset_stages": ["execute"]}
        p = json.loads((ws / "pipeline.json").read_text(encoding="utf-8"))
        assert engine.overall_status(p, alive=False) == "idle"

    def test_unknown(self, lib):
        with pytest.raises(FileNotFoundError):
            engine.JobManager().stop("nope")


def vid_not_failed(mgr):
    return "vid" not in mgr.failed_ids()


def test_stopped_short_leaves_the_queue(lib, monkeypatch):
    mgr = engine.JobManager()
    _ws(lib, "s1", stage_status="pending")
    with mgr._lock:
        mgr._queued.add("s1")
    monkeypatch.setattr(engine, "_ralph_pids", lambda ws: [])
    assert mgr.stop("s1")["stopped"] == ["fila"]
    assert mgr.queued_ids() == set()


def test_stop_endpoint(lib, monkeypatch):
    pytest.importorskip("flask")
    _ws(lib)
    monkeypatch.setattr(engine, "_ralph_pids", lambda ws: [])
    client = api.create_app(engine.JobManager()).test_client()
    assert client.post("/api/videos/vid/stop").get_json()["reset_stages"] == ["execute"]
    assert client.post("/api/videos/nope/stop").status_code == 404


class TestLibraryNames:
    def test_title_from_metadata_and_thumbnail(self, lib):
        _ws(lib, "a", stage_status="complete", metadata={"youtube_title": "Rodar: o app que lê o carro"})
        (lib / "output").mkdir()
        (lib / "output" / "a_thumbnail.png").write_bytes(b"png")
        item = engine.summarize(lib / "a")
        assert item["title"] == "Rodar: o app que lê o carro"
        assert item["context"] == "Falando do Rodar"
        assert item["has_thumbnail"] is True

    def test_no_metadata_yet(self, lib):
        item = engine.summarize(_ws(lib, "b", stage_status="pending"))
        assert item["title"] is None and item["has_thumbnail"] is False

    def test_short_title(self, lib):
        _ws(lib, "c", stage_status="complete", metadata={"short_title": "Encostou, abriu a comanda"})
        assert engine.summarize(lib / "c")["title"] == "Encostou, abriu a comanda"
