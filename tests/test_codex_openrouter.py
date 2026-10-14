"""Codex (CLI) and OpenRouter (HTTP API + a saved key): runners against a fake
binary and a stubbed API, key storage, status and the key endpoints."""
import json
import sys
from pathlib import Path

import pytest

from auto_edit import agent_status, agents, api, engine


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return tmp_path


@pytest.mark.parametrize("raw", ["codex", "Codex", "openrouter", "OpenRouter"])
def test_known_names(raw):
    assert agents.normalize(raw) == raw.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="shebang fakes")
class TestCodex:
    def _fake(self, tmp_path: Path, script: str) -> str:
        path = tmp_path / "codex"
        path.write_text(f"#!{sys.executable}\nimport sys, os\n{script}\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_read_only_exec_in_an_empty_dir_answer_from_last_message(self, tmp_path):
        fake = self._fake(tmp_path, """
args = sys.argv[1:]
assert args[0] == "exec", args
assert args[args.index("--sandbox") + 1] == "read-only"
assert "--skip-git-repo-check" in args and "--ephemeral" in args and args[-1] == "-"
d = args[args.index("-C") + 1]
assert os.getcwd() == os.path.realpath(d) and os.listdir(d) == []
assert args[args.index("-m") + 1] == "gpt-5-codex"
prompt = sys.stdin.read()
print("progress noise that is not the answer")
open(args[args.index("-o") + 1], "w").write('{"echo": "%s"}' % prompt[-5:])
""")
        assert agents.run_codex("um prompt", model="gpt-5-codex", binary=fake) == '{"echo": "rompt"}'

    def test_no_final_message_is_an_error(self, tmp_path):
        fake = self._fake(tmp_path, "sys.stdin.read()")
        with pytest.raises(agents.AgentError, match="sem resposta"):
            agents.run_codex("p", binary=fake)

    def test_failure_carries_the_cli_message(self, tmp_path):
        fake = self._fake(tmp_path, "sys.stdin.read(); sys.stderr.write('Not logged in'); sys.exit(1)")
        with pytest.raises(agents.AgentError, match="Not logged in"):
            agents.run_codex("p", binary=fake)

    def test_not_logged_in(self, tmp_path):
        fake = self._fake(tmp_path, "sys.stdin.read(); sys.stderr.write('unexpected status 401 Unauthorized'); sys.exit(1)")
        with pytest.raises(agents.AgentError, match="Fazer login"):
            agents.run_codex("p", binary=fake)

    def test_gets_the_text_only_preface(self, monkeypatch):
        seen = {}
        monkeypatch.setitem(agents.RUNNERS, "codex", lambda p, model=None, timeout=None: seen.setdefault("p", p) and '{"ok": true}')
        assert agent_status.test("codex")["ok"] is True
        assert seen["p"].startswith(agents.TEXT_ONLY)


class TestOpenRouterKey:
    def test_saved_key_env_wins_and_remove(self, home, monkeypatch):
        assert agents.openrouter_key() is None
        agents.save_openrouter_key("  sk-or-v1-saved  ")
        assert agents.openrouter_key() == "sk-or-v1-saved"
        if sys.platform != "win32":
            assert agents.openrouter_key_file().stat().st_mode & 0o777 == 0o600
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-env")
        assert agents.openrouter_key() == "sk-or-v1-env"
        monkeypatch.delenv("OPENROUTER_API_KEY")
        agents.save_openrouter_key(None)
        assert agents.openrouter_key() is None

    def test_status_is_installed_with_a_key_and_never_shows_it(self, home):
        assert agent_status.status("openrouter")["installed"] is False
        agents.save_openrouter_key("sk-or-v1-abcdefghijklmnop1234")
        s = agent_status.status("openrouter")
        assert s["installed"] is True and s["api_key"] is True and s["key_source"] == "settings"
        assert "abcdefghijklmnop" not in json.dumps(s) and s["key_hint"].endswith("1234")


class TestOpenRouterRunner:
    def test_no_key(self, home):
        with pytest.raises(agents.AgentError, match="chave"):
            agents.run_openrouter("p")

    def test_request_and_answer(self, home, monkeypatch):
        agents.save_openrouter_key("sk-or-v1-k")
        seen = {}

        def fake(path, key, body=None, timeout=None):
            seen.update(path=path, key=key, body=body)
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        monkeypatch.setattr(agents, "_openrouter", fake)
        assert agents.run_openrouter("prompt") == '{"ok": true}'
        assert seen["path"] == "/chat/completions" and seen["key"] == "sk-or-v1-k"
        assert seen["body"]["model"] == agents.OPENROUTER_DEFAULT_MODEL
        assert seen["body"]["response_format"] == {"type": "json_object"}
        agents.run_openrouter("prompt", model="anthropic/x")
        assert seen["body"]["model"] == "anthropic/x"

    def test_empty_answer_and_error_body(self, home, monkeypatch):
        agents.save_openrouter_key("k")
        monkeypatch.setattr(agents, "_openrouter", lambda *a, **kw: {"choices": [{"message": {"content": ""}}]})
        with pytest.raises(agents.AgentError, match="vazio"):
            agents.run_openrouter("p")
        monkeypatch.setattr(agents, "_openrouter", lambda *a, **kw: {"error": {"message": "model not found"}})
        with pytest.raises(agents.AgentError, match="model not found"):
            agents.run_openrouter("p")


class TestKeyEndpoints:
    def test_put_and_delete(self, home):
        pytest.importorskip("flask")
        c = api.create_app(engine.JobManager()).test_client()
        assert c.put("/api/agents/openrouter/key", json={"key": " "}).status_code == 400
        r = c.put("/api/agents/openrouter/key", json={"key": "sk-or-v1-abcdefghijklmnop9999"})
        assert r.status_code == 200 and r.get_json()["installed"] is True
        assert "abcdefghijklmnop" not in r.get_data(as_text=True)
        assert agents.openrouter_key() == "sk-or-v1-abcdefghijklmnop9999"
        assert c.delete("/api/agents/openrouter/key").get_json()["installed"] is False


def test_install_pages_are_openable():
    assert engine._OPENABLE_URL.match(agents.AGENTS["codex"].docs)
    assert engine._OPENABLE_URL.match(agents.AGENTS["openrouter"].docs)
