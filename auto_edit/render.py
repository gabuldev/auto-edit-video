"""The React renderer (`renderer/`, compiled into `auto-edit-render`).

Shared by the thumbnail and the overlay stages: where the executable is, and
the brand (name, handle, accent) the overlays draw.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from auto_edit import overlay_assets

TIMEOUT = 300
DEFAULT_ACCENT = (0, 214, 255)


def command() -> list[str] | None:
    """`auto-edit-render` (shipped in the app's bin/, on PATH), or the source
    run with bun in a dev checkout. None when neither is there."""
    explicit = os.environ.get("AUTO_EDIT_RENDER_BIN")
    if explicit:
        return [explicit]
    found = shutil.which("auto-edit-render")
    if found:
        return [found]
    src = overlay_assets.default_repo_root() / "renderer"
    bun = shutil.which("bun") or str(Path.home() / ".bun" / "bin" / "bun")
    if Path(bun).is_file() and (src / "node_modules").is_dir():
        return [bun, "run", str(src / "src" / "cli.tsx")]
    return None


def fonts_dir() -> Path:
    return overlay_assets.default_repo_root() / "assets" / "fonts"


def _accent(value) -> tuple[int, int, int]:
    if isinstance(value, str):
        h = value.strip().lstrip("#")
        if len(h) == 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                pass
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            pass
    return DEFAULT_ACCENT


def brand() -> dict:
    """Name, handle and accent for the overlays: settings ("brand"), then the
    connected YouTube channel's name. Name may be None — then there is no
    lower third to draw."""
    from auto_edit import settings

    saved = settings.load().get("brand") or {}
    name = (saved.get("name") or "").strip() or None
    if name is None:
        try:
            from auto_edit import youtube_auth
            name = youtube_auth.channel_title()
        except Exception:
            name = None
    handle = (saved.get("handle") or "").strip() or None
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"
    return {"name": name, "handle": handle, "accent": list(_accent(saved.get("accent")))}
