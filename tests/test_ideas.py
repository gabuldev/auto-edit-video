"""Tests for auto_edit/ideas.py — CRUD operations on the ideas backlog."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from auto_edit import config as cfg
from auto_edit.cli import app

runner = CliRunner()


@pytest.fixture
def auto_edit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    cfg.ensure_dirs()
    return tmp_path


def _write_idea(home: Path, idea_id: str, **fields) -> Path:
    body = {"id": idea_id, "title": f"Test {idea_id}", "status": "backlog", "priority": "medium", **fields}
    path = home / "ideas" / f"{idea_id}.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


# ── add ──────────────────────────────────────────────────────────────────────


class TestAdd:
    def test_add_basic(self, auto_edit_home):
        result = runner.invoke(app, ["ideas", "add", "My great idea"])
        assert result.exit_code == 0
        assert "Idea added" in result.output

        files = list((auto_edit_home / "ideas").glob("idea-*.yaml"))
        assert len(files) == 1
        data = yaml.safe_load(files[0].read_text())
        assert data["title"] == "My great idea"
        assert data["status"] == "backlog"
        assert data["priority"] == "medium"
        assert data["source"] == "personal"

    def test_add_with_all_options(self, auto_edit_home):
        result = runner.invoke(app, [
            "ideas", "add", "Flutter tutorial",
            "--source", "youtube-comment",
            "--priority", "high",
            "--tags", "flutter,dart",
            "--format", "tutorial",
            "--description", "Requested by viewers",
            "--language", "en",
        ])
        assert result.exit_code == 0
        files = list((auto_edit_home / "ideas").glob("idea-*.yaml"))
        data = yaml.safe_load(files[0].read_text())
        assert data["title"] == "Flutter tutorial"
        assert data["source"] == "youtube-comment"
        assert data["priority"] == "high"
        assert data["tags"] == ["flutter", "dart"]
        assert data["format"] == "tutorial"
        assert data["description"] == "Requested by viewers"
        assert data["language"] == "en"

    def test_add_invalid_priority(self, auto_edit_home):
        result = runner.invoke(app, ["ideas", "add", "Bad", "--priority", "urgent"])
        assert result.exit_code != 0
        assert "Invalid priority" in result.output

    def test_add_sequential_ids(self, auto_edit_home):
        runner.invoke(app, ["ideas", "add", "First"])
        runner.invoke(app, ["ideas", "add", "Second"])
        files = sorted((auto_edit_home / "ideas").glob("idea-*.yaml"))
        assert len(files) == 2
        assert files[0].stem.endswith("-001")
        assert files[1].stem.endswith("-002")


# ── list ─────────────────────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, auto_edit_home):
        result = runner.invoke(app, ["ideas", "list"])
        assert result.exit_code == 0
        assert "No ideas yet" in result.output

    def test_list_shows_backlog_by_default(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Active")
        _write_idea(auto_edit_home, "idea-20260511-002", title="Finished", status="done")
        result = runner.invoke(app, ["ideas", "list"])
        assert "Active" in result.output
        assert "Finished" not in result.output

    def test_list_all_flag(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Active")
        _write_idea(auto_edit_home, "idea-20260511-002", title="Finished", status="done")
        result = runner.invoke(app, ["ideas", "list", "--all"])
        assert "Active" in result.output
        assert "Finished" in result.output

    def test_list_filter_by_priority(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Important", priority="high")
        _write_idea(auto_edit_home, "idea-20260511-002", title="Meh", priority="low")
        result = runner.invoke(app, ["ideas", "list", "--priority", "high"])
        assert "Important" in result.output
        assert "Meh" not in result.output

    def test_list_filter_by_tag(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Tagged", tags=["flutter"])
        _write_idea(auto_edit_home, "idea-20260511-002", title="Untagged", tags=[])
        result = runner.invoke(app, ["ideas", "list", "--tag", "flutter"])
        assert "Tagged" in result.output
        assert "Untagged" not in result.output


# ── show ─────────────────────────────────────────────────────────────────────


class TestShow:
    def test_show_existing(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Show me", description="Details here")
        result = runner.invoke(app, ["ideas", "show", "idea-20260511-001"])
        assert result.exit_code == 0
        assert "Show me" in result.output
        assert "Details here" in result.output

    def test_show_not_found(self, auto_edit_home):
        result = runner.invoke(app, ["ideas", "show", "idea-nonexistent"])
        assert result.exit_code != 0

    def test_show_short_id(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Found by suffix")
        result = runner.invoke(app, ["ideas", "show", "001"])
        assert result.exit_code == 0
        assert "Found by suffix" in result.output


# ── update ───────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_priority(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", priority="low")
        result = runner.invoke(app, ["ideas", "update", "idea-20260511-001", "--priority", "high"])
        assert result.exit_code == 0
        assert "Updated" in result.output
        data = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert data["priority"] == "high"

    def test_update_status(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        result = runner.invoke(app, ["ideas", "update", "idea-20260511-001", "--status", "done"])
        assert result.exit_code == 0
        data = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert data["status"] == "done"

    def test_update_tags(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", tags=["old"])
        result = runner.invoke(app, ["ideas", "update", "idea-20260511-001", "--tags", "new,shiny"])
        assert result.exit_code == 0
        data = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert data["tags"] == ["new", "shiny"]

    def test_update_no_flags(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        result = runner.invoke(app, ["ideas", "update", "idea-20260511-001"])
        assert result.exit_code != 0
        assert "Nothing to update" in result.output

    def test_update_invalid_status(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        result = runner.invoke(app, ["ideas", "update", "idea-20260511-001", "--status", "invalid"])
        assert result.exit_code != 0
        assert "Invalid status" in result.output

    def test_update_sets_updated_at(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", updated_at="2020-01-01T00:00:00")
        runner.invoke(app, ["ideas", "update", "idea-20260511-001", "--priority", "high"])
        data = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert data["updated_at"] != "2020-01-01T00:00:00"


# ── remove ───────────────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_with_yes_flag(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Bye")
        result = runner.invoke(app, ["ideas", "remove", "idea-20260511-001", "--yes"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        assert not (auto_edit_home / "ideas" / "idea-20260511-001.yaml").exists()

    def test_remove_confirmed(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Bye")
        result = runner.invoke(app, ["ideas", "remove", "idea-20260511-001"], input="y\n")
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_remove_cancelled(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Stay")
        runner.invoke(app, ["ideas", "remove", "idea-20260511-001"], input="n\n")
        assert (auto_edit_home / "ideas" / "idea-20260511-001.yaml").exists()

    def test_remove_not_found(self, auto_edit_home):
        result = runner.invoke(app, ["ideas", "remove", "idea-nonexistent", "--yes"])
        assert result.exit_code != 0


# ── pick / unpick ────────────────────────────────────────────────────────────


def _write_plan(home: Path, period_id: str, **fields) -> Path:
    body = {
        "period": period_id,
        "kind": "week" if "-W" in period_id else "month",
        "longs": [
            {"id": "L1", "topic": "Long 1", "language": "pt", "format": "tutorial", "status": "planned"},
            {"id": "L2", "topic": "Long 2", "language": "pt", "format": "tutorial", "status": "planned"},
        ],
        "shorts": [
            {"id": "S1", "topic": "Short 1", "language": "pt", "format": "tutorial", "status": "planned"},
        ],
        **fields,
    }
    path = home / "plans" / f"{period_id}.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


class TestPick:
    def test_pick_links_idea_to_slot(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="My Tutorial", language="en", format="tutorial")
        _write_plan(auto_edit_home, "2026-W20")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20", "--slot", "L1"])
        assert result.exit_code == 0
        assert "Linked" in result.output

        idea = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert idea["status"] == "planned"
        assert idea["plan_id"] == "2026-W20/L1"

        plan = yaml.safe_load((auto_edit_home / "plans" / "2026-W20.yaml").read_text())
        l1 = plan["longs"][0]
        assert l1["topic"] == "My Tutorial"
        assert l1["language"] == "en"
        assert l1["idea_id"] == "idea-20260511-001"

    def test_pick_shows_available_slots(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        _write_plan(auto_edit_home, "2026-W20")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20"])
        assert result.exit_code == 0
        assert "Available slots" in result.output
        assert "L1" in result.output
        assert "L2" in result.output

    def test_pick_already_linked(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", plan_id="2026-W19/L1")
        _write_plan(auto_edit_home, "2026-W20")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20", "--slot", "L1"])
        assert result.exit_code != 0
        assert "already linked" in result.output

    def test_pick_slot_not_found(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        _write_plan(auto_edit_home, "2026-W20")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20", "--slot", "L99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_pick_plan_not_found(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W01", "--slot", "L1"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_pick_slot_already_has_source(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        _write_plan(auto_edit_home, "2026-W20", longs=[
            {"id": "L1", "topic": "Taken", "language": "pt", "format": "tutorial", "status": "planned", "source_folder": "/some/path"},
        ])
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20", "--slot", "L1"])
        assert result.exit_code != 0
        assert "source_folder" in result.output

    def test_pick_with_short_slot(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", title="Quick tip")
        _write_plan(auto_edit_home, "2026-W20")
        result = runner.invoke(app, ["ideas", "pick", "idea-20260511-001", "--plan", "2026-W20", "--slot", "S1"])
        assert result.exit_code == 0

        plan = yaml.safe_load((auto_edit_home / "plans" / "2026-W20.yaml").read_text())
        assert plan["shorts"][0]["topic"] == "Quick tip"
        assert plan["shorts"][0]["idea_id"] == "idea-20260511-001"


class TestUnpick:
    def test_unpick_unlinks(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", status="planned", plan_id="2026-W20/L1")
        _write_plan(auto_edit_home, "2026-W20", longs=[
            {"id": "L1", "topic": "My Tutorial", "language": "pt", "format": "tutorial", "status": "planned", "idea_id": "idea-20260511-001"},
            {"id": "L2", "topic": "Long 2", "language": "pt", "format": "tutorial", "status": "planned"},
        ])
        result = runner.invoke(app, ["ideas", "unpick", "idea-20260511-001"])
        assert result.exit_code == 0
        assert "Unlinked" in result.output

        idea = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert idea["status"] == "backlog"
        assert idea["plan_id"] is None

        plan = yaml.safe_load((auto_edit_home / "plans" / "2026-W20.yaml").read_text())
        assert "idea_id" not in plan["longs"][0]

    def test_unpick_not_linked(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001")
        result = runner.invoke(app, ["ideas", "unpick", "idea-20260511-001"])
        assert result.exit_code != 0
        assert "not linked" in result.output

    def test_unpick_plan_deleted(self, auto_edit_home):
        _write_idea(auto_edit_home, "idea-20260511-001", status="planned", plan_id="2026-W99/L1")
        result = runner.invoke(app, ["ideas", "unpick", "idea-20260511-001"])
        assert result.exit_code == 0
        assert "Unlinked" in result.output
        idea = yaml.safe_load((auto_edit_home / "ideas" / "idea-20260511-001.yaml").read_text())
        assert idea["status"] == "backlog"
