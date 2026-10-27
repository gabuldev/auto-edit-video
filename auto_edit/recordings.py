"""Biblioteca: the recordings in the inbox (Configurações → Pastas), with what
the person needs to pick one — length, shape, size, date, which subfolder —
and whether it was already edited.

ffprobe is the slow part, so each file's media info is cached by path, size
and modification time: a folder is only probed once, new files as they come.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from auto_edit import config as cfg

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts"}
MAX_DEPTH = 3  # subfolders walked below the inbox
MAX_FILES = 1000  # newest first beyond this; a folder that big is an archive, not an inbox
THUMB_WIDTH = 320

_lock = threading.Lock()


def _key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


# ── scanning ──────────────────────────────────────────────────────────────────

def scan(root: Path, max_depth: int = MAX_DEPTH) -> list[Path]:
    """Video files under `root`, subfolders included down to `max_depth`.
    Hidden folders/files are skipped; unreadable folders are too."""
    found: list[Path] = []
    pending = [(root, 0)]
    while pending:
        folder, depth = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        pending.append((Path(entry.path), depth + 1))
                elif Path(entry.name).suffix.lower() in VIDEO_EXTS:
                    found.append(Path(entry.path))
            except OSError:
                continue
    return found


# ── media info (ffprobe, cached) ──────────────────────────────────────────────

def parse_probe(payload: str) -> dict:
    """{duration, width, height} from ffprobe's JSON, as the video displays:
    a phone records landscape with a 90° rotation for a portrait clip."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    stream = (data.get("streams") or [{}])[0]
    width, height = stream.get("width"), stream.get("height")
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = side["rotation"]
    rotation = rotation or (stream.get("tags") or {}).get("rotate") or 0
    try:
        if width and height and abs(int(float(rotation))) % 180 == 90:
            width, height = height, width
    except (TypeError, ValueError):
        pass
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    out = {"duration": duration}
    if width and height:
        out.update(width=int(width), height=int(height))
    return out


def probe_media(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format=duration",
        "-of", "json", str(path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_probe(res.stdout) if res.returncode == 0 else {}


def _cache_file() -> Path:
    return cfg.home_dir() / "cache" / "recordings.json"


def _load_cache() -> dict:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    path = _cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # a cache that can't be written just means probing again next time


def media_info(files: list[tuple[Path, os.stat_result]], probe=None) -> dict[str, dict]:
    """Media info per file key; cached ones reused, the rest probed in parallel."""
    probe = probe or probe_media
    with _lock:
        cache = _load_cache()
        wanted, fresh = {}, {}
        for path, st in files:
            key = _key(path)
            hit = cache.get(key)
            if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime:
                fresh[key] = hit["info"]
            else:
                wanted[key] = (path, st)
        if wanted:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = pool.map(lambda item: (item[0], probe(item[1][0])), wanted.items())
                for key, info in results:
                    path, st = wanted[key]
                    fresh[key] = info
                    cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "info": info}
            _save_cache(cache)
        return fresh


# ── the listing ───────────────────────────────────────────────────────────────

def listing(root: Path, edits: dict[str, list[dict]] | None = None, probe=None) -> dict:
    """The Biblioteca screen: every recording under `root`, newest first.

    `edits` maps a source file's key (see `source_key`) to the edits made
    from it, so each recording says whether — and where — it was edited.
    """
    edits = edits or {}
    if not root.is_dir():
        return {"folder": str(root), "exists": False, "recordings": [], "truncated": False}
    files = []
    for path in scan(root):
        try:
            files.append((path, path.stat()))
        except OSError:
            continue
    files.sort(key=lambda item: item[1].st_mtime, reverse=True)
    truncated = len(files) > MAX_FILES
    files = files[:MAX_FILES]
    info = media_info(files, probe=probe)
    out = []
    for path, st in files:
        key = _key(path)
        folder = path.parent.relative_to(root).as_posix()
        out.append({
            "name": path.name,
            "path": str(path),
            "folder": "" if folder == "." else folder,
            "ext": path.suffix.lstrip(".").lower(),
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            **info.get(key, {}),
            "edits": edits.get(key, []),
        })
    return {"folder": str(root), "exists": True, "recordings": out, "truncated": truncated}


def source_key(video_path: str | None) -> str | None:
    """The key a workspace's source video is matched by (same as a listing's)."""
    if not video_path:
        return None
    try:
        return _key(Path(video_path))
    except OSError:
        return None


# ── thumbnails ────────────────────────────────────────────────────────────────

def thumbnail(path: Path, *, run=subprocess.run) -> Path | None:
    """A small JPEG frame of the recording, cached; None when ffmpeg can't."""
    st = path.stat()
    digest = hashlib.sha1(f"{_key(path)}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:20]
    out = cfg.home_dir() / "cache" / "thumbs" / f"{digest}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    for at in ("1", "0"):  # a clip under a second has no frame at 1s
        cmd = [
            "ffmpeg", "-v", "error", "-y", "-ss", at, "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "5", str(out),
        ]
        try:
            run(cmd, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.is_file() and out.stat().st_size > 0:
            return out
    return None
