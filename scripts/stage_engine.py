"""Stage the engine the desktop app ships with: a portable Python with
auto-edit installed, the pipeline files, and an FFmpeg with libass.

Whoever downloads the app shouldn't have to install Python or FFmpeg. The
pipeline isn't a single executable — ralph.sh calls `python -m auto_edit…`
and tools/*.py throughout — so the app carries a whole relocatable Python
(python-build-standalone) instead of a frozen binary.

    python scripts/stage_engine.py --target aarch64-apple-darwin --out desktop/src-tauri/engine

Layout of --out:

    python/          portable CPython 3.12 with auto-edit[api] + Whisper + torch (CPU)
    repo/            ralph.sh, agents/, tools/, assets/, auto_edit/ (AUTO_EDIT_REPO_ROOT)
    bin/             ffmpeg, ffprobe (with libass: captions need the subtitles filter)

Not included: the agent CLI (claude, agy, …) — the user installs and logs in
to that (Settings). On Windows ralph.sh still needs bash (Git for Windows).
Fails loudly if anything that the pipeline needs doesn't work in the result.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_SERIES = "3.12"
PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
TORCH_CPU = "https://download.pytorch.org/whl/cpu"

FFMPEG = {
    "x86_64-unknown-linux-gnu": [
        ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz", None),
    ],
    "x86_64-pc-windows-msvc": [
        ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip", None),
    ],
    "aarch64-apple-darwin": [
        ("https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip", "ffmpeg"),
        ("https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip", "ffprobe"),
    ],
    "x86_64-apple-darwin": [
        ("https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffmpeg.zip", "ffmpeg"),
        ("https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffprobe.zip", "ffprobe"),
    ],
}

REPO_FILES = ["ralph.sh", "agents", "tools", "assets", "auto_edit", "pyproject.toml", "LICENSE"]


def log(msg: str) -> None:
    print(f"[stage-engine] {msg}", flush=True)


def fetch(url: str) -> bytes:
    headers = {"User-Agent": "auto-edit-stage-engine"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        # Unauthenticated API calls share a small per-IP quota on CI runners.
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def python_url(target: str) -> str:
    release = json.loads(fetch(PBS_API))
    suffix = f"-{target}-install_only_stripped.tar.gz"
    for asset in release["assets"]:
        name = asset["name"]
        if name.startswith(f"cpython-{PY_SERIES}.") and name.endswith(suffix):
            return asset["browser_download_url"]
    raise SystemExit(f"no python-build-standalone {PY_SERIES} asset for {target}")


def python_exe(out: Path, target: str) -> Path:
    if "windows" in target:
        return out / "python" / "python.exe"
    return out / "python" / "bin" / "python3"


def stage_python(out: Path, target: str) -> Path:
    url = python_url(target)
    log(f"python: {url.rsplit('/', 1)[-1]}")
    with tarfile.open(fileobj=io.BytesIO(fetch(url)), mode="r:gz") as tar:
        tar.extractall(out, filter="data")  # -> out/python
    return python_exe(out, target)


def pip(py: Path, *args: str, rosetta: bool = False) -> None:
    cmd = [str(py), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", *args]
    if rosetta:  # Intel macOS app built on an Apple Silicon runner
        cmd = ["arch", "-x86_64", *cmd]
    log(" ".join(cmd[cmd.index("install"):]))
    subprocess.run(cmd, check=True)


def stage_packages(py: Path, target: str) -> None:
    rosetta = target == "x86_64-apple-darwin" and sys.platform == "darwin" and _arm_host()
    if "linux" in target or "windows" in target:
        # The default torch wheels on Linux/Windows carry CUDA (~2.5 GB). Whisper
        # runs on CPU here; the CPU build is a fraction of that.
        pip(py, "torch", "--index-url", TORCH_CPU)
    pip(py, f"{ROOT}[api]", rosetta=rosetta)


def _arm_host() -> bool:
    import platform

    return platform.machine() in ("arm64", "aarch64")


def stage_repo(out: Path) -> None:
    repo = out / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    for name in REPO_FILES:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, repo / name, ignore=ignore, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, repo / name)
    log(f"repo files -> {repo}")


def stage_ffmpeg(out: Path, target: str) -> None:
    bindir = out / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    exe = ".exe" if "windows" in target else ""
    for url, single in FFMPEG[target]:
        log(f"ffmpeg: {url}")
        data = fetch(url)
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    base = Path(member).name
                    if base in (f"ffmpeg{exe}", f"ffprobe{exe}") and (single is None or base.startswith(single)):
                        (bindir / base).write_bytes(zf.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
                for member in tar.getmembers():
                    base = Path(member.name).name
                    if base in ("ffmpeg", "ffprobe") and member.isfile():
                        (bindir / base).write_bytes(tar.extractfile(member).read())
    for tool in bindir.iterdir():
        tool.chmod(0o755)


def verify(out: Path, py: Path, target: str) -> None:
    """Everything the pipeline needs must work in the staged engine."""
    exe = ".exe" if "windows" in target else ""
    ffmpeg = out / "bin" / f"ffmpeg{exe}"
    checks = [
        ([str(py), "-c", "import auto_edit, whisper, torch, flask, numpy; print('imports ok', torch.__version__)"], "python imports"),
        ([str(py), "-m", "auto_edit.cli", "--version"], "auto-edit CLI"),
        ([str(ffmpeg), "-hide_banner", "-filters"], "ffmpeg"),
    ]
    for cmd, label in checks:
        if target == "x86_64-apple-darwin" and _arm_host():
            cmd = ["arch", "-x86_64", *cmd]  # Rosetta
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"{label} failed:\n{res.stdout[-800:]}\n{res.stderr[-800:]}")
        if label == "ffmpeg" and " subtitles " not in res.stdout:
            raise SystemExit("ffmpeg has no libass (subtitles filter) — captions would fail")
        said = (res.stdout or res.stderr).strip().splitlines()
        detail = "libass" if label == "ffmpeg" else (said[-1] if said else "rc 0")
        log(f"ok: {label} ({detail})")


def size(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1e6:.0f} MB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=sorted(FFMPEG))
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    py = stage_python(out, args.target)
    stage_packages(py, args.target)
    stage_repo(out)
    stage_ffmpeg(out, args.target)
    verify(out, py, args.target)
    log(f"engine staged in {out} ({size(out)})")


if __name__ == "__main__":
    main()
