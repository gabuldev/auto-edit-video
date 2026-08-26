"""Tests for auto_edit.cli._resolve_plan — when the plan picker shows up."""
import pytest

from auto_edit import cli
from auto_edit import plan as plan_mod


@pytest.fixture
def picker_spy(monkeypatch):
    """Record whether the interactive picker was reached."""
    calls = {"pending": 0, "prompt": 0}

    def fake_pending():
        calls["pending"] += 1
        return [{"_full_id": "2026-W18/L1", "id": "L1", "_kind": "long", "topic": "x"}]

    def fake_prompt():
        calls["prompt"] += 1
        return "2026-W18/L1"

    monkeypatch.setattr(plan_mod, "pending_items", fake_pending)
    monkeypatch.setattr(plan_mod, "prompt_for_plan_id", fake_prompt)
    return calls


class TestResolvePlan:
    def test_no_flags_never_prompts(self, picker_spy):
        # Editing a video without asking for a plan link must run straight through
        assert cli._resolve_plan(None, False, None) is None
        assert picker_spy["prompt"] == 0

    def test_no_flags_does_not_even_read_pending_items(self, picker_spy):
        cli._resolve_plan(None, False, None)
        assert picker_spy["pending"] == 0

    def test_plan_prompt_flag_opts_in(self, picker_spy):
        assert cli._resolve_plan(None, True, None) == "2026-W18/L1"
        assert picker_spy["prompt"] == 1

    def test_prompt_skipped_when_no_pending_items(self, monkeypatch, picker_spy):
        monkeypatch.setattr(plan_mod, "pending_items", lambda: [])
        assert cli._resolve_plan(None, True, None) is None
        assert picker_spy["prompt"] == 0

    def test_explicit_plan_id_wins_over_prompt(self, monkeypatch, picker_spy):
        monkeypatch.setattr(plan_mod, "resolve_plan_id_arg", lambda raw: f"2026-W19/{raw}")
        assert cli._resolve_plan("S2", True, None) == "2026-W19/S2"
        assert picker_spy["prompt"] == 0

    def test_resume_ignores_plan_entirely(self, monkeypatch, picker_spy):
        monkeypatch.setattr(plan_mod, "resolve_plan_id_arg", lambda raw: raw)
        assert cli._resolve_plan("S2", True, "plan") is None
        assert picker_spy["prompt"] == 0
