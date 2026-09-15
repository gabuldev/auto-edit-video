"""
Overlay MP4 layout helpers: canonical dir is <repo>/assets/overlays/.
Optional mirror: <repo>/overlays/ — run sync-overlays to copy into assets/overlays/.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def default_repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def overlay_search_dirs(repo_root: Path | None = None) -> list[Path]:
    """Folders the overlayer searches for overlay MP4s, in priority order.

    1. ``$AUTO_EDIT_ASSETS_OVERLAYS`` — explicit override (single folder), if set.
    2. ``<repo>/assets/overlays`` — canonical location.
    3. ``<repo>/overlays`` — optional mirror (see :func:`sync_overlay_assets`).

    This is the single source of truth shared by the overlayer stage and
    ``auto-edit doctor`` so the two never drift.
    """
    override = os.environ.get("AUTO_EDIT_ASSETS_OVERLAYS")
    if override:
        return [Path(override).expanduser().resolve()]
    root = (repo_root or default_repo_root()).resolve()
    return [root / "assets" / "overlays", root / "overlays"]


def sync_overlay_assets(repo_root: Path | None = None) -> list[Path]:
    """
    Copy *.mp4 from <repo>/overlays/ into <repo>/assets/overlays/.
    Returns paths written (may overwrite existing files).
    """
    root = (repo_root or default_repo_root()).resolve()
    src = root / "overlays"
    if not src.is_dir():
        return []

    dst = root / "assets" / "overlays"
    dst.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for f in sorted(src.glob("*.mp4")):
        if not f.is_file():
            continue
        target = dst / f.name
        shutil.copy2(f, target)
        copied.append(target)
    return copied
