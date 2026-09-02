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

import json
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
from auto_edit.workspace import init_workspace, workspace_root

# ── Paths ─────────────────────────────────────────────────────────────────────


def repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def ralph_path() -> Path:
    return repo_root() / "ralph.sh"


def library_root() -> Path:
    """Directory holding per-video workspaces (same one the CLI writes to)."""
    return workspace_root()


def inbox_root() -> Path:
    """Default folder the "new edit" picker browses (same one `plan ingest` uses)."""
    env = os.environ.get("AUTO_EDIT_INBOX")
    if env:
        return Path(env).expanduser()
    return repo_root() / "upload"


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts"}


def browse(directory: str | None = None) -> dict:
    """List sub-folders and video files of a directory — feeds the file picker.

    Defaults to the inbox. Read-only and video-only: it never walks recursively
    and never reports files the pipeline could not open anyway.
    """
    root = Path(directory).expanduser() if directory else inbox_root()
    try:
        root = root.resolve()
    except OSError:
        return {"dir": str(root), "parent": None, "exists": False, "dirs": [], "videos": []}

    if not root.is_dir():
        return {"dir": str(root), "parent": str(root.parent), "exists": False, "dirs": [], "videos": []}

    dirs: list[dict] = []
    videos: list[dict] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            if entry.is_dir():
                if not entry.name.startswith("."):
                    dirs.append({"name": entry.name, "path": str(entry)})
            elif entry.suffix.lower() in VIDEO_EXTS:
                stat = entry.stat()
                videos.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    }
                )
        except OSError:
            continue

    dirs.sort(key=lambda d: d["name"].lower())
    videos.sort(key=lambda v: v["modified"], reverse=True)
    parent = str(root.parent) if root.parent != root else None
    return {"dir": str(root), "parent": parent, "exists": True, "dirs": dirs, "videos": videos}


# ── Status derivation ─────────────────────────────────────────────────────────


def overall_status(pipeline: dict, active: bool = False, failed: bool = False) -> str:
    """Collapse a pipeline.json into one status: running | done | failed | idle.

    `active` is True while the engine has a live job for this workspace — the
    pipeline.json alone can't tell "paused between runs" from "in progress".
    `failed` is True when the last job for it died: a run that blows up before
    ralph marks a stage would otherwise read as a calm "idle".
    """
    stages = pipeline.get("stages", {})
    if pipeline.get("current_stage") == "done":
        return "done"
    if failed or any(s.get("status") == "failed" for s in stages.values()):
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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Read models ───────────────────────────────────────────────────────────────


def summarize(ws: Path, active: bool = False, failed: bool = False) -> dict:
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
        "status": overall_status(p, active=active, failed=failed),
        "iteration": p.get("iteration"),
        "max_iterations": p.get("max_iterations"),
        "plan_id": p.get("plan_id"),
        "created_at": p.get("created_at"),
        "stages": {name: info.get("status") for name, info in p.get("stages", {}).items()},
        "estimated_tokens": tokens,
        "output": str(out) if out else None,
    }


def list_library(
    active_ids: set[str] | None = None,
    failed_ids: set[str] | None = None,
) -> list[dict]:
    """Every workspace under the library root, newest first."""
    active_ids = active_ids or set()
    failed_ids = failed_ids or set()
    root = library_root()
    if not root.is_dir():
        return []
    items: list[dict] = []
    for pj in root.glob("*/pipeline.json"):
        ws = pj.parent
        try:
            items.append(
                summarize(ws, active=ws.name in active_ids, failed=ws.name in failed_ids)
            )
        except (FileNotFoundError, ValueError):
            continue
    items.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return items


def detail(video_id: str, active: bool = False, failed: bool = False) -> dict | None:
    """Full status for one workspace, plus plan/metadata summaries when present."""
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    p = pl.load(ws)
    data = summarize(ws, active=active, failed=failed)
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


# ── Cut plan (read + edit) ────────────────────────────────────────────────────

PLAN_FILES = ("reviewed_plan.json", "cut_plan.json")
AGENT_PLAN_BACKUP = "reviewed_plan.agent.json"


def _plan_path(ws: Path) -> Path | None:
    """The plan the executor would use, falling back to the planner's draft."""
    for name in PLAN_FILES:
        if (ws / name).exists():
            return ws / name
    return None


def _transcript_text(segments: list[dict], start: float, end: float, limit: int = 400) -> str:
    """Whatever was said inside a window — that's what makes a cut reviewable."""
    said = [
        (s.get("text") or "").strip()
        for s in segments
        if s.get("end", 0) > start and s.get("start", 0) < end
    ]
    text = " ".join(t for t in said if t)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def read_plan(video_id: str) -> dict | None:
    """The cut plan of a workspace, enriched with what is said in each segment.

    Returns None when the workspace doesn't exist or hasn't planned yet — the
    plan only shows up after the `plan`/`review` stages.
    """
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    path = _plan_path(ws)
    if path is None:
        return None
    plan = _read_json(path)
    if not isinstance(plan, dict):
        return None

    transcription = _read_json(ws / "transcription.json")
    segments = []
    duration = None
    if isinstance(transcription, dict):
        segments = transcription.get("segments") or []
        duration = transcription.get("duration")

    kept = []
    for i, seg in enumerate(plan.get("kept_segments") or []):
        try:
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        kept.append(
            {
                "index": i,
                "start": start,
                "end": end,
                "duration": round(end - start, 3),
                "summary": seg.get("summary") or seg.get("reason"),
                "text": _transcript_text(segments, start, end),
            }
        )

    cuts = []
    for cut in plan.get("cuts") or []:
        try:
            start, end = float(cut["start"]), float(cut["end"])
        except (KeyError, TypeError, ValueError):
            continue
        cuts.append(
            {
                "start": start,
                "end": end,
                "duration": round(end - start, 3),
                "reason": cut.get("reason"),
                "type": cut.get("type"),
            }
        )

    return {
        "id": video_id,
        "source": path.name,
        "editable": path.name == "reviewed_plan.json",
        "duration": duration,
        "kept_total": round(sum(k["duration"] for k in kept), 3),
        "kept_segments": kept,
        "cuts": cuts,
        "dropped_blocks": plan.get("dropped_blocks"),
    }


def write_plan(video_id: str, kept_segments: list[dict]) -> dict:
    """Replace the kept segments of a workspace's plan.

    Everything else in the plan (cuts, dropped_blocks, …) is preserved, and the
    agent's own version is kept once as `reviewed_plan.agent.json` so an edit
    made by hand never destroys what the planner proposed.
    """
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        raise FileNotFoundError(f"no workspace for: {video_id}")
    if not isinstance(kept_segments, list) or not kept_segments:
        raise ValueError("kept_segments must be a non-empty list")

    cleaned: list[dict] = []
    for i, seg in enumerate(kept_segments):
        try:
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"kept_segments[{i}] needs numeric start and end") from exc
        if start < 0:
            raise ValueError(f"kept_segments[{i}] start is negative")
        if end <= start:
            raise ValueError(f"kept_segments[{i}] end must be greater than start")
        entry = {"start": round(start, 3), "end": round(end, 3)}
        if seg.get("summary"):
            entry["summary"] = seg["summary"]
        cleaned.append(entry)
    cleaned.sort(key=lambda s: s["start"])

    path = _plan_path(ws)
    base = _read_json(path) if path else None
    plan = dict(base) if isinstance(base, dict) else {}

    target = ws / "reviewed_plan.json"
    backup = ws / AGENT_PLAN_BACKUP
    if target.exists() and not backup.exists():
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")

    plan["kept_segments"] = cleaned
    target.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return read_plan(video_id) or {}


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
        return self._ids_with_status("running")

    def failed_ids(self) -> set[str]:
        """Videos whose latest job died — the library shows them as failed even
        when ralph never got far enough to mark a stage."""
        return self._ids_with_status("failed")

    def _ids_with_status(self, status: str) -> set[str]:
        with self._lock:
            return {
                self._jobs[jid].video_id
                for jid in self._by_video.values()
                if self._jobs[jid].status == status
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
