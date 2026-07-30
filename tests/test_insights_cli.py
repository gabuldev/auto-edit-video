"""Tests for auto_edit/insights/cli.py — arg parsing / error paths via CliRunner."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights.cli import insights_app

runner = CliRunner()


class TestInsightsCli:
    def test_report_empty_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        result = runner.invoke(insights_app, ["report"])
        assert result.exit_code == 0

    def test_sync_unknown_platform_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        result = runner.invoke(insights_app, ["sync", "myspace"])
        assert result.exit_code != 0
        assert "myspace" in result.output or "desconhecida" in result.output.lower()
