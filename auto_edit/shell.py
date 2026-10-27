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
            return found
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
