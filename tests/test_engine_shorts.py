"""Tests for the shorts side of the headless engine (read model, clipper job,
cut queue) and its HTTP routes. No ffmpeg, ralph.sh, or agent CLI required:
the processes are faked."""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import agents, api, engine
from auto_edit import shorts as sh


def _long_ws(root: Path, wid: str = "talk", *, stage: str = "done", vtype: str = "long", plan=None) -> Path:
    """A finished long workspace, the way `auto-edit long` leaves it."""
    ws = root / wid
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({
        "video_path": f"/videos/{wid}.mp4",
        "video_name": wid,
        "type": vtype,
        "language": "pt",
        "context": "palestra",
        "current_stage": stage,
        "created_at": "2026-01-01T00:00:00+00:00",
        "stages": {},
    }))
    (ws / sh.SOURCE_VIDEO_NAME).write_bytes(b"mp4")
    (ws / sh.POST_CUT_NAME).write_text(json.dumps({
        "duration": 300.0,
        "segments": [
            {"start": 10.0, "end": 20.0, "text": "primeira ideia"},
            {"start": 100.0, "end": 130.0, "text": "segunda ideia"},
        ],
        "words": [],
    }))
    if plan is not None:
        (ws / sh.CLIPS_PLAN_NAME).write_text(json.dumps(plan))
    return ws


PLAN = {
    "source_duration": 300.0,
    "clips": [
        {"start": 10.0, "end": 40.0, "hook": "baixa", "score": 5},
        {"start": 100.0, "end": 140.0, "hook": "alta", "score": 9},
        {"start": 30.0, "end": 60.0, "hook": "sobrepoe a baixa", "score": 7},
        {"start": 200.0, "end": 201.0, "hook": "curta demais", "score": 8},
    ],
    "notes": "três bons",
}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    return tmp_path


def _wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ── shorts_state ──────────────────────────────────────────────────────────────

class TestShortsState:
    def test_unknown_workspace(self, lib):
        assert engine.shorts_state("nope") is None

    def test_short_is_not_eligible(self, lib):
        _long_ws(lib, vtype="short")
        st = engine.shorts_state("talk")
        assert st["eligible"] is False
        assert "long" in st["reason"]

    def test_unfinished_long_is_not_eligible(self, lib):
        _long_ws(lib, stage="execute")
        st = engine.shorts_state("talk")
        assert st["eligible"] is False
        assert "não terminou" in st["reason"]

    def test_eligible_without_plan(self, lib):
        _long_ws(lib)
        st = engine.shorts_state("talk")
        assert st["eligible"] is True
        assert st["has_plan"] is False
        assert st["clips"] == []

    def test_candidates_numbered_by_score_like_the_cli(self, lib):
        _long_ws(lib, plan=PLAN)
        st = engine.shorts_state("talk")
        assert st["has_plan"] is True
        assert [c["hook"] for c in st["clips"]] == ["alta", "sobrepoe a baixa", "baixa"]
        assert [c["number"] for c in st["clips"]] == [1, 2, 3]
        assert len(st["rejected"]) == 1 and "mínimo" in st["rejected"][0]
        assert st["notes"] == "três bons"

    def test_candidate_carries_what_is_said_and_overlaps(self, lib):
        _long_ws(lib, plan=PLAN)
        clips = {c["hook"]: c for c in engine.shorts_state("talk")["clips"]}
        assert clips["alta"]["text"] == "segunda ideia"
        assert clips["alta"]["duration"] == 40.0
        assert clips["alta"]["overlaps"] is False
        assert clips["baixa"]["overlaps"] is True
        assert clips["sobrepoe a baixa"]["overlaps"] is True

    def test_reports_an_already_cut_short(self, lib):
        ws = _long_ws(lib, plan=PLAN)
        clips, _ = sh.load_clips_plan(ws)
        sh.seed_short_workspace(ws, json.loads((ws / "pipeline.json").read_text()), clips[0], 1)
        first = engine.shorts_state("talk")["clips"][0]
        assert first["short"]["id"] == "talk_short1"
        assert first["short"]["overwrite_warning"] is None

    def test_max_duration_filters(self, lib):
        _long_ws(lib, plan=PLAN)
        st = engine.shorts_state("talk", max_duration=35)
        assert [c["hook"] for c in st["clips"]] == ["sobrepoe a baixa", "baixa"]


# ── cut_shorts (seed + queue) ─────────────────────────────────────────────────

class TestCutShorts:
    def test_seeds_and_runs_one_at_a_time(self, lib, monkeypatch):
        _long_ws(lib, plan=PLAN)
        order: list[str] = []
        running = {"now": 0, "max": 0}

        def fake_run(ws, *, emit, language="pt", **_):
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            time.sleep(0.02)
            order.append(ws.name)
            running["now"] -= 1
            emit({"type": "done", "status": "done"})
            return 0

        monkeypatch.setattr(engine, "run_workspace", fake_run)
        mgr = engine.JobManager()
        ids = mgr.cut_shorts("talk", [3, 1])

        assert ids == ["talk_short1", "talk_short3"]
        for wid in ids:  # seeded up front, so the library lists them at once
            assert (lib / wid / "pipeline.json").exists()
        assert _wait(lambda: len(order) == 2)
        assert order == ["talk_short1", "talk_short3"]
        assert running["max"] == 1
        assert _wait(lambda: not mgr.queued_ids())

    def test_pending_shorts_read_as_queued(self, lib, monkeypatch):
        _long_ws(lib, plan=PLAN)
        import threading
        release = threading.Event()

        def fake_run(ws, *, emit, **_):
            release.wait(2)
            emit({"type": "done", "status": "done"})
            return 0

        monkeypatch.setattr(engine, "run_workspace", fake_run)
        mgr = engine.JobManager()
        mgr.cut_shorts("talk", [1, 2])
        assert _wait(lambda: "talk_short1" in mgr.active_ids())
        assert mgr.queued_ids() == {"talk_short2"}
        lib_items = {
            v["id"]: v for v in engine.list_library(
                active_ids=mgr.active_ids(), queued_ids=mgr.queued_ids()
            )
        }
        assert lib_items["talk_short1"]["status"] == "running"
        assert lib_items["talk_short2"]["status"] == "queued"
        assert lib_items["talk_short2"]["derived_from"] == "talk"
        release.set()
        assert _wait(lambda: not mgr.active_ids() and not mgr.queued_ids())

    def test_a_failed_short_stops_the_queue(self, lib, monkeypatch):
        _long_ws(lib, plan=PLAN)
        ran: list[str] = []

        def fake_run(ws, *, emit, **_):
            ran.append(ws.name)
            emit({"type": "error", "status": "failed"})
            return 1

        monkeypatch.setattr(engine, "run_workspace", fake_run)
        mgr = engine.JobManager()
        mgr.cut_shorts("talk", [1, 2])
        assert _wait(lambda: not mgr.queued_ids())
        time.sleep(0.05)
        assert ran == ["talk_short1"]

    @pytest.mark.parametrize("pick", [[], [0], [4], ["x"]])
    def test_rejects_bad_picks(self, lib, pick):
        _long_ws(lib, plan=PLAN)
        with pytest.raises(sh.ShortsError):
            engine.JobManager().cut_shorts("talk", pick)

    def test_needs_a_plan(self, lib):
        _long_ws(lib)
        with pytest.raises(sh.ShortsError):
            engine.JobManager().cut_shorts("talk", [1])


# ── find_shorts / run_clipper ─────────────────────────────────────────────────

class _Proc:
    def __init__(self, lines, rc):
        self.stdout = iter(lines)
        self._rc = rc

    def wait(self):
        return self._rc


class TestClipper:
    def test_find_shorts_needs_a_finished_long(self, lib):
        _long_ws(lib, stage="plan")
        with pytest.raises(sh.ShortsError):
            engine.JobManager().find_shorts("talk")

    def test_find_shorts_refuses_while_busy(self, lib, monkeypatch):
        _long_ws(lib)
        import threading
        release = threading.Event()

        def fake_clipper(ws, *, emit, **_):
            release.wait(2)
            return 0

        monkeypatch.setattr(engine, "run_clipper", fake_clipper)
        mgr = engine.JobManager()
        job = mgr.find_shorts("talk", max_duration=60)
        assert job.kind == "shorts"
        with pytest.raises(sh.ShortsError):
            mgr.find_shorts("talk")
        release.set()

    def test_run_clipper_invokes_ralph_agent(self, tmp_path, monkeypatch):
        ws = _long_ws(tmp_path)
        ralph = tmp_path / "ralph.sh"
        ralph.write_text("#!/bin/bash\n")
        monkeypatch.setattr(engine, "ralph_path", lambda: ralph)
        seen = {}

        def fake_popen(args, **kw):
            seen["args"], seen["env"] = args, kw["env"]
            return _Proc(["pensando\n"], 0)

        evs: list[dict] = []
        rc = engine.run_clipper(ws, emit=evs.append, max_duration=60, popen=fake_popen)
        assert rc == 0
        assert seen["args"][2:4] == ["--agent", str(ws.resolve())]
        assert seen["args"][4] == "clip"
        assert seen["args"][5].endswith(sh.CLIPS_PLAN_NAME)
        assert seen["args"][6].endswith("clipper.md")
        assert seen["env"]["AUTO_EDIT_CLIP_MAX_DUR"] == "60"
        assert [e["type"] for e in evs] == ["log", "done"]

    def test_run_clipper_failure_emits_error(self, tmp_path, monkeypatch):
        ws = _long_ws(tmp_path)
        ralph = tmp_path / "ralph.sh"
        ralph.write_text("#!/bin/bash\n")
        monkeypatch.setattr(engine, "ralph_path", lambda: ralph)
        evs: list[dict] = []
        rc = engine.run_clipper(ws, emit=evs.append, popen=lambda *a, **k: _Proc([], 2))
        assert rc == 2
        assert evs[-1]["type"] == "error"

    def _fail_clipper(self, ws, tmp_path, monkeypatch, popen):
        ralph = tmp_path / "ralph.sh"
        ralph.write_text("#!/bin/bash\n")
        monkeypatch.setattr(engine, "ralph_path", lambda: ralph)
        evs: list[dict] = []
        engine.run_clipper(ws, emit=evs.append, popen=popen)
        return evs[-1]

    def test_run_clipper_tells_when_the_video_exceeds_the_model(self, tmp_path, monkeypatch):
        ws = _long_ws(tmp_path)
        reason = f"este vídeo {agents.MODEL_LIMIT_MARK} qwen2.5:7b. Escolha outro agente em Configurações"

        def popen(*a, **k):
            (ws / ".output_clip.txt").write_text(reason + "\n", encoding="utf-8")
            return _Proc([], 1)

        assert self._fail_clipper(ws, tmp_path, monkeypatch, popen)["message"] == reason

    def test_run_clipper_ignores_the_output_of_a_previous_run(self, tmp_path, monkeypatch):
        ws = _long_ws(tmp_path)
        (ws / ".output_clip.txt").write_text(f"este vídeo {agents.MODEL_LIMIT_MARK} x\n", encoding="utf-8")
        ev = self._fail_clipper(ws, tmp_path, monkeypatch, lambda *a, **k: _Proc([], 1))
        assert ev["message"] == "o clipper falhou"

    def test_run_clipper_keeps_the_generic_message_for_other_failures(self, tmp_path, monkeypatch):
        ws = _long_ws(tmp_path)

        def popen(*a, **k):
            (ws / ".output_clip.txt").write_text("ollama fora do ar\n", encoding="utf-8")
            return _Proc([], 1)

        assert self._fail_clipper(ws, tmp_path, monkeypatch, popen)["message"] == "o clipper falhou"


def test_queued_status():
    p = {"current_stage": "execute", "stages": {"execute": {"status": "pending"}}}
    assert engine.overall_status(p, queued=True) == "queued"
    assert engine.overall_status(p, active=True, queued=True) == "running"


# ── HTTP ──────────────────────────────────────────────────────────────────────

class TestShortsEndpoints:
    def _client(self, jobs=None):
        pytest.importorskip("flask")
        return api.create_app(jobs).test_client()

    def test_get_404_for_unknown(self, lib):
        assert self._client().get("/api/videos/nope/shorts").status_code == 404

    def test_get_lists_candidates(self, lib):
        _long_ws(lib, plan=PLAN)
        body = self._client().get("/api/videos/talk/shorts?max_dur=35").get_json()
        assert [c["number"] for c in body["clips"]] == [1, 2]

    def test_find_400_on_unfinished_long(self, lib):
        _long_ws(lib, stage="plan")
        r = self._client().post("/api/videos/talk/shorts", json={})
        assert r.status_code == 400

    def test_cut_needs_a_list(self, lib):
        _long_ws(lib, plan=PLAN)
        r = self._client().post("/api/videos/talk/shorts/cut", json={"pick": "1,3"})
        assert r.status_code == 400

    def test_cut_starts_the_queue(self, lib, monkeypatch):
        _long_ws(lib, plan=PLAN)
        monkeypatch.setattr(engine, "run_workspace", lambda ws, *, emit, **_: 0)
        r = self._client(engine.JobManager()).post(
            "/api/videos/talk/shorts/cut", json={"pick": [2]}
        )
        assert r.status_code == 202
        assert r.get_json() == {"shorts": ["talk_short2"]}
