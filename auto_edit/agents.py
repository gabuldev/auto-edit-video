"""The agent CLIs the pipeline can drive, in one place.

ralph.sh calls the LLM stages through one of these. claude and cursor keep
their own paths (claude -p in ralph.sh, cursor via runner.invoke-cursor);
the newer ones run through `python -m auto_edit.agents invoke <name>`:

- **agy** (Antigravity CLI): the prompt goes on stdin as stream-json
  (`{"event": "user", "message": {"content": ...}}`) — its `-p` only takes
  the prompt as an argument, and a transcript does not fit on a command line.
  `--mode plan` keeps it read-only.
- **opencode**: prompt on stdin, `--format json` events out. Runs with the
  read-only `plan` agent, `--pure`, in an empty scratch directory, so an
  agent with file tools never touches the repo or the user's files.
- **ollama**: a local model, called straight through Ollama's HTTP API with
  JSON mode and a context window big enough for a transcript. Not through
  opencode: wrapped in an agent harness full of tools, a 7B local model
  answered about its tools instead of following the prompt.

Every runner returns the model's text in `output_file`; ralph.sh validates
the JSON exactly as for claude.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Agent:
    name: str
    label: str
    binaries: tuple[str, ...]
    model_env: str
    login_command: str | None  # what the user runs in a terminal to log in
    docs: str


AGENTS: dict[str, Agent] = {
    "claude": Agent("claude", "Claude Code", ("claude",), "AUTO_EDIT_CLAUDE_MODEL", "claude",
                    "https://docs.claude.com/en/docs/claude-code"),
    "cursor": Agent("cursor", "Cursor Agent", ("cursor-agent", "agent"), "AUTO_EDIT_CURSOR_MODEL",
                    "cursor-agent login", "https://cursor.com/docs/cli"),
    "agy": Agent("agy", "Antigravity", ("agy",), "AUTO_EDIT_AGY_MODEL", "agy",
                 "https://antigravity.google"),
    "opencode": Agent("opencode", "OpenCode", ("opencode",), "AUTO_EDIT_OPENCODE_MODEL",
                      "opencode auth login", "https://opencode.ai"),
    "ollama": Agent("ollama", "Ollama (local)", ("ollama",), "AUTO_EDIT_OLLAMA_MODEL", None,
                    "https://ollama.com"),
}

ALIASES = {"agent": "cursor", "antigravity": "agy"}


def normalize(name: str) -> str | None:
    key = (name or "").strip().lower()
    key = ALIASES.get(key, key)
    return key if key in AGENTS else None


def find_binary(agent: Agent) -> str | None:
    """On PATH, or in the usual per-user install spots a GUI app's PATH misses."""
    home = Path.home()
    extra = [home / ".local/bin", home / ".opencode/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    for name in agent.binaries:
        found = shutil.which(name)
        if found:
            return found
        for d in extra:
            if (d / name).is_file() and os.access(d / name, os.X_OK):
                return str(d / name)
    return None


# ── runners ───────────────────────────────────────────────────────────────────


class AgentError(RuntimeError):
    pass


def _run(cmd: list[str], stdin: str, timeout: float | None, env: dict | None = None, cwd: str | None = None) -> str:
    try:
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, env=env, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        raise AgentError(f"{cmd[0]} não respondeu em {timeout:.0f}s") from None
    if proc.returncode != 0:
        raise AgentError(f"{Path(cmd[0]).name} saiu com {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-500:]}")
    return proc.stdout


def run_agy(prompt: str, *, model: str | None = None, timeout: float | None = None, binary: str | None = None) -> str:
    binary = binary or find_binary(AGENTS["agy"])
    if not binary:
        raise AgentError("agy (Antigravity CLI) não encontrado")
    cmd = [binary, "--mode", "plan", "--input-format", "stream-json", "--output-format", "stream-json"]
    if model:
        cmd += ["--model", model]
    line = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False)
    out = _run(cmd, line + "\n", timeout)
    for raw in out.splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("event") == "result":
            result = ev.get("result") or {}
            if result.get("status") != "SUCCESS":
                raise AgentError(f"agy: {result.get('error') or result.get('status')}")
            if not (result.get("response") or "").strip():
                denied = ", ".join(a.get("display_name", "?") for a in result.get("denied_actions") or [])
                raise AgentError("agy terminou sem resposta" + (f" (tentou usar: {denied})" if denied else ""))
            return result["response"]
    raise AgentError("agy terminou sem resultado")


OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"
OLLAMA_CONTEXT = int(os.environ.get("AUTO_EDIT_OLLAMA_CTX", "32768"))


def _ollama(path: str, body: dict | None = None, timeout: float | None = 10) -> dict:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{OLLAMA_URL}{path}", data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AgentError(f"Ollama: {exc.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise AgentError(f"Ollama não está rodando em {OLLAMA_URL} ({exc})") from None


def ollama_models() -> list[str]:
    return [m["name"] for m in _ollama("/api/tags").get("models", [])]


def run_ollama(prompt: str, *, model: str | None = None, timeout: float | None = None, binary: str | None = None) -> str:
    if not model:
        models = ollama_models()
        if not models:
            raise AgentError("nenhum modelo no Ollama — rode `ollama pull qwen2.5:7b` ou escolha um nas Configurações")
        model = models[0]
    # A prompt past the context window is silently truncated by Ollama — the
    # planner would edit a video it only half read. Refuse, so the fallback
    # agent takes the stage.
    needed = len(prompt) // 3 + 4096
    if needed > OLLAMA_CONTEXT:
        raise AgentError(
            f"prompt de ~{needed} tokens não cabe no contexto de {OLLAMA_CONTEXT} do modelo local "
            "(AUTO_EDIT_OLLAMA_CTX) — usando o fallback"
        )
    resp = _ollama("/api/chat", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",  # every LLM stage answers a JSON object
        "options": {"num_ctx": OLLAMA_CONTEXT, "temperature": 0.2},
    }, timeout=timeout)
    return (resp.get("message") or {}).get("content") or ""


def run_opencode(prompt: str, *, model: str | None = None, timeout: float | None = None,
                 binary: str | None = None) -> str:
    binary = binary or find_binary(AGENTS["opencode"])
    if not binary:
        raise AgentError("opencode não encontrado")
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="auto-edit-opencode-") as scratch:
        cmd = [binary, "run", "--agent", "plan", "--pure", "--format", "json", "--dir", scratch]
        if model:
            cmd += ["-m", model]
        out = _run(cmd, prompt, timeout, env=env, cwd=scratch)
    texts = []
    for raw in out.splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "text":
            texts.append((ev.get("part") or {}).get("text") or "")
        elif ev.get("type") == "error":
            raise AgentError(f"opencode: {json.dumps(ev.get('error') or ev, ensure_ascii=False)[:300]}")
    if not texts:
        raise AgentError("opencode terminou sem texto")
    return "".join(texts)


RUNNERS = {"agy": run_agy, "opencode": run_opencode, "ollama": run_ollama}

# agy and opencode are coding agents: handed a task, they reach for tools (agy
# tried RunCommand on the metadata prompt and, denied by plan mode, answered
# nothing). The pipeline only wants text back.
TEXT_ONLY = (
    "You are being called as a text-only API by an automated pipeline. Do not use "
    "any tools: do not run commands, do not read, create or edit files, do not "
    "browse. Answer in this message only, with exactly the output the task asks "
    "for and nothing else.\n\n---\n\n"
)
AGENTIC = {"agy", "opencode"}


def invoke(name: str, prompt_file: Path, output_file: Path, timeout: float | None = None) -> int:
    agent = AGENTS[name]
    prompt = prompt_file.read_text(encoding="utf-8")
    if name in AGENTIC:
        prompt = TEXT_ONLY + prompt
    try:
        text = RUNNERS[name](prompt, model=os.environ.get(agent.model_env) or None, timeout=timeout)
    except AgentError as exc:
        output_file.write_text(str(exc), encoding="utf-8")
        return 1
    output_file.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "invoke" and sys.argv[2] in RUNNERS:
        sys.exit(invoke(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])))
    print("usage: python -m auto_edit.agents invoke agy|opencode|ollama <prompt_file> <output_file>", file=sys.stderr)
    sys.exit(2)
