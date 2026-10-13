"""First run on a machine with nothing: what's missing, installing an agent,
the Whisper download, and the test that marks an agent as working."""
import sys
import time

import pytest

from auto_edit import agent_status, agents, api, engine, settings, setup


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(agent_status, "all_status", lambda: [
        {"name": "claude", "installed": True, "label": "Claude Code"},
        {"name": "ollama", "installed": True, "models": [], "label": "Ollama"},
        {"name": "agy", "installed": False, "label": "Antigravity"},
    ])
    setup._download.update(model=None, status="idle", error=None)
    return tmp_path


def _whisper_file(home, model="small", mb=466):
    d = home / "cache" / "whisper"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{model}.pt").write_bytes(b"\0" * (mb * 1_000_000))


class TestState:
    def test_fresh_machine_is_not_ready(self, home):
        s = setup.state()
        assert s["ready"] is False and s["agent_ready"] is False
        assert s["whisper"]["ready"] is False and s["whisper"]["size_mb"] == 466
        assert s["installed"] == ["claude"]  # ollama without a model doesn't count

    def test_ready_needs_a_tested_agent_and_the_model(self, home):
        _whisper_file(home)
        settings.save({"verified_agent": "claude"})
        assert setup.state()["ready"] is True

    def test_verified_agent_that_was_uninstalled(self, home):
        _whisper_file(home)
        settings.save({"verified_agent": "agy"})
        assert setup.state()["agent_ready"] is False

    def test_partial_model_file_is_not_ready(self, home):
        _whisper_file(home, mb=100)
        assert setup.whisper_state("small")["ready"] is False


class TestInstall:
    def test_claude_runs_the_official_installer_in_a_terminal(self, monkeypatch):
        opened = []
        monkeypatch.setattr(agent_status, "open_terminal", lambda cmd, **kw: opened.append(cmd))
        r = setup.open_install("claude")
        assert opened == [r["command"]]
        assert "claude.ai/install" in r["command"]

    def test_apps_without_a_one_liner_open_the_download_page(self, monkeypatch):
        urls = []
        monkeypatch.setattr(engine, "open_url", lambda url, **kw: urls.append(url) or True)
        assert setup.open_install("ollama") == {"opened": "https://ollama.com"}
        assert urls == ["https://ollama.com"]

    @pytest.mark.parametrize("platform, needle", [("win32", "install.ps1"), ("darwin", "install.sh"), ("linux", "install.sh")])
    def test_installer_per_os(self, monkeypatch, platform, needle):
        monkeypatch.setattr(sys, "platform", platform)
        assert needle in setup.install_command("claude")


def test_whisper_downloads_in_the_background(home):
    calls = []

    def fake_load(model):
        calls.append(model)
        _whisper_file(home, model=model, mb=75)

    setup.download_whisper("tiny", load=fake_load)
    for _ in range(200):
        if setup._download["status"] == "done":
            break
        time.sleep(0.01)
    assert calls == ["tiny"]
    assert setup.whisper_state("tiny")["ready"] is True


def test_whisper_download_error_is_reported(home):
    def boom(model):
        raise OSError("sem internet")

    setup.download_whisper("tiny", load=boom)
    for _ in range(200):
        if setup._download["status"] == "error":
            break
        time.sleep(0.01)
    assert "sem internet" in setup.whisper_state("tiny")["error"]


class TestApi:
    def _client(self):
        pytest.importorskip("flask")
        return api.create_app(engine.JobManager()).test_client()

    def test_passing_test_marks_the_agent_and_makes_it_primary(self, home, monkeypatch):
        monkeypatch.setattr(agent_status, "test", lambda name, model=None: {"name": name, "ok": True, "seconds": 1})
        self._client().post("/api/agents/agy/test", json={})
        s = settings.load()
        assert s["verified_agent"] == "agy" and s["agent"]["primary"] == "agy"

    def test_a_later_test_does_not_steal_primary(self, home, monkeypatch):
        settings.save({"verified_agent": "claude"})
        monkeypatch.setattr(agent_status, "test", lambda name, model=None: {"name": name, "ok": True, "seconds": 1})
        self._client().post("/api/agents/agy/test", json={})
        s = settings.load()
        assert s["agent"]["primary"] == "claude" and s["verified_agent"] == "agy"

    def test_failed_test_changes_nothing(self, home, monkeypatch):
        monkeypatch.setattr(agent_status, "test", lambda name, model=None: {"name": name, "ok": False})
        self._client().post("/api/agents/claude/test", json={})
        assert settings.load()["verified_agent"] is None

    def test_setup_and_whisper_endpoints(self, home, monkeypatch):
        monkeypatch.setattr(setup, "download_whisper", lambda model: {"model": model, "downloading": True})
        c = self._client()
        assert c.get("/api/setup").get_json()["ready"] is False
        assert c.post("/api/setup/whisper", json={"model": "tiny"}).get_json()["model"] == "tiny"
        assert c.post("/api/setup/whisper", json={"model": "gigante"}).status_code == 400


def test_find_binary_on_windows_looks_for_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(agents.Path, "home", staticmethod(lambda: tmp_path))
    exe = tmp_path / ".local" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    exe.chmod(0o755)
    assert agents.find_binary(agents.AGENTS["claude"]) == str(exe)
