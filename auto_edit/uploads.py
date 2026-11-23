"""Resumable uploads into the inbox: a phone sends a recording over Wi-Fi (#146).

A video of several GB can't count on one request surviving: the phone sleeps,
the Wi-Fi drops. So the upload is a file that grows by chunks, each sent at
the offset the engine already has:

    POST   /api/uploads            {name, size}       → {id, offset: 0, ...}
    PUT    /api/uploads/<id>?offset=N  <bytes>        → {offset: N + len, ...}
    GET    /api/uploads/<id>                          → where it stopped (to resume)
    DELETE /api/uploads/<id>                          → gives up

A chunk at the wrong offset is refused (409, with the right one), so a resent
chunk never duplicates bytes. The partial file sits in a hidden folder of the
inbox (same disk: finishing is a rename, not a copy of GBs). When the last
byte arrives it moves to ``<inbox>/Celular/<name>`` (``name (2).mp4`` if
taken) and the upload answers ``done`` with the path, ready for /api/edit.
Partials untouched for a week are dropped.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path

from auto_edit import engine

FOLDER = ".auto-edit-uploads"
DEST = "Celular"
MAX_SIZE = 200 * 1024**3  # 200 GB: a typo guard, not a quota
STALE_SEC = 7 * 24 * 3600
COPY_BUF = 1024 * 1024

_lock = threading.Lock()


class UploadError(ValueError):
    def __init__(self, message: str, status: int = 400, state: dict | None = None):
        super().__init__(message)
        self.status = status
        self.state = state


def _dir() -> Path:
    d = engine.inbox_root() / FOLDER
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{24}", upload_id or ""):
        raise UploadError("upload não encontrado", 404)
    return _dir() / f"{upload_id}.json"


def _load(upload_id: str) -> dict:
    try:
        return json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UploadError("upload não encontrado", 404) from None


def _save(meta: dict) -> None:
    _meta_path(meta["id"]).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _part(upload_id: str) -> Path:
    return _dir() / f"{upload_id}.part"


def _state(meta: dict) -> dict:
    done = meta.get("path") is not None
    offset = meta["size"] if done else (_part(meta["id"]).stat().st_size if _part(meta["id"]).exists() else 0)
    return {
        "id": meta["id"],
        "name": meta["name"],
        "size": meta["size"],
        "offset": offset,
        "done": done,
        "path": meta.get("path"),
    }


def safe_name(name: str) -> str:
    """The file name the phone gave, without folders or odd characters."""
    base = Path(str(name or "").replace("\\", "/")).name.strip()
    base = re.sub(r'[\x00-\x1f<>:"|?*]', "_", base).lstrip(".")
    return base[:120]


def _cleanup() -> None:
    now = time.time()
    for meta in _dir().glob("*.json"):
        try:
            if now - meta.stat().st_mtime > STALE_SEC:
                part = meta.with_suffix(".part")
                part.unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
        except OSError:
            pass


def create(name: str, size) -> dict:
    clean = safe_name(name)
    if not clean or Path(clean).suffix.lower() not in engine.VIDEO_EXTS:
        raise UploadError(f"não é um vídeo: {name!r}")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_SIZE:
        raise UploadError("tamanho inválido")
    with _lock:
        _cleanup()
        meta = {"id": secrets.token_hex(12), "name": clean, "size": size, "path": None,
                "created_at": time.time()}
        _save(meta)
        _part(meta["id"]).touch()
        return _state(meta)


def get(upload_id: str) -> dict:
    return _state(_load(upload_id))


def append(upload_id: str, offset, stream, length: int | None) -> dict:
    """Write a chunk at ``offset`` (it must be where the file ends)."""
    with _lock:
        meta = _load(upload_id)
        state = _state(meta)
        if state["done"]:
            raise UploadError("upload já terminou", 409, state)
        if not isinstance(offset, int) or offset != state["offset"]:
            raise UploadError(f"offset errado: o motor tem {state['offset']} bytes", 409, state)
        if length is not None and offset + length > meta["size"]:
            raise UploadError("passa do tamanho anunciado", 400, state)
        part = _part(upload_id)
        written = 0
        with part.open("ab") as f:
            while True:
                chunk = stream.read(COPY_BUF)
                if not chunk:
                    break
                if offset + written + len(chunk) > meta["size"]:
                    f.truncate(offset + written)
                    raise UploadError("passa do tamanho anunciado", 400, _state(meta))
                f.write(chunk)
                written += len(chunk)
        _save(meta)  # touch: a live upload isn't stale
        if offset + written == meta["size"]:
            meta["path"] = str(_finish(part, meta["name"]))
            _save(meta)
        return _state(meta)


def _finish(part: Path, name: str) -> Path:
    dest_dir = engine.inbox_root() / DEST
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    dest = dest_dir / name
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    part.replace(dest)
    return dest.resolve()


def cancel(upload_id: str) -> None:
    with _lock:
        meta = _load(upload_id)
        _part(upload_id).unlink(missing_ok=True)
        _meta_path(meta["id"]).unlink(missing_ok=True)
