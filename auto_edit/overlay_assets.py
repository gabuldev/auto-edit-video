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
