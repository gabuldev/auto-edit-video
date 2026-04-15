"""
Download thumbnail fonts from GitHub (google/fonts repo) and other free sources.
Saves to assets/thumbnails/fonts/ — idempotent, skips existing files.

Usage: python tools/download_fonts.py [--repo-root <path>]
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

# ── Font sources ────────────────────────────────────────────────────────────
# All fonts are OFL (Open Font License) — free for commercial use.
# Downloaded from github.com/google/fonts (canonical mirror).

FONTS = [
    {
        "name": "BebasNeue-Regular",
        "url": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
        "filename": "BebasNeue-Regular.ttf",
        "desc": "Tall condensed display — great for thumbnails",
    },
    {
        "name": "Anton-Regular",
        "url": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
        "filename": "Anton-Regular.ttf",
        "desc": "Heavy impact style",
    },
    {
        "name": "Oswald-Bold",
        "url": "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
        "filename": "Oswald-Variable.ttf",
        "desc": "Clean condensed (variable weight, supports bold)",
    },
    {
        "name": "Montserrat-ExtraBold",
        "url": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
        "filename": "Montserrat-Variable.ttf",
        "desc": "Modern geometric (variable weight, supports extra-bold)",
    },
    {
        "name": "ProtestGuerrilla",
        "url": "https://github.com/google/fonts/raw/main/ofl/protestguerrilla/ProtestGuerrilla-Regular.ttf",
        "filename": "ProtestGuerrilla-Regular.ttf",
        "desc": "Bold display — similar to Prohibition/CapCut style",
    },
]


def _repo_root() -> Path:
    env = os.environ.get("AUTO_EDIT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _download(url: str, desc: str) -> bytes:
    """Download URL with a simple progress indicator."""
    print(f"  Downloading {desc}...", end=" ", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "auto-edit-video/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        print("OK")
        return data
    except Exception as e:
        print(f"FAILED ({e})")
        return b""


def download_font(font: dict, dest_dir: Path) -> bool:
    """Download a single font file. Skips if already exists."""
    dest = dest_dir / font["filename"]
    if dest.exists():
        print(f"  [skip] {font['filename']} — already exists")
        return True

    data = _download(font["url"], f"{font['name']} ({font['desc']})")
    if not data:
        return False

    dest.write_bytes(data)
    print(f"  [ok] {font['filename']}")
    return True


def download_all(dest_dir: Path | None = None) -> int:
    """Download all thumbnail fonts. Returns count of fonts available."""
    if dest_dir is None:
        dest_dir = _repo_root() / "assets" / "thumbnails" / "fonts"

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"[fonts] Downloading thumbnail fonts to {dest_dir}")
    count = 0

    for font in FONTS:
        if download_font(font, dest_dir):
            count += 1

    existing = list(dest_dir.glob("*.ttf")) + list(dest_dir.glob("*.otf"))
    print(f"[fonts] {len(existing)} fonts available in {dest_dir}")
    return len(existing)


if __name__ == "__main__":
    root = None
    if "--repo-root" in sys.argv:
        idx = sys.argv.index("--repo-root")
        if idx + 1 < len(sys.argv):
            root = Path(sys.argv[idx + 1]) / "assets" / "thumbnails" / "fonts"

    download_all(root)
