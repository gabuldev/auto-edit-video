"""Tests for auto_edit.shell — which bash runs ralph.sh on Windows."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import shell


def _fake_which(found: dict):
    return lambda name, path=None: found.get(path)


class TestBash:
    def test_posix_is_plain_bash(self, monkeypatch):
        monkeypatch.setattr(shell.sys, "platform", "darwin")
        assert shell.bash({"PATH": "/x"}) == "bash"

    def test_windows_skips_the_wsl_launcher(self, monkeypatch):
        monkeypatch.setattr(shell.sys, "platform", "win32")
        monkeypatch.setattr(shell.os, "pathsep", ";")
        git = r"C:\App\engine\git\usr\bin"
        monkeypatch.setattr(shell.shutil, "which", _fake_which({
            r"C:\Windows\System32": r"C:\Windows\System32\bash.exe",
            git: git + r"\bash.exe",
        }))
        env = {"PATH": rf"C:\Windows\System32;{git}"}
        assert shell.bash(env) == git + r"\bash.exe"

    def test_windows_drops_the_extended_prefix(self, monkeypatch):
        monkeypatch.setattr(shell.sys, "platform", "win32")
        monkeypatch.setattr(shell.os, "pathsep", ";")
        git = "\\\\?\\C:\\App\\git\\usr\\bin"
        monkeypatch.setattr(shell.shutil, "which", _fake_which({git: git + "\\bash.EXE"}))
        assert shell.bash({"PATH": git}) == "C:\\App\\git\\usr\\bin\\bash.EXE"

    def test_windows_without_git_bash_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shell.sys, "platform", "win32")
        monkeypatch.setattr(shell.shutil, "which", _fake_which({}))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "nothing"))
        monkeypatch.setenv("ProgramW6432", "")
        assert shell.bash({"PATH": ""}) == "bash"


class TestNativePath:
    def test_strips_extended_prefix(self):
        assert shell.native_path("\\\\?\\C:\\Users\\a\\video.mp4") == "C:\\Users\\a\\video.mp4"

    def test_unc(self):
        assert shell.native_path("\\\\?\\UNC\\srv\\share\\v.mp4") == "\\\\srv\\share\\v.mp4"

    def test_plain_path_unchanged(self):
        p = Path("/videos/v.mp4")
        assert shell.native_path(p) == str(p)


class TestNativeEnv:
    def test_cleans_path_and_engine_vars(self, monkeypatch):
        monkeypatch.setattr(shell.os, "pathsep", ";")
        env = shell.native_env({
            "PATH": "\\\\?\\C:\\App\\bin;C:\\Windows",
            "AUTO_EDIT_REPO_ROOT": "\\\\?\\C:\\App\\repo",
            "HOME": "\\\\?\\left-alone",
        })
        assert env["PATH"] == "C:\\App\\bin;C:\\Windows"
        assert env["AUTO_EDIT_REPO_ROOT"] == "C:\\App\\repo"
        assert env["HOME"] == "\\\\?\\left-alone"
