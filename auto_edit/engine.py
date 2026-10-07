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
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Callable, Iterator

from auto_edit import pipeline as pl
from auto_edit.chapters import description_with_chapters
from auto_edit import shorts as sh
from auto_edit.publish import youtube as yt
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


def overall_status(
    pipeline: dict, active: bool = False, failed: bool = False, queued: bool = False
) -> str:
    """Collapse a pipeline.json into one status: running | done | failed | queued | idle.

    `active` is True while the engine has a live job for this workspace — the
    pipeline.json alone can't tell "paused between runs" from "in progress".
    `failed` is True when the last job for it died: a run that blows up before
    ralph marks a stage would otherwise read as a calm "idle". `queued` is True
    while it waits its turn behind another job (shorts are cut one at a time).
    """
    stages = pipeline.get("stages", {})
    if pipeline.get("current_stage") == "done":
        return "done"
    if failed or any(s.get("status") == "failed" for s in stages.values()):
        return "failed"
    if active or any(s.get("status") == "running" for s in stages.values()):
        return "running"
    if queued:
        return "queued"
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


def summarize(ws: Path, active: bool = False, failed: bool = False, queued: bool = False) -> dict:
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
        "status": overall_status(p, active=active, failed=failed, queued=queued),
        "derived_from": Path(p["derived_from"]).name if p.get("derived_from") else None,
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
    queued_ids: set[str] | None = None,
) -> list[dict]:
    """Every workspace under the library root, newest first."""
    active_ids = active_ids or set()
    failed_ids = failed_ids or set()
    queued_ids = queued_ids or set()
    root = library_root()
    if not root.is_dir():
        return []
    items: list[dict] = []
    for pj in root.glob("*/pipeline.json"):
        ws = pj.parent
        try:
            items.append(
                summarize(
                    ws,
                    active=ws.name in active_ids,
                    failed=ws.name in failed_ids,
                    queued=ws.name in queued_ids,
                )
            )
        except (FileNotFoundError, ValueError):
            continue
    items.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return items


def detail(
    video_id: str, active: bool = False, failed: bool = False, queued: bool = False
) -> dict | None:
    """Full status for one workspace, plus plan/metadata summaries when present."""
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    p = pl.load(ws)
    data = summarize(ws, active=active, failed=failed, queued=queued)
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


# ── Finished artifacts ────────────────────────────────────────────────────────

# What `pipeline.finalize()` drops in <workspace root>/output/, by kind.
ARTIFACT_SUFFIXES = {
    "video": "_final.mp4",
    "thumbnail": "_thumbnail.png",
    "captions": ".srt",
    "notes": ".txt",
}
ARTIFACT_MIME = {
    "video": "video/mp4",
    "thumbnail": "image/png",
    "captions": "text/plain; charset=utf-8",
    "notes": "text/plain; charset=utf-8",
}


def artifact_path(video_id: str, kind: str) -> Path | None:
    """Absolute path of one finished artifact, or None when it isn't there.

    Only the four known kinds resolve, and always inside the library's own
    output folder — this is what the API serves to the player.
    """
    suffix = ARTIFACT_SUFFIXES.get(kind)
    if suffix is None:
        return None
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    name = pl.load(ws).get("video_name", video_id)
    # Absolute: the library root is usually relative ("workspace"), and Flask's
    # send_file resolves a relative path against the package, not the cwd.
    candidate = (ws.parent / "output" / f"{name}{suffix}").resolve()
    return candidate if candidate.is_file() else None


def open_artifact(
    video_id: str,
    kind: str,
    *,
    reveal: bool = False,
    run: Callable[..., object] = subprocess.Popen,
) -> Path | None:
    """Open a finished artifact with the OS: its default app, or the file
    manager with the file selected (`reveal`). None when it isn't there.

    The engine runs on the user's own machine, so this is how a frontend gets
    a file onto the screen — a webview (Tauri) won't follow a download link.
    """
    path = artifact_path(video_id, kind)
    if path is None:
        return None
    if sys.platform == "darwin":
        cmd = ["open", "-R", str(path)] if reveal else ["open", str(path)]
    elif sys.platform == "win32":
        cmd = ["explorer", f"/select,{path}"] if reveal else ["cmd", "/c", "start", "", str(path)]
    else:  # no portable "select in folder" on Linux: open the folder instead
        cmd = ["xdg-open", str(path.parent if reveal else path)]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


# Links the frontend may ask the OS to open — only the platforms we publish to.
_OPENABLE_URL = re.compile(r"^https://(www\.|studio\.)?youtube\.com/|^https://youtu\.be/")


def open_url(url: str, *, run: Callable[..., object] = subprocess.Popen) -> bool:
    """Open a platform link in the default browser (the webview won't)."""
    if not isinstance(url, str) or not _OPENABLE_URL.match(url):
        return False
    if sys.platform == "darwin":
        cmd = ["open", url]
    elif sys.platform == "win32":
        cmd = ["cmd", "/c", "start", "", url]
    else:
        cmd = ["xdg-open", url]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def result(video_id: str) -> dict | None:
    """Everything the "Resultado" screen shows: metadata + the files on disk."""
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    p = pl.load(ws)

    files = {}
    for kind in ARTIFACT_SUFFIXES:
        path = artifact_path(video_id, kind)
        if path is not None:
            files[kind] = {"path": str(path), "size": path.stat().st_size}

    metadata = _read_json(ws / "metadata.json")
    if isinstance(metadata, dict) and metadata.get("chapters"):
        # The screen copies the description as it goes on YouTube: chapters included.
        metadata = {
            **metadata,
            "youtube_description": description_with_chapters(
                metadata.get("youtube_description") or "", metadata["chapters"]
            ),
        }
    return {
        "id": video_id,
        "video_name": p.get("video_name", video_id),
        "type": p.get("type"),
        "status": overall_status(p),
        "metadata": metadata if isinstance(metadata, dict) else None,
        "files": files,
        "token_stats": p.get("token_stats"),
    }


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


# ── Shorts derivados (read model) ─────────────────────────────────────────────


def shorts_state(video_id: str, max_duration: float = sh.DEFAULT_MAX_DURATION) -> dict | None:
    """The shorts candidates of a finished long, as the "Shorts" screen shows them.

    Mirrors `auto-edit shorts <video>` without --pick: same validation, same
    score order, same numbering. The number a candidate gets here is the one
    `cut` takes and the `_shortN` suffix of its workspace. `eligible` is False
    (with the reason) for anything that isn't a finished long; `has_plan` is
    False until the clipper ran once.
    """
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None

    state: dict = {
        "id": video_id,
        "eligible": False,
        "reason": None,
        "has_plan": False,
        "max_duration": max_duration,
        "clips": [],
        "rejected": [],
        "notes": "",
    }
    try:
        long_pipeline = sh.require_finished_long(ws)
        sh.long_source_video(ws)
    except sh.ShortsError as exc:
        state["reason"] = str(exc)
        return state
    state["eligible"] = True

    if not (ws / sh.CLIPS_PLAN_NAME).exists():
        return state
    try:
        clips, rejected = sh.load_clips_plan(ws, max_duration=max_duration)
    except (sh.ShortsError, ValueError) as exc:
        state["reason"] = f"{sh.CLIPS_PLAN_NAME} ilegível: {exc}"
        return state

    post_cut = _read_json(ws / sh.POST_CUT_NAME)
    segments = post_cut.get("segments") or [] if isinstance(post_cut, dict) else []
    overlaps = sh.overlapping_indices(clips)

    items = []
    for i, clip in enumerate(clips):
        number = i + 1
        start, end = float(clip["start"]), float(clip["end"])
        short_ws = sh.short_workspace_path(ws, long_pipeline, number)
        existing = None
        if (short_ws / "pipeline.json").exists():
            existing = {
                "id": short_ws.name,
                "status": overall_status(pl.load(short_ws)),
                "overwrite_warning": sh.overwrite_warning(ws, long_pipeline, clip, number),
            }
        items.append(
            {
                "number": number,
                "start": start,
                "end": end,
                "duration": round(end - start, 3),
                "score": clip.get("score"),
                "hook": clip.get("hook") or "",
                "reason": clip.get("reason") or clip.get("why"),
                "text": _transcript_text(segments, start, end),
                "overlaps": i in overlaps,
                "short": existing,
            }
        )

    state.update(
        has_plan=True, clips=items, rejected=rejected, notes=sh.plan_notes(ws)
    )
    return state


# ── Publicação (YouTube) ──────────────────────────────────────────────────────

# The OAuth consent runs in a background thread: it blocks until the user
# authorizes in the browser, and the frontend polls `youtube_account()`.
_yt_connect = {"status": "idle", "error": None}
_yt_lock = threading.Lock()


def youtube_account() -> dict:
    with _yt_lock:
        connecting = _yt_connect["status"] == "connecting"
        error = _yt_connect["error"]
    return {
        "connected": yt.is_connected(),
        "channel": yt.channel_title(),
        "connecting": connecting,
        "error": error,
        "has_client_secret": yt.client_config() is not None,
    }


def connect_youtube(*, connect: Callable[[], object] = yt.connect) -> dict:
    """Start the OAuth consent (opens the browser). Returns the account state."""
    with _yt_lock:
        already = _yt_connect["status"] == "connecting"
        if not already:
            _yt_connect.update(status="connecting", error=None)
    if already:  # outside the lock: youtube_account() takes it too
        return youtube_account()

    def _run() -> None:
        error = None
        try:
            connect()
        except Exception as exc:  # surfaced to the UI as-is
            error = str(exc)
        with _yt_lock:
            _yt_connect.update(status="idle", error=error)

    threading.Thread(target=_run, name="youtube-connect", daemon=True).start()
    return youtube_account()


def disconnect_youtube() -> dict:
    yt.disconnect()
    return youtube_account()


def publish_state(video_id: str) -> dict | None:
    """What the "Publicar" card shows: defaults from metadata + past publishes."""
    ws = library_root() / video_id
    if not (ws / "pipeline.json").exists():
        return None
    p = pl.load(ws)
    video = artifact_path(video_id, "video")
    reason = None
    if p.get("current_stage") != "done":
        reason = "o vídeo ainda não terminou de editar"
    elif video is None:
        reason = "o vídeo final não está em output/"
    metadata = _read_json(ws / "metadata.json")
    is_short = p.get("type") == "short"
    return {
        "id": video_id,
        "type": p.get("type"),
        "eligible": reason is None,
        "reason": reason,
        "defaults": {
            **yt.defaults(p, metadata if isinstance(metadata, dict) else None),
            "privacy": "private",
        },
        # A API não aceita thumbnail personalizada em Shorts.
        "thumbnail": not is_short and artifact_path(video_id, "thumbnail") is not None,
        "limits": {"title": yt.TITLE_MAX, "description": yt.DESCRIPTION_MAX},
        "published": yt.read_record(ws).get("youtube", []),
        "account": youtube_account(),
    }


def run_publish_youtube(
    ws: Path,
    body: dict,
    *,
    video: Path,
    thumbnail: Path | None,
    emit: Emit,
    upload: Callable[..., dict] = yt.upload,
) -> dict:
    """Upload with progress events, then record it in the workspace."""
    size_mb = video.stat().st_size / (1024 * 1024)
    emit({"type": "log", "line": f"enviando {video.name} ({size_mb:.0f} MB) pro YouTube…"})
    last = {"pct": -1}

    def progress(frac: float) -> None:
        pct = int(frac * 100)
        if pct != last["pct"]:
            last["pct"] = pct
            emit({"type": "progress", "pct": pct})

    if thumbnail is not None:
        thumbnail = yt.prepare_thumbnail(thumbnail, ws)
    res = upload(video, body, thumbnail=thumbnail, on_progress=progress)
    for warning in res.get("warnings", []):
        emit({"type": "log", "line": f"aviso: {warning}"})
    entry = {
        "video_id": res["video_id"],
        "url": res["url"],
        "title": body["snippet"]["title"],
        "privacy": body["status"]["privacyStatus"],
        "publish_at": body["status"].get("publishAt"),
        "warnings": res.get("warnings", []),
    }
    yt.add_record(ws, "youtube", entry)
    emit({"type": "done", "status": "done", "url": res["url"], "video_id": res["video_id"]})
    return entry


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
        self._queued: set[str] = set()
        self._lock = threading.Lock()

    def active_ids(self) -> set[str]:
        return self._ids_with_status("running")

    def queued_ids(self) -> set[str]:
        """Workspaces seeded and waiting for their turn (shorts cut in a row)."""
        with self._lock:
            return set(self._queued)

    def _busy(self, video_id: str) -> bool:
        if video_id in self.queued_ids():
            return True
        job = self.job_for_video(video_id)
        return job is not None and job.status == "running"

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
        cold_open: bool = False,
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
        if cold_open:
            pl.set_cold_open(ws)
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


    def find_shorts(
        self, video_id: str, *, max_duration: float = sh.DEFAULT_MAX_DURATION
    ) -> Job:
        """Run the clipper over a finished long (`auto-edit shorts <video> --replan`).

        Raises FileNotFoundError for an unknown workspace and ShortsError when
        it isn't a finished long or something is already running on it.
        """
        ws = library_root() / video_id
        if not (ws / "pipeline.json").exists():
            raise FileNotFoundError(f"no workspace for: {video_id}")
        long_pipeline = sh.require_finished_long(ws)
        sh.long_source_video(ws)
        if self._busy(video_id):
            raise sh.ShortsError(f"{video_id} já tem um job rodando")
        return self._spawn(
            video_id,
            "shorts",
            lambda emit: run_clipper(
                ws, emit=emit, max_duration=max_duration,
                language=long_pipeline.get("language", "pt"),
            ),
        )

    def cut_shorts(
        self,
        video_id: str,
        picks: list[int],
        *,
        max_duration: float = sh.DEFAULT_MAX_DURATION,
    ) -> list[str]:
        """Seed one `_shortN` workspace per picked candidate and cut them in a row.

        `picks` are the 1-based numbers `shorts_state` shows. Every workspace is
        seeded up front, so all of them show up in the library right away (as
        "queued"); they then run one at a time, like the CLI's `--pick`, since
        each one is an FFmpeg encode plus agent calls. A failed short stops the
        queue — the rest stay seeded and can be resumed from `execute`.
        """
        ws = library_root() / video_id
        if not (ws / "pipeline.json").exists():
            raise FileNotFoundError(f"no workspace for: {video_id}")
        long_pipeline = sh.require_finished_long(ws)
        clips, _rejected = sh.load_clips_plan(ws, max_duration=max_duration)
        if not clips:
            raise sh.ShortsError("nenhum candidato a short pra cortar")
        try:
            numbers = sorted({int(n) for n in picks})
        except (TypeError, ValueError):
            raise sh.ShortsError("pick precisa ser uma lista de números") from None
        if not numbers:
            raise sh.ShortsError("escolha pelo menos um candidato")
        bad = [n for n in numbers if n < 1 or n > len(clips)]
        if bad:
            raise sh.ShortsError(f"fora da faixa: {bad}. Válidos: 1-{len(clips)}")

        targets = [sh.short_workspace_path(ws, long_pipeline, n) for n in numbers]
        busy = [t.name for t in targets if self._busy(t.name)]
        if busy:
            raise sh.ShortsError(f"já rodando: {', '.join(busy)}")

        seeded = [
            sh.seed_short_workspace(ws, long_pipeline, clips[n - 1], n) for n in numbers
        ]
        language = long_pipeline.get("language", "pt")
        with self._lock:
            self._queued.update(w.name for w in seeded)

        def _run_queue() -> None:
            stopped = False
            for short_ws in seeded:
                with self._lock:
                    self._queued.discard(short_ws.name)
                if stopped:
                    continue
                job = self._spawn(
                    short_ws.name,
                    "short",
                    lambda emit, w=short_ws: run_workspace(w, language=language, emit=emit),
                )
                for _ev in job.subscribe():  # block until this short is done
                    pass
                stopped = job.status == "failed"

        threading.Thread(target=_run_queue, name=f"shorts-{video_id}", daemon=True).start()
        return [w.name for w in seeded]


    def publish_youtube(self, video_id: str, fields: dict, *, force: bool = False) -> Job:
        """Upload a finished video to YouTube as a job (progress over SSE).

        Raises FileNotFoundError for an unknown workspace and PublishError for
        anything the user has to fix (not done, not connected, bad fields,
        already published without `force`, busy).
        """
        ws = library_root() / video_id
        if not (ws / "pipeline.json").exists():
            raise FileNotFoundError(f"no workspace for: {video_id}")
        state = publish_state(video_id)
        if not state["eligible"]:
            raise yt.PublishError(state["reason"])
        if not yt.is_connected():
            raise yt.PublishError("YouTube não conectado. Conecte a conta antes de publicar.")
        if state["published"] and not force:
            raise yt.PublishError("este vídeo já foi enviado pro YouTube")
        if self._busy(video_id):
            raise yt.PublishError(f"{video_id} já tem um job rodando")

        p = pl.load(ws)
        body = yt.build_body(
            title=fields.get("title", ""),
            description=fields.get("description", ""),
            tags=fields.get("tags") or [],
            privacy=fields.get("privacy") or "private",
            publish_at=fields.get("publish_at") or None,
            language=p.get("language"),
        )
        video = artifact_path(video_id, "video")
        thumbnail = artifact_path(video_id, "thumbnail") if state["thumbnail"] else None
        return self._spawn(
            video_id,
            "publish",
            lambda emit: run_publish_youtube(ws, body, video=video, thumbnail=thumbnail, emit=emit),
        )


# ── Pipeline runner (streams ralph.sh) ────────────────────────────────────────


def _ralph_env(ralph: Path, language: str) -> dict:
    env = os.environ.copy()
    env["AUTO_EDIT_REPO_ROOT"] = str(ralph.parent.resolve())
    env["AUTO_EDIT_LANGUAGE"] = language
    env.setdefault("AUTO_EDIT_LLM", "claude")
    env["PYTHON"] = os.environ.get("PYTHON", sys.executable)
    return env


def run_clipper(
    ws: Path,
    *,
    emit: Emit,
    max_duration: float = sh.DEFAULT_MAX_DURATION,
    language: str = "pt",
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    """Run the clipper agent over a finished long, writing its clips_plan.json.

    Same invocation as `auto-edit shorts --replan`. Emits log lines, then
    done/error. `popen` is injectable for tests.
    """
    ralph = ralph_path()
    if not ralph.exists():
        emit({"type": "error", "message": f"ralph.sh not found at {ralph}"})
        return 1

    env = _ralph_env(ralph, language)
    env["AUTO_EDIT_CLIP_MAX_DUR"] = f"{max_duration:g}"
    proc = popen(
        [
            "bash", str(ralph), "--agent", str(ws.resolve()),
            "clip", str((ws / sh.CLIPS_PLAN_NAME).resolve()),
            str(ralph.parent / "agents" / "clipper.md"),
        ],
        cwd=str(ralph.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is not None:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line:
                emit({"type": "log", "line": line})

    rc = proc.wait()
    if rc == 0:
        emit({"type": "done", "status": "done"})
    else:
        emit({"type": "error", "status": "failed", "message": "o clipper falhou"})
    return rc


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

    env = _ralph_env(ralph, language)
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
