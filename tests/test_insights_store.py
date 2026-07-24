"""Tests for auto_edit/insights — config paths, store CRUD."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import config as cfg


class TestConfigPaths:
    def test_insights_db_path_under_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        assert cfg.insights_db_path() == tmp_path / "insights.db"

    def test_tokens_dir_created_700(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        d = cfg.tokens_dir()
        assert d == tmp_path / "tokens"
        assert d.is_dir()
        assert (d.stat().st_mode & 0o777) == 0o700
