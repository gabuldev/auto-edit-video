"""Settings file: defaults, validation, env precedence, and the API; agent
status/test/login (with fakes — no real CLI or terminal)."""
import json
import sys

import pytest

from auto_edit import agent_status, agents, api, engine, settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    for var in ("AUTO_EDIT_LLM", "AUTO_EDIT_LLM_FALLBACK", "AUTO_EDIT_INBOX", "AUTO_EDIT_LANGUAGE",
                "AUTO_EDIT_ASSETS_OVERLAYS", "AUTO_EDIT_OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


class TestSettings:
    def test_defaults_without_a_file(self, home):
        s = settings.load()
        assert s["agent"]["primary"] == "claude" and s["cold_open"] is True
        assert set(s["agent"]["models"]) == set(agents.AGENTS)

    def test_partial_update_keeps_the_rest(self, home):
        settings.save({"agent": {"primary": "agy"}})
        settings.save({"language": "en"})
        s = settings.load()
        assert s["agent"]["primary"] == "agy" and s["language"] == "en"

    @pytest.mark.parametrize("bad", [
        {"agent": {"primary": "gemini"}},
        {"agent": {"fallback": "nope"}},
        {"whisper_model": "huge"},
        {"inbox": "/definitely/not/here"},
    ])
    def test_rejects(self, home, bad):
        with pytest.raises(settings.SettingsError):
            settings.save(bad)

    def test_aliases_and_same_fallback(self, home):
        s = settings.save({"agent": {"primary": "antigravity", "fallback": "agy"}})
        assert s["agent"]["primary"] == "agy" and s["agent"]["fallback"] is None

    def test_broken_file_reads_as_defaults(self, home):
        settings.path().parent.mkdir(parents=True)
        settings.path().write_text("{nope", encoding="utf-8")
        assert settings.load()["agent"]["primary"] == "claude"

    def test_env_fills_gaps_but_set_variables_win(self, home, tmp_path):
        inbox = tmp_path / "in"
        inbox.mkdir()
        settings.save({"agent": {"primary": "ollama", "fallback": "claude", "models": {"ollama": "qwen2.5:7b"}},
                       "inbox": str(inbox)})
        env = settings.env_from_settings({"AUTO_EDIT_LLM": "cursor"})
        assert env["AUTO_EDIT_LLM"] == "cursor"  # already set: untouched
        assert env["AUTO_EDIT_LLM_FALLBACK"] == "claude"
        assert env["AUTO_EDIT_OLLAMA_MODEL"] == "qwen2.5:7b"
        assert env["AUTO_EDIT_INBOX"] == str(inbox)

    def test_engine_uses_the_saved_inbox(self, home, tmp_path):
        inbox = tmp_path / "gravacoes"
        inbox.mkdir()
        settings.save({"inbox": str(inbox)})
        assert engine.inbox_root() == inbox


class TestApi:
    def _client(self):
        pytest.importorskip("flask")
        return api.create_app(engine.JobManager()).test_client()

    def test_get_and_put(self, home):
        c = self._client()
        assert c.get("/api/settings").get_json()["agent"]["primary"] == "claude"
        r = c.put("/api/settings", json={"agent": {"primary": "opencode", "models": {"opencode": "opencode/big-pickle"}}})
        assert r.status_code == 200 and r.get_json()["agent"]["models"]["opencode"] == "opencode/big-pickle"
        assert c.put("/api/settings", json={"whisper_model": "x"}).status_code == 400

    def test_edit_defaults_come_from_settings(self, home, tmp_path, monkeypatch):
        settings.save({"language": "en", "whisper_model": "medium", "cold_open": False})
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        seen = {}
        mgr = engine.JobManager()
        monkeypatch.setattr(mgr, "start_edit", lambda *a, **kw: seen.update(kw) or type("J", (), {"id": "j", "video_id": "v"})())
        r = api.create_app(mgr).test_client().post("/api/edit", json={"video_path": str(video), "type": "long"})
        assert r.status_code == 202
        assert (seen["language"], seen["whisper_model"], seen["cold_open"]) == ("en", "medium", False)

    def test_agents_endpoints(self, home, monkeypatch):
        monkeypatch.setattr(agent_status, "all_status", lambda: [{"name": "claude"}])
        monkeypatch.setattr(agent_status, "test", lambda name, model=None: {"name": name, "ok": True, "model": model})
        c = self._client()
        assert c.get("/api/agents").get_json()["agents"] == [{"name": "claude"}]
        assert c.post("/api/agents/agy/test", json={"model": "m"}).get_json() == {"name": "agy", "ok": True, "model": "m"}
        assert c.post("/api/agents/gemini/test").status_code == 404
        assert c.post("/api/agents/ollama/pull", json={}).status_code == 400


class TestAgentStatus:
    def test_test_reports_failure_with_the_cli_message(self, monkeypatch):
        def boom(prompt, model=None, timeout=None):
            raise agents.AgentError("Authentication required")
        monkeypatch.setitem(agents.RUNNERS, "agy", boom)
        r = agent_status.test("agy")
        assert r["ok"] is False and "Authentication" in r["error"]

    def test_answer_that_is_not_what_was_asked(self, monkeypatch):
        monkeypatch.setitem(agents.RUNNERS, "ollama", lambda p, model=None, timeout=None: "olá!")
        r = agent_status.test("ollama")
        assert r["ok"] is False and r["answer"] == "olá!"

    def test_agentic_clis_get_the_text_only_preface(self, monkeypatch):
        seen = {}
        monkeypatch.setitem(agents.RUNNERS, "opencode", lambda p, model=None, timeout=None: seen.setdefault("p", p) and '{"ok": true}')
        assert agent_status.test("opencode")["ok"] is True
        assert seen["p"].startswith(agents.TEXT_ONLY)

    @pytest.mark.skipif(sys.platform != "darwin", reason="osascript")
    def test_login_opens_terminal_with_the_command(self, monkeypatch):
        monkeypatch.setattr(agents, "find_binary", lambda a: f"/bin/{a.binaries[0]}")
        calls = []
        cmd = agent_status.open_login("cursor", run=lambda c: calls.append(c))
        assert cmd == "/bin/cursor-agent login"
        assert calls[0][0] == "osascript" and json.dumps(cmd) in calls[0][2]

    def test_no_login_for_ollama(self):
        with pytest.raises(agents.AgentError):
            agent_status.open_login("ollama")

    def test_pull_tracks_progress(self, monkeypatch):
        monkeypatch.setattr(agents, "find_binary", lambda a: "/bin/ollama")
        done = []

        class P:
            returncode = 0
            stderr = ""

        def run(cmd, **kw):
            done.append(cmd)
            return P()
        agent_status._pulls.clear()
        agent_status.pull("qwen2.5:7b", run=run)
        for _ in range(100):
            if agent_status._pulls.get("qwen2.5:7b") == "done":
                break
            import time
            time.sleep(0.01)
        assert done == [["/bin/ollama", "pull", "qwen2.5:7b"]]
        assert agent_status._pulls["qwen2.5:7b"] == "done"
