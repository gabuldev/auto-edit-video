"""The agent CLIs: names/aliases, and the agy / opencode / ollama runners
against fake binaries and a fake Ollama server (no network, no real CLI)."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from auto_edit import agents


@pytest.mark.parametrize("raw, name", [
    ("claude", "claude"), ("Cursor", "cursor"), ("agent", "cursor"), ("agy", "agy"),
    ("antigravity", "agy"), ("opencode", "opencode"), ("ollama", "ollama"), ("gemini", None), ("", None),
])
def test_normalize(raw, name):
    assert agents.normalize(raw) == name


def _fake(tmp_path: Path, name: str, script: str) -> str:
    """A fake CLI: a Python script that reads stdin and prints what the real one would."""
    path = tmp_path / name
    path.write_text(f"#!{sys.executable}\nimport sys, json\n{script}\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@pytest.mark.skipif(sys.platform == "win32", reason="shebang fakes")
class TestAgy:
    def test_prompt_goes_as_stream_json_and_response_comes_back(self, tmp_path):
        fake = _fake(tmp_path, "agy", """
args = sys.argv[1:]
assert args[:6] == ["--mode", "plan", "--input-format", "stream-json", "--output-format", "stream-json"], args
msg = json.loads(sys.stdin.readline())
assert msg["event"] == "user"
print(json.dumps({"event": "init"}))
print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "eco:" + msg["message"]["content"][-5:]}}))
""")
        assert agents.run_agy("um prompt", binary=fake) == "eco:rompt"

    def test_empty_answer_names_the_denied_tool(self, tmp_path):
        fake = _fake(tmp_path, "agy", """
sys.stdin.read()
print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "",
      "denied_actions": [{"display_name": "RunCommand"}]}}))
""")
        with pytest.raises(agents.AgentError, match="RunCommand"):
            agents.run_agy("x", binary=fake)

    def test_error_status(self, tmp_path):
        fake = _fake(tmp_path, "agy", """
sys.stdin.read()
print(json.dumps({"event": "result", "result": {"status": "ERROR", "error": "quota"}}))
""")
        with pytest.raises(agents.AgentError, match="quota"):
            agents.run_agy("x", binary=fake)


@pytest.mark.skipif(sys.platform == "win32", reason="shebang fakes")
class TestOpencode:
    def test_read_only_agent_in_a_scratch_dir(self, tmp_path):
        fake = _fake(tmp_path, "opencode", """
import os
args = sys.argv[1:]
assert args[:3] == ["run", "--agent", "plan"] and "--pure" in args, args
d = args[args.index("--dir") + 1]
assert os.getcwd() == os.path.realpath(d) and os.listdir(d) == []
assert args[args.index("-m") + 1] == "opencode/big-pickle"
sys.stdin.read()
for t in ("{\\"ok\\": ", "true}"):
    print(json.dumps({"type": "text", "part": {"text": t}}))
""")
        assert agents.run_opencode("p", model="opencode/big-pickle", binary=fake) == '{"ok": true}'

    def test_error_event(self, tmp_path):
        fake = _fake(tmp_path, "opencode", """
sys.stdin.read()
print(json.dumps({"type": "error", "error": {"message": "model retired"}}))
""")
        with pytest.raises(agents.AgentError, match="retired"):
            agents.run_opencode("p", binary=fake)


class _Ollama(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"models": [{"name": "qwen2.5:7b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Ollama.seen.append(body)
        self._send({"message": {"content": '{"ok": true}'}})


@pytest.fixture
def ollama(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Ollama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(agents, "OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
    _Ollama.seen = []
    yield _Ollama
    server.shutdown()


class TestOllama:
    def test_json_mode_and_a_real_context_window(self, ollama):
        assert agents.run_ollama("oi", model="qwen2.5:7b") == '{"ok": true}'
        sent = ollama.seen[0]
        assert sent["format"] == "json" and sent["stream"] is False
        assert sent["options"]["num_ctx"] == agents.OLLAMA_CONTEXT

    def test_first_installed_model_when_none_chosen(self, ollama):
        agents.run_ollama("oi")
        assert ollama.seen[0]["model"] == "qwen2.5:7b"

    def test_prompt_past_the_context_is_refused_not_truncated(self, ollama, monkeypatch):
        monkeypatch.setattr(agents, "OLLAMA_CONTEXT", 8000)
        with pytest.raises(agents.AgentError, match="não cabe"):
            agents.run_ollama("x" * 30000, model="qwen2.5:7b")
        assert ollama.seen == []

    def test_server_down(self, monkeypatch):
        monkeypatch.setattr(agents, "OLLAMA_URL", "http://127.0.0.1:9")
        with pytest.raises(agents.AgentError, match="não está rodando"):
            agents.ollama_models()


def test_invoke_writes_the_text_or_the_error(tmp_path, monkeypatch):
    prompt = tmp_path / "p.txt"
    prompt.write_text("tarefa", encoding="utf-8")
    out = tmp_path / "o.txt"
    seen = {}

    def ok(p, **kw):
        seen["prompt"] = p
        return '{"a": 1}'

    monkeypatch.setitem(agents.RUNNERS, "agy", ok)
    assert agents.invoke("agy", prompt, out) == 0
    assert out.read_text(encoding="utf-8") == '{"a": 1}'
    assert seen["prompt"].startswith(agents.TEXT_ONLY) and seen["prompt"].endswith("tarefa")

    def boom(p, **kw):
        raise agents.AgentError("falhou")

    monkeypatch.setitem(agents.RUNNERS, "ollama", boom)
    assert agents.invoke("ollama", prompt, out) == 1
    assert out.read_text(encoding="utf-8") == "falhou"


def test_model_comes_from_the_env(tmp_path, monkeypatch):
    prompt = tmp_path / "p.txt"
    prompt.write_text("x", encoding="utf-8")
    seen = {}
    monkeypatch.setitem(agents.RUNNERS, "ollama", lambda p, **kw: seen.update(kw) or "{}")
    monkeypatch.setenv("AUTO_EDIT_OLLAMA_MODEL", "llama3.1:8b")
    agents.invoke("ollama", prompt, tmp_path / "o.txt")
    assert seen["model"] == "llama3.1:8b"
    assert os.environ["AUTO_EDIT_OLLAMA_MODEL"] == "llama3.1:8b"


class TestComplete:
    """One text call outside the pipeline (Estilos → Criar com IA): the agent
    from Settings, then the fallback."""

    @pytest.fixture
    def env(self, monkeypatch):
        from auto_edit import settings

        e: dict = {}
        monkeypatch.setattr(settings, "env_from_settings", lambda base=None: e)
        return e

    def test_primary_answers(self, env, monkeypatch):
        env["AUTO_EDIT_LLM"] = "ollama"
        monkeypatch.setitem(agents.RUNNERS, "ollama", lambda prompt, model=None, timeout=None: f"ok:{prompt}")
        assert agents.complete("oi") == "ok:oi"

    def test_falls_back_when_primary_fails(self, env, monkeypatch):
        env.update(AUTO_EDIT_LLM="ollama", AUTO_EDIT_LLM_FALLBACK="openrouter")

        def boom(prompt, model=None, timeout=None):
            raise agents.AgentError("caiu")

        monkeypatch.setitem(agents.RUNNERS, "ollama", boom)
        monkeypatch.setitem(agents.RUNNERS, "openrouter", lambda prompt, model=None, timeout=None: "do fallback")
        assert agents.complete("oi") == "do fallback"

    def test_both_fail_lists_both(self, env, monkeypatch):
        env.update(AUTO_EDIT_LLM="ollama", AUTO_EDIT_LLM_FALLBACK="openrouter")

        def boom(prompt, model=None, timeout=None):
            raise agents.AgentError("caiu")

        monkeypatch.setitem(agents.RUNNERS, "ollama", boom)
        monkeypatch.setitem(agents.RUNNERS, "openrouter", boom)
        with pytest.raises(agents.AgentError, match="ollama.*openrouter"):
            agents.complete("oi")

    def test_agentic_cli_gets_the_text_only_preamble(self, env, monkeypatch):
        env["AUTO_EDIT_LLM"] = "opencode"
        seen = {}
        monkeypatch.setitem(agents.RUNNERS, "opencode", lambda prompt, model=None, timeout=None: seen.setdefault("p", prompt))
        agents.complete("tarefa")
        assert seen["p"].startswith(agents.TEXT_ONLY) and seen["p"].endswith("tarefa")

    def test_claude_gets_the_prompt_on_stdin(self, env, monkeypatch):
        env.update(AUTO_EDIT_LLM="claude", AUTO_EDIT_CLAUDE_MODEL="sonnet")
        calls = []
        monkeypatch.setattr(agents, "find_binary", lambda agent: "/bin/claude")
        monkeypatch.setattr(agents, "_run", lambda cmd, stdin, timeout, env=None, cwd=None: calls.append((cmd, stdin)) or "resposta")
        assert agents.complete("p") == "resposta"
        assert calls == [(["/bin/claude", "--model", "sonnet", "-p"], "p")]

    def test_missing_cli_is_an_agent_error(self, env, monkeypatch):
        env["AUTO_EDIT_LLM"] = "claude"
        monkeypatch.setattr(agents, "find_binary", lambda agent: None)
        with pytest.raises(agents.AgentError, match="Claude"):
            agents.complete("p")

    def test_cursor_answer_is_unwrapped_with_timeout_and_env(self, env, monkeypatch):
        env.update(AUTO_EDIT_LLM="cursor", AUTO_EDIT_CURSOR_MODEL="gpt-5")
        calls = []
        monkeypatch.setattr(agents, "find_binary", lambda agent: "/opt/bin/cursor-agent")

        def fake_run(cmd, stdin, timeout, env=None, cwd=None):
            calls.append((cmd, stdin, timeout, env))
            return json.dumps({"type": "result", "result": '{"name": "X"}', "is_error": False})

        monkeypatch.setattr(agents, "_run", fake_run)
        assert agents.complete("p", timeout=33) == '{"name": "X"}'
        cmd, stdin, timeout, e = calls[0]
        assert cmd[0] == "/opt/bin/cursor-agent" and "--print" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5"
        assert stdin == "p" and timeout == 33 and e is env

    def test_cursor_error_result_is_an_agent_error(self, env, monkeypatch):
        env["AUTO_EDIT_LLM"] = "cursor"
        monkeypatch.setattr(agents, "find_binary", lambda agent: "/opt/bin/agent")
        monkeypatch.setattr(agents, "_run", lambda cmd, stdin, timeout, env=None, cwd=None: json.dumps({"type": "result", "result": "limit", "is_error": True}))
        with pytest.raises(agents.AgentError, match="limit"):
            agents.complete("p")


class TestImages:
    """complete(images=...): only agents that see images get them."""

    @pytest.fixture
    def env(self, monkeypatch):
        from auto_edit import settings

        e: dict = {}
        monkeypatch.setattr(settings, "env_from_settings", lambda base=None: e)
        return e

    @pytest.fixture
    def img(self, tmp_path):
        p = tmp_path / "ref.png"
        p.write_bytes(b"\x89PNGfake")
        return p

    def test_claude_reads_only_the_images_folder(self, env, monkeypatch, img):
        env["AUTO_EDIT_LLM"] = "claude"
        seen = {}
        monkeypatch.setattr(agents, "find_binary", lambda agent: "/bin/claude")

        def fake_run(cmd, stdin, timeout, env=None, cwd=None):
            seen.update(cmd=cmd, stdin=stdin, cwd=cwd, copied=sorted(p.name for p in Path(cwd).iterdir()))
            return "ok"

        monkeypatch.setattr(agents, "_run", fake_run)
        assert agents.complete("faça", images=[img]) == "ok"
        cmd = seen["cmd"]
        # No blanket "Read" grant (it would approve any path): the folder is
        # the working directory, and every tool that writes or reaches out is off.
        assert "--allowedTools" not in cmd and cmd[-1] == "-p"
        denied = cmd[cmd.index("--disallowedTools") + 1]
        assert all(t in denied for t in ("Bash", "Edit", "Write", "WebFetch", "WebSearch"))
        assert seen["copied"] == ["ref.png"] and "ref.png" in seen["stdin"] and seen["stdin"].startswith("faça")

    def test_codex_gets_image_flags_before_other_options(self, monkeypatch, img):
        seen = {}
        monkeypatch.setattr(agents, "_run", lambda cmd, stdin, timeout, env=None, cwd=None: seen.update(cmd=cmd) or "")
        with pytest.raises(agents.AgentError):  # no last message written by the fake
            agents.run_codex("p", binary="/bin/codex", images=[img])
        assert seen["cmd"][1:4] == ["exec", "-i", str(img)] and seen["cmd"][-1] == "-"

    def test_openrouter_sends_image_url_parts(self, monkeypatch, img):
        seen = {}
        monkeypatch.setattr(agents, "openrouter_key", lambda: "k")
        monkeypatch.setattr(agents, "_openrouter", lambda path, key, body=None, timeout=None: seen.update(body=body) or {"choices": [{"message": {"content": "ok"}}]})
        assert agents.run_openrouter("p", images=[img]) == "ok"
        content = seen["body"]["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "p"}
        assert content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_ollama_sends_images_only_to_a_vision_model(self, monkeypatch, img):
        caps = {"capabilities": ["completion"]}
        bodies = []

        def fake(path, body=None, timeout=10):
            if path == "/api/show":
                return caps
            bodies.append(body)
            return {"message": {"content": "ok"}}

        monkeypatch.setattr(agents, "_ollama", fake)
        with pytest.raises(agents.AgentError, match="imagens"):
            agents.run_ollama("p", model="qwen2.5:7b", images=[img])
        caps["capabilities"].append("vision")
        assert agents.run_ollama("p", model="llava", images=[img]) == "ok"
        assert bodies[0]["messages"][0]["images"] == [__import__("base64").b64encode(img.read_bytes()).decode()]

    def test_complete_skips_agents_without_vision(self, env, monkeypatch, img):
        env.update(AUTO_EDIT_LLM="cursor", AUTO_EDIT_LLM_FALLBACK="openrouter")
        monkeypatch.setitem(agents.RUNNERS, "openrouter", lambda prompt, model=None, timeout=None, images=None: f"viu {len(images)}")
        monkeypatch.setattr(agents, "find_binary", lambda agent: pytest.fail("cursor ran"))
        assert agents.complete("x", images=[img]) == "viu 1"

    def test_complete_without_any_vision_agent(self, env, img):
        env["AUTO_EDIT_LLM"] = "cursor"
        with pytest.raises(agents.AgentError, match="não enxerga"):
            agents.complete("x", images=[img])

    def test_vision_ready(self, env):
        env["AUTO_EDIT_LLM"] = "cursor"
        assert agents.vision_ready() is False
        env["AUTO_EDIT_LLM_FALLBACK"] = "codex"
        assert agents.vision_ready() is True
