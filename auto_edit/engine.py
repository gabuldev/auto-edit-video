"""
Headless engine facade over the canonical pipeline (ralph.sh + pipeline.py +
workspace.py).

This is the single, UI-agnostic entry point a desktop/web frontend drives:
list the library, read a workspace's status, start an edit, resume a stage, and
subscribe to live progress events. It reuses the exact same state machine and
ralph.sh invocation the CLI and MCP server use — it does not reimplement the
pipeline. The legacy Flask `web_app.py` predates this and is left untouched.

Nothing here imports a web framework; `api.py` layers HTTP/SSE on top.
"""
from __future__ import annotations

import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Callable, Iterator

from auto_edit import pipeline as pl
from auto_edit.workspace import init_workspace

# ── Paths ─────────────────────────────────────────────────────────────────────


def repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def ralph_path() -> Path:
    return repo_root() / "ralph.sh"


def library_root() -> Path:
    """Directory holding per-video workspaces (same layout the CLI writes)."""
    return Path(os.environ.get("AUTO_EDIT_WORKSPACE", "workspace"))


# ── Status derivation ─────────────────────────────────────────────────────────


def overall_status(pipeline: dict, active: bool = False) -> str:
    """Collapse a pipeline.json into one status: running | done | failed | idle.

    `active` is True while the engine has a live job for this workspace — the
    pipeline.json alone can't tell "paused between runs" from "in progress".
    """
    stages = pipeline.get("stages", {})
    if pipeline.get("current_stage") == "done":
        return "done"
    if any(s.get("status") == "failed" for s in stages.values()):
        return "failed"
    if active or any(s.get("status") == "running" for s in stages.values()):
        return "running"
    return "idle"


def _output_file(ws: Path, pipeline: dict) -> Path | None:
    """The finalized output for a done workspace, if present on disk."""
    output_dir = ws.parent / "output"
    candidate = output_dir / f"{pipeline.get('video_name', ws.name)}_final.mp4"
    return candidate if candidate.exists() else None


def _read_json(path: Path) -> dict | list | None:
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Read models ───────────────────────────────────────────────────────────────


def summarize(ws: Path, active: bool = False) -> dict:
    """One-line summary of a workspace for the library list."""
    p = pl.load(ws)
    tokens = (p.get("token_stats") or {}).get("total_estimated_tokens")
    out = _output_file(ws, p)
    return {
        "id": ws.name,
        "video_name": p.get("video_name", ws.name),
        "video_path": p.get("video_path"),
        "type": p.get("type"),
        "language": p.get("language"),
        "current_stage": p.get("current_stage"),
        "status": overall_status(p, active=active),
        "iteration": p.get("iteration"),
        "max_iterations": p.get("max_iterations"),
        "plan_id": p.get("plan_id"),
        "created_at": p.get("created_at"),
        "stages": {name: info.get("status") for name, info in p.get("stages", {}).items()},
        "estimated_tokens": tokens,
        "output": str(out) if out else None,
    }


def list_library(active_ids: set[str] | None = None) -> list[dict]:
    """Every workspace under the library root, newest first."""
    active_ids = active_ids or set()
    root = library_root()
    if not root.is_dir():
        return []
    items: list[dict] = []
    for pj in root.glob("*/pipeline.json"):
        ws = pj.parent
        try:
            items.append(summarize(ws, active=ws.name in active_ids))
        except (FileNotFoundError, ValueError):
            continue
    items.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return items


def detail(video_id: str, active: bool = False) -> dict | None:
    """Full status for one workspace, plus plan/metadata summaries when present."""
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    p = pl.load(ws)
    data = summarize(ws, active=active)
    data["context"] = p.get("context")
    data["stage_detail"] = p.get("stages", {})
    data["token_stats"] = p.get("token_stats")

    reviewed = _read_json(ws / "reviewed_plan.json")
    if isinstance(reviewed, dict):
        segs = reviewed.get("kept_segments") or []
        data["plan"] = {
            "kept_segments": len(segs),
            "dropped_blocks": reviewed.get("dropped_blocks"),
        }

    metadata = _read_json(ws / "metadata.json")
    if isinstance(metadata, dict):
        data["metadata"] = metadata

    return data


# ── Live job registry ─────────────────────────────────────────────────────────

# An event is a plain dict: {"type": "log"|"stage"|"done"|"error", ...}.
Event = dict
Emit = Callable[[Event], None]
_SENTINEL: Event = {"type": "_end"}


@dataclass
class Job:
    id: str
    video_id: str
    kind: str  # "edit" | "resume"
    status: str = "running"  # running | done | failed
    history: list[Event] = field(default_factory=list)
    _subscribers: set[Queue] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def emit(self, event: Event) -> None:
        with self._lock:
            self.history.append(event)
            if event.get("type") == "done":
                self.status = "done"
            elif event.get("type") == "error":
                self.status = "failed"
            subs = list(self._subscribers)
        for q in subs:
            q.put(event)

    def close(self) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(_SENTINEL)

    def subscribe(self) -> Iterator[Event]:
        """Yield backlog then live events until the job ends. Drop the sub on exit."""
        q: Queue = Queue()
        with self._lock:
            backlog = list(self.history)
            finished = self.status != "running"
            self._subscribers.add(q)
        try:
            for ev in backlog:
                yield ev
            if finished:
                return
            while True:
                ev = q.get()
                if ev is _SENTINEL:
                    return
                yield ev
        finally:
            with self._lock:
                self._subscribers.discard(q)


class JobManager:
    """Tracks running pipeline jobs and their event streams (in-memory)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_video: dict[str, str] = {}
        self._lock = threading.Lock()

    def active_ids(self) -> set[str]:
        with self._lock:
            return {
                self._jobs[jid].video_id
                for jid in self._by_video.values()
                if self._jobs[jid].status == "running"
            }

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def job_for_video(self, video_id: str) -> Job | None:
        with self._lock:
            jid = self._by_video.get(video_id)
            return self._jobs.get(jid) if jid else None

    def _spawn(self, video_id: str, kind: str, target: Callable[[Emit], int]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], video_id=video_id, kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._by_video[video_id] = job.id

        def _run() -> None:
            try:
                target(job.emit)
            except Exception as exc:  # surface, never crash the thread silently
                job.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                if job.status == "running":
                    job.emit({"type": "done", "status": "done"})
                job.close()

        threading.Thread(target=_run, name=f"job-{job.id}", daemon=True).start()
        return job

    def start_edit(
        self,
        video_path: str,
        video_type: str,
        *,
        context: str = "",
        whisper_model: str = "small",
        language: str = "pt",
        max_iterations: int = 3,
        dry_run: bool = False,
        overlays_dir: str | None = None,
        caption_style: dict | None = None,
    ) -> Job:
        video = Path(video_path).resolve()
        if not video.exists():
            raise FileNotFoundError(f"file not found: {video}")
        ws = init_workspace(
            video_path=video,
            video_type=video_type,
            context=context,
            whisper_model=whisper_model,
            max_iterations=max_iterations,
            caption_style=caption_style or {},
            language=language,
        )
        return self._spawn(
            ws.name,
            "edit",
            lambda emit: run_workspace(
                ws, dry_run=dry_run, language=language,
                overlays_dir=overlays_dir, emit=emit,
            ),
        )

    def resume_edit(self, video_id: str, from_stage: str, *, overlays_dir: str | None = None) -> Job:
        ws = library_root() / video_id
        if not (ws / "pipeline.json").exists():
            raise FileNotFoundError(f"no workspace for: {video_id}")
        p = pl.load(ws)
        if from_stage not in pl.STAGES:
            raise ValueError(f"unknown stage: {from_stage}")
        pl.set_stage(ws, from_stage)
        return self._spawn(
            video_id,
            "resume",
            lambda emit: run_workspace(
                ws, dry_run=False, language=p.get("language", "pt"),
                overlays_dir=overlays_dir, emit=emit,
            ),
        )


# ── Pipeline runner (streams ralph.sh) ────────────────────────────────────────


def run_workspace(
    ws: Path,
    *,
    emit: Emit,
    dry_run: bool = False,
    language: str = "pt",
    overlays_dir: str | None = None,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    """Run ralph.sh on `ws`, emitting log/stage/done/error events. Returns rc.

    Stage transitions come from re-reading pipeline.json (the single source of
    truth ralph updates), so they stay accurate regardless of log formatting.
    `popen` is injectable for tests.
    """
    ralph = ralph_path()
    if not ralph.exists():
        emit({"type": "error", "message": f"ralph.sh not found at {ralph}"})
        return 1

    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(ralph.parent.resolve())
    env["AUTO_EDIT_LANGUAGE"] = language
    env.setdefault("AUTO_EDIT_LLM", "claude")
    env["PYTHON"] = os.environ.get("PYTHON", __import__("sys").executable)
    if dry_run:
        env["AUTO_EDIT_DRY_RUN"] = "1"
    if overlays_dir:
        env["AUTO_EDIT_ASSETS_OVERLAYS"] = str(Path(overlays_dir).expanduser().resolve())

    proc = popen(
        ["bash", str(ralph), str(ws.resolve())],
        cwd=str(ralph.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    last_stage: str | None = None
    if proc.stdout is not None:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line:
                emit({"type": "log", "line": line})
            cur = _current_stage(ws)
            if cur and cur != last_stage:
                last_stage = cur
                emit({"type": "stage", "stage": cur})

    rc = proc.wait()
    if rc == 0:
        out = None
        try:
            out = _output_file(ws, pl.load(ws))
        except (FileNotFoundError, ValueError):
            pass
        emit({"type": "done", "status": "done", "output": str(out) if out else None})
    else:
        emit({"type": "error", "status": "failed", "stage": _current_stage(ws)})
    return rc


def _current_stage(ws: Path) -> str | None:
    try:
        return pl.load(ws).get("current_stage")
    except (FileNotFoundError, ValueError):
        return None


# Module-level manager the API layer shares.
jobs = JobManager()
