"""Is each agent CLI installed, which version, does it answer — and how to
log in. Feeds the Settings screen (`/api/agents`).

"Logged in" is never guessed from config files (every CLI keeps them in its
own format, and they change): `test()` sends a tiny real prompt and reports
what happened. That is the only answer that matches what the pipeline will
see.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from auto_edit import agents

TEST_PROMPT = 'Responda APENAS com o JSON {"ok": true}. Nada mais.'
TEST_TIMEOUT = 120.0


def _version(binary: str) -> str | None:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[-1][:60] if text else None


def status(name: str) -> dict:
    agent = agents.AGENTS[name]
    info: dict = {
        "name": name,
        "label": agent.label,
        "docs": agent.docs,
        "login_command": agent.login_command,
        "installed": False,
        "path": None,
        "version": None,
    }
    if name == "ollama":
        info.update(_ollama_status())
        return info
    binary = agents.find_binary(agent)
    if binary:
        info.update(installed=True, path=binary, version=_version(binary))
    return info


def _ollama_status() -> dict:
    binary = agents.find_binary(agents.AGENTS["ollama"])
    out = {"installed": bool(binary), "path": binary, "version": _version(binary) if binary else None,
           "server": False, "models": [], "pulling": dict(_pulls)}
    try:
        out["models"] = agents.ollama_models()
        out["server"] = True
    except agents.AgentError:
        pass
    return out


def all_status() -> list[dict]:
    return [status(name) for name in agents.AGENTS]


# ── test ──────────────────────────────────────────────────────────────────────


def _run_claude(prompt: str, model: str | None, timeout: float) -> str:
    binary = agents.find_binary(agents.AGENTS["claude"])
    if not binary:
        raise agents.AgentError("claude não encontrado")
    cmd = [binary, "-p"] + (["--model", model] if model else [])
    return agents._run(cmd, prompt, timeout)


def _run_cursor(prompt: str, model: str | None, timeout: float) -> str:
    from auto_edit import runner

    with tempfile.TemporaryDirectory(prefix="auto-edit-test-") as d:
        p, o = Path(d) / "p.txt", Path(d) / "o.txt"
        p.write_text(prompt, encoding="utf-8")
        env_model = os.environ.get("AUTO_EDIT_CURSOR_MODEL")
        if model:
            os.environ["AUTO_EDIT_CURSOR_MODEL"] = model
        try:
            rc = runner.invoke_cursor(p, o, Path(d))
        finally:
            if model:
                if env_model is None:
                    os.environ.pop("AUTO_EDIT_CURSOR_MODEL", None)
                else:
                    os.environ["AUTO_EDIT_CURSOR_MODEL"] = env_model
        text = o.read_text(encoding="utf-8") if o.exists() else ""
        if rc != 0:
            raise agents.AgentError(text[-400:] or f"cursor saiu com {rc}")
        return text


def test(name: str, model: str | None = None, timeout: float = TEST_TIMEOUT) -> dict:
    """Send a tiny prompt through the same path the pipeline uses."""
    started = time.monotonic()
    try:
        if name == "claude":
            text = _run_claude(TEST_PROMPT, model, timeout)
        elif name == "cursor":
            text = _run_cursor(TEST_PROMPT, model, timeout)
        else:
            prompt = (agents.TEXT_ONLY + TEST_PROMPT) if name in agents.AGENTIC else TEST_PROMPT
            text = agents.RUNNERS[name](prompt, model=model, timeout=timeout)
    except agents.AgentError as exc:
        return {"name": name, "ok": False, "seconds": round(time.monotonic() - started, 1), "error": str(exc)}
    ok = '"ok"' in text and "true" in text
    return {
        "name": name,
        "ok": ok,
        "seconds": round(time.monotonic() - started, 1),
        "answer": text.strip()[:200],
        **({} if ok else {"error": "respondeu, mas não o que foi pedido — veja a resposta"}),
    }


# ── login ─────────────────────────────────────────────────────────────────────


def login_command(name: str) -> str | None:
    agent = agents.AGENTS[name]
    if not agent.login_command:
        return None
    binary = agents.find_binary(agent)
    if not binary:
        return None
    rest = agent.login_command.split(" ", 1)[1:]  # "cursor-agent login" → ["login"]
    return " ".join([shlex.quote(binary), *rest])


def open_login(name: str, run=subprocess.Popen) -> str:
    """Open a terminal running the CLI's login — those are interactive TUIs
    that can't run inside the app. Returns the command shown to the user."""
    command = login_command(name)
    if command is None:
        raise agents.AgentError(f"{name} não está instalado ou não tem login")
    if sys.platform == "darwin":
        script = f'tell application "Terminal" to do script {json.dumps(command)}\ntell application "Terminal" to activate'
        run(["osascript", "-e", script])
    elif sys.platform == "win32":
        run(["cmd", "/c", "start", "cmd", "/k", command])
    else:
        run(["x-terminal-emulator", "-e", "bash", "-lc", f"{command}; exec bash"])
    return command


# ── ollama pull ───────────────────────────────────────────────────────────────

_pulls: dict[str, str] = {}  # model → "downloading" | "done" | "error: …"


def pull(model: str, run=subprocess.run) -> None:
    """`ollama pull <model>` in the background; progress shows in status()."""
    binary = agents.find_binary(agents.AGENTS["ollama"])
    if not binary:
        raise agents.AgentError("ollama não está instalado")
    if _pulls.get(model) == "downloading":
        return
    _pulls[model] = "downloading"

    def _go() -> None:
        proc = run([binary, "pull", model], capture_output=True, text=True)
        _pulls[model] = "done" if proc.returncode == 0 else f"error: {(proc.stderr or '').strip()[-200:]}"

    threading.Thread(target=_go, name=f"ollama-pull-{model}", daemon=True).start()
