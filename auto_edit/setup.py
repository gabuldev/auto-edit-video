"""First run on a machine with nothing on it: is the app ready to edit, and
what's missing — an agent CLI, or the Whisper model.

The installed app brings Python, FFmpeg and (on Windows) bash. What it can't
bring is the agent: the user installs and logs in to it. And Whisper
downloads its model (~460 MB for "small") on first use, which made the first
edit look frozen — here it downloads up front, with progress.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from auto_edit import agents

# Official one-line installers, run in a visible terminal so the user sees
# what happens (and answers any prompt). None → the agent's download page.
INSTALL = {
    "claude": {
        "posix": "curl -fsSL https://claude.ai/install.sh | bash",
        "win32": "powershell -NoExit -ExecutionPolicy Bypass -Command \"irm https://claude.ai/install.ps1 | iex\"",
    },
    "opencode": {"posix": "curl -fsSL https://opencode.ai/install | bash", "win32": None},
    "ollama": {"posix": None, "win32": None},  # a desktop app: the download page
    "agy": {"posix": None, "win32": None},
    "cursor": {"posix": None, "win32": None},
}

WHISPER_SIZES_MB = {"tiny": 75, "base": 142, "small": 466, "medium": 1530, "large": 2950,
                    "large-v3": 2950, "turbo": 1550}


def install_command(name: str) -> str | None:
    by_os = INSTALL.get(name) or {}
    return by_os.get("win32" if sys.platform == "win32" else "posix")


def open_install(name: str, run=None) -> dict:
    """Run the official installer in a terminal, or open the download page."""
    from auto_edit import agent_status, engine

    command = install_command(name)
    if command is None:
        url = agents.AGENTS[name].docs
        engine.open_url(url)
        return {"opened": url}
    agent_status.open_terminal(command, **({"run": run} if run else {}))
    return {"command": command}


# ── whisper ───────────────────────────────────────────────────────────────────


def whisper_cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"


def _model_file(model: str) -> Path:
    return whisper_cache() / f"{model}.pt"


_download: dict = {"model": None, "status": "idle", "error": None}


def whisper_state(model: str) -> dict:
    path = _model_file(model)
    expected = WHISPER_SIZES_MB.get(model, 0) * 1_000_000
    have = path.stat().st_size if path.exists() else 0
    downloading = _download["status"] == "downloading" and _download["model"] == model
    ready = path.exists() and not downloading and (not expected or have >= expected * 0.95)
    return {
        "model": model,
        "ready": ready,
        "downloading": downloading,
        "progress": round(min(1.0, have / expected), 3) if expected and downloading else (1.0 if ready else 0.0),
        "size_mb": WHISPER_SIZES_MB.get(model),
        "error": _download["error"] if _download["model"] == model else None,
    }


def download_whisper(model: str, load=None) -> dict:
    """Fetch the model in the background (whisper's own downloader, checksum
    included). Progress is the size of the file being written."""
    if _download["status"] == "downloading":
        return whisper_state(model)
    _download.update(model=model, status="downloading", error=None)

    def _go() -> None:
        try:
            if load is not None:
                load(model)
            else:
                import whisper

                whisper._download(whisper._MODELS[model], str(whisper_cache()), in_memory=False)
            _download["status"] = "done"
        except Exception as exc:  # shown in the UI
            _download.update(status="error", error=str(exc))

    threading.Thread(target=_go, name=f"whisper-{model}", daemon=True).start()
    return whisper_state(model)


# ── overall ───────────────────────────────────────────────────────────────────


def state() -> dict:
    from auto_edit import agent_status, settings

    saved = settings.load()
    statuses = agent_status.all_status()
    primary = saved["agent"]["primary"]
    installed = [s["name"] for s in statuses if s["installed"] and (s["name"] != "ollama" or s.get("models"))]
    whisper = whisper_state(saved["whisper_model"])
    verified = saved.get("verified_agent")
    return {
        "agents": statuses,
        "primary": primary,
        "installed": installed,
        "agent_ready": bool(verified and verified in installed),
        "verified_agent": verified,
        "whisper": whisper,
        "ready": bool(verified and verified in installed) and whisper["ready"],
        "install_commands": {name: install_command(name) for name in agents.AGENTS},
        "platform": sys.platform,
    }
