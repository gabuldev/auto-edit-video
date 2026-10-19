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
- **codex** (OpenAI Codex CLI): `codex exec` with the prompt on stdin, in a
  read-only sandbox, in an empty scratch directory, `--ephemeral`; the final
  message comes from `--output-last-message`.
- **openrouter**: no CLI — OpenRouter's HTTP API (OpenAI-compatible) with the
  user's API key (`OPENROUTER_API_KEY`, or the one saved in Settings under
  `tokens/openrouter.key`). Any model on OpenRouter; `openrouter/auto` by
  default.
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
    "codex": Agent("codex", "Codex (OpenAI)", ("codex",), "AUTO_EDIT_CODEX_MODEL", "codex login",
                   "https://developers.openai.com/codex/cli"),
    "openrouter": Agent("openrouter", "OpenRouter", (), "AUTO_EDIT_OPENROUTER_MODEL", None,
                        "https://openrouter.ai/settings/keys"),
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
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        extra += [local / "Programs" / "Ollama", local / "Programs" / "claude", home / ".opencode/bin",
                  roaming / "npm"]  # codex via npm
    exts = (".exe", ".cmd", "") if sys.platform == "win32" else ("",)
    for name in agent.binaries:
        found = shutil.which(name)
        if found:
            return found
        for d in extra:
            for ext in exts:
                cand = d / f"{name}{ext}"
                if cand.is_file() and os.access(cand, os.X_OK):
                    return str(cand)
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


def _b64(path: Path) -> str:
    import base64

    return base64.b64encode(Path(path).read_bytes()).decode()


def _data_url(path: Path) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "webp": "webp"}.get(ext, "png")
    return f"data:image/{mime};base64,{_b64(path)}"


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


def run_ollama(prompt: str, *, model: str | None = None, timeout: float | None = None, binary: str | None = None,
               images: list[Path] | None = None) -> str:
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
    message: dict = {"role": "user", "content": prompt}
    if images:
        caps = _ollama("/api/show", {"model": model}).get("capabilities") or []
        if "vision" not in caps:
            raise AgentError(f"o modelo {model} do Ollama não enxerga imagens")
        message["images"] = [_b64(p) for p in images]
    resp = _ollama("/api/chat", {
        "model": model,
        "messages": [message],
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


def run_codex(prompt: str, *, model: str | None = None, timeout: float | None = None,
              binary: str | None = None, images: list[Path] | None = None) -> str:
    binary = binary or find_binary(AGENTS["codex"])
    if not binary:
        raise AgentError("codex não encontrado")
    with tempfile.TemporaryDirectory(prefix="auto-edit-codex-") as scratch:
        last = Path(scratch) / "last_message.txt"
        # Images right after `exec`: -i takes several values, the next option ends them.
        cmd = [binary, "exec", *(a for p in images or [] for a in ("-i", str(p))), "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--color", "never", "-C", scratch, "-o", str(last)]
        if model:
            cmd += ["-m", model]
        cmd.append("-")  # prompt on stdin: a transcript does not fit on a command line
        try:
            _run(cmd, prompt, timeout, cwd=scratch)
        except AgentError as exc:
            if "401" in str(exc) or "Unauthorized" in str(exc):
                raise AgentError("Codex sem login — clique em Fazer login (entra com a conta do ChatGPT)") from None
            raise
        text = last.read_text(encoding="utf-8") if last.exists() else ""
    if not text.strip():
        raise AgentError("codex terminou sem resposta")
    return text


# ── openrouter ────────────────────────────────────────────────────────────────

OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openrouter/auto"


def openrouter_key_file() -> Path:
    from auto_edit import config as cfg

    return cfg.tokens_dir() / "openrouter.key"


def openrouter_key() -> str | None:
    """The environment wins over the key saved in Settings."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    try:
        return openrouter_key_file().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_openrouter_key(key: str | None) -> None:
    """Save (or, with None/empty, remove) the key. Readable only by the user."""
    path = openrouter_key_file()
    key = (key or "").strip()
    if not key:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _openrouter(path: str, key: str, body: dict | None = None, timeout: float | None = 30) -> dict:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {key}",
        # OpenRouter's app attribution headers (optional).
        "HTTP-Referer": "https://gabuldev.github.io/auto-edit-video/",
        "X-Title": "Auto-Edit",
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{OPENROUTER_URL}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        if exc.code == 401:
            raise AgentError(f"OpenRouter recusou a chave ({detail}) — confira em Configurações") from None
        if exc.code == 402:
            raise AgentError(f"OpenRouter: sem créditos ({detail})") from None
        raise AgentError(f"OpenRouter {exc.code}: {str(detail)[:300]}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise AgentError(f"não deu pra falar com o OpenRouter ({exc})") from None


def run_openrouter(prompt: str, *, model: str | None = None, timeout: float | None = None,
                   binary: str | None = None, images: list[Path] | None = None) -> str:
    key = openrouter_key()
    if not key:
        raise AgentError("sem chave do OpenRouter — cole a sua em Configurações (openrouter.ai/settings/keys)")
    resp = _openrouter("/chat/completions", key, {
        "model": model or OPENROUTER_DEFAULT_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            *({"type": "image_url", "image_url": {"url": _data_url(p)}} for p in images),
        ] if images else prompt}],
        "temperature": 0.2,
        # Every LLM stage answers a JSON object; models that don't support
        # this have it dropped by OpenRouter.
        "response_format": {"type": "json_object"},
    }, timeout=timeout)
    if resp.get("error"):
        raise AgentError(f"OpenRouter: {(resp['error'] or {}).get('message') or resp['error']}")
    choices = resp.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
    if not text.strip():
        raise AgentError("OpenRouter respondeu vazio")
    return text


RUNNERS = {"agy": run_agy, "opencode": run_opencode, "codex": run_codex,
           "openrouter": run_openrouter, "ollama": run_ollama}

# agy and opencode are coding agents: handed a task, they reach for tools (agy
# tried RunCommand on the metadata prompt and, denied by plan mode, answered
# nothing). The pipeline only wants text back.
TEXT_ONLY = (
    "You are being called as a text-only API by an automated pipeline. Do not use "
    "any tools: do not run commands, do not read, create or edit files, do not "
    "browse. Answer in this message only, with exactly the output the task asks "
    "for and nothing else.\n\n---\n\n"
)
AGENTIC = {"agy", "opencode", "codex"}


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


# Agents that can be handed images (complete(images=...)). Ollama only with a
# vision model (checked when it runs).
VISION = {"claude", "codex", "openrouter", "ollama"}
NO_VISION = "seu agente de IA não enxerga imagens — troque nas Configurações"


def _agent_names(env: dict) -> list[str]:
    names = [normalize(env.get("AUTO_EDIT_LLM") or "claude") or "claude"]
    fallback = normalize(env.get("AUTO_EDIT_LLM_FALLBACK") or "")
    if fallback and fallback not in names:
        names.append(fallback)
    return names


def vision_ready(env: dict | None = None) -> bool:
    """Can the chosen agent (or the fallback) look at an image?"""
    if env is None:
        from auto_edit import settings

        env = settings.env_from_settings()
    return any(n in VISION for n in _agent_names(env))


def _complete_one(name: str, prompt: str, timeout: float, env: dict, images: list[Path] | None = None) -> str:
    agent = AGENTS[name]
    model = env.get(agent.model_env) or None
    if name in ("claude", "cursor"):
        binary = find_binary(agent)
        if binary is None:
            raise AgentError(f"{agent.label} não encontrado")
    if name == "claude":
        if images:
            # Claude opens the images itself, from a folder of copies that is
            # its working directory: Read works there without a grant (a bare
            # "Read" rule would approve any path), anything outside is denied
            # in -p, and every tool that writes or reaches out is off.
            with tempfile.TemporaryDirectory(prefix="auto-edit-images-") as td:
                paths = []
                for p in images:
                    dst = Path(td) / Path(p).name
                    shutil.copyfile(p, dst)
                    paths.append(str(dst))
                prompt += "\n\n# IMAGENS (abra cada uma com a ferramenta Read)\n" + "\n".join(paths) + "\n"
                cmd = [binary, *(["--model", model] if model else []),
                       "--disallowedTools", "Bash Edit Write NotebookEdit WebFetch WebSearch Task", "-p"]
                return _run(cmd, prompt, timeout, env=env, cwd=td)
        return _run([binary, *(["--model", model] if model else []), "-p"], prompt, timeout, env=env)
    if name == "cursor":
        # Same flags as runner.invoke_cursor (read-only ask mode, JSON envelope),
        # but with a timeout, the settings' env and the binary found above, in
        # an empty scratch workspace.
        with tempfile.TemporaryDirectory(prefix="auto-edit-agent-") as td:
            out = _run([binary, "--output-format", "json", "--mode", "ask", "--trust", "--model", model or "auto",
                        "--print", "--workspace", td], prompt, timeout, env=env, cwd=td)
        try:
            outer = json.loads(out.strip())
        except ValueError:
            return out
        if isinstance(outer, dict) and outer.get("type") == "result" and isinstance(outer.get("result"), str):
            if outer.get("is_error") is True:
                raise AgentError(outer["result"].strip()[-300:] or "cursor falhou")
            return outer["result"]
        return out
    if name in AGENTIC:
        prompt = TEXT_ONLY + prompt
    if images:
        return RUNNERS[name](prompt, model=model, timeout=timeout, images=images)
    return RUNNERS[name](prompt, model=model, timeout=timeout)


def complete(prompt: str, *, images: list[Path] | None = None, timeout: float = 120) -> str:
    """One text answer outside the pipeline (no workspace, no ralph.sh): the
    agent chosen in Settings, then the fallback. With `images`, only agents
    that can see them run. AgentError lists what each one said when none
    answers."""
    from auto_edit import settings

    env = settings.env_from_settings()
    names = _agent_names(env)
    if images:
        names = [n for n in names if n in VISION]
        if not names:
            raise AgentError(NO_VISION)
    errors = []
    for name in names:
        try:
            return _complete_one(name, prompt, timeout, env, images=images)
        except AgentError as exc:
            errors.append(f"{name}: {exc}")
    raise AgentError("; ".join(errors))


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "invoke" and sys.argv[2] in RUNNERS:
        sys.exit(invoke(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])))
    print("usage: python -m auto_edit.agents invoke agy|opencode|codex|openrouter|ollama <prompt_file> <output_file>", file=sys.stderr)
    sys.exit(2)
