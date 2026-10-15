"""The React renderer (`renderer/`, compiled into `auto-edit-render`).

Shared by the thumbnail and the overlay stages: where the executable is, and
the brand (name, handle, logo) the overlays draw.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from auto_edit import overlay_assets

TIMEOUT = 300


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


def brand() -> dict:
    """Name, handle and logo for the overlays: settings ("brand"), then the
    connected YouTube channel's name. Name may be None — then there is no
    lower third to draw. Colors live in the style (auto_edit.styles)."""
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
    logo = saved.get("logo")
    logo = logo if logo and Path(logo).is_file() else None
    return {"name": name, "handle": handle, "logo": logo, "logo_bg": saved.get("logo_bg") or None}


LOGO_MAX_BYTES = 5 * 1024 * 1024
_LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def save_logo(data_url: str | None) -> str | None:
    """Store the brand's logo (a data: URL from the app) under the home and
    point settings at it; None removes it. Returns the saved path."""
    import base64
    import re

    from auto_edit import config as cfg
    from auto_edit import settings

    folder = cfg.home_dir() / "brand"
    for old in folder.glob("logo.*") if folder.is_dir() else []:
        old.unlink()
    if not data_url:
        settings.save({"brand": {"logo": None}})
        return None
    m = re.fullmatch(r"data:(image/[a-z]+);base64,([A-Za-z0-9+/=\s]+)", data_url.strip())
    if not m or m.group(1) not in _LOGO_TYPES:
        raise ValueError("envie uma imagem PNG, JPG ou WebP")
    data = base64.b64decode(m.group(2))
    if len(data) > LOGO_MAX_BYTES:
        raise ValueError("imagem grande demais (máx. 5 MB)")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"logo{_LOGO_TYPES[m.group(1)]}"
    path.write_bytes(data)
    settings.save({"brand": {"logo": str(path)}})
    return str(path)
