"""Stamp the desktop app with the package version (auto_edit/_version.py).

The release workflow bumps auto_edit/_version.py; the Tauri bundle names its
installers after tauri.conf.json's version, which sat at 0.1.0. Run before
building: `python scripts/sync_desktop_version.py [version]`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"


def package_version() -> str:
    text = (ROOT / "auto_edit" / "_version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def sync(version: str) -> None:
    conf = DESKTOP / "src-tauri" / "tauri.conf.json"
    data = json.loads(conf.read_text(encoding="utf-8"))
    data["version"] = version
    conf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pkg = DESKTOP / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["version"] = version
    pkg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cargo = DESKTOP / "src-tauri" / "Cargo.toml"
    text = cargo.read_text(encoding="utf-8")
    cargo.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1), encoding="utf-8")


if __name__ == "__main__":
    v = sys.argv[1].lstrip("v") if len(sys.argv) > 1 else package_version()
    sync(v)
    print(f"desktop app version → {v}")
