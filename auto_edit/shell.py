"""Which bash runs ralph.sh, and paths it can read.

On Windows, `Popen(["bash", ...])` resolves "bash" through CreateProcess,
which searches System32 *before* PATH: it finds the WSL launcher
(`C:\\Windows\\System32\\bash.exe`), not the PortableGit bash the app ships.
WSL can't see `C:\\...\\ralph.sh`, prints nothing to the pipe and the edit
"finishes" without running a single stage.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_EXTENDED_PREFIX = "\\\\?\\"


def _is_wsl_launcher(path: str) -> bool:
    low = path.replace("/", "\\").lower()
    return any(part in low for part in ("\\system32\\", "\\windowsapps\\", "\\sysnative\\"))


def bash(env: dict | None = None) -> str:
    """The bash to run ralph.sh with: on Windows, the first one on PATH that
    isn't the WSL launcher (the app puts its PortableGit first)."""
    if sys.platform != "win32":
        return "bash"
    path = (env or os.environ).get("PATH", "")
    for d in path.split(os.pathsep):
        found = shutil.which("bash", path=d) if d else None
        if found and not _is_wsl_launcher(found):
            return native_path(found)
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramW6432", "")):
        cand = Path(root) / "Git" / "bin" / "bash.exe"
        if root and cand.exists():
            return str(cand)
    return "bash"


def native_path(p: str | Path) -> str:
    """Drop the Windows extended-length prefix (`\\\\?\\C:\\...`): bash and
    ffmpeg don't understand it."""
    s = str(p)
    if s.startswith(_EXTENDED_PREFIX + "UNC\\"):
        return "\\\\" + s[len(_EXTENDED_PREFIX) + 4:]
    if s.startswith(_EXTENDED_PREFIX):
        return s[len(_EXTENDED_PREFIX):]
    return s


# Paths the app hands the engine; any of them can arrive as \\?\C:\...
_PATH_VARS = ("AUTO_EDIT_REPO_ROOT", "AUTO_EDIT_FFMPEG", "AUTO_EDIT_RENDER_BIN", "PYTHON")


def native_env(env: dict) -> dict:
    """`env` with the extended-length prefix dropped from PATH and the
    engine's path variables, so bash and what it starts can use them."""
    out = dict(env)
    if "PATH" in out:
        out["PATH"] = os.pathsep.join(native_path(d) for d in out["PATH"].split(os.pathsep))
    for k in _PATH_VARS:
        if out.get(k):
            out[k] = native_path(out[k])
    return out


def probe_bash(env: dict) -> str:
    """What bash says to `echo ok`, for the error shown when ralph.sh never
    started (no output, exit 0)."""
    try:
        res = subprocess.run([bash(env), "-c", "echo ok"], env=env, capture_output=True,
                             text=True, errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return f"bash não abre: {e}"
    said = (res.stdout + res.stderr).strip().replace("\x00", "")[-300:]
    return f"bash -c 'echo ok' → rc {res.returncode}: {said or '(nada)'}"
