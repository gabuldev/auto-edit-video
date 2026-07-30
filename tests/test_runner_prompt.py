"""Prompt assembly: long-form uses the curation planner, short-form does not."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_edit import runner

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def _workspace(tmp_path: Path, video_type: str, **plan_extra) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(
        json.dumps({"type": video_type, "context": "tutorial", "stage": "plan"}),
        encoding="utf-8",
    )
    (ws / "transcription.json").write_text(
        json.dumps(
            {
                "duration": 120.0,
                "segments": [{"start": 0.0, "end": 5.0, "text": "olá"}],
                "words": [{"word": "olá", "start": 0.0, "end": 0.4}],
            }
        ),
        encoding="utf-8",
    )
    cut_plan = {"cuts": [], "kept_segments": [{"start": 0.0, "end": 120.0}]}
    cut_plan.update(plan_extra)
    (ws / "cut_plan.json").write_text(json.dumps(cut_plan), encoding="utf-8")
    return ws


def test_resolve_prompt_file_swaps_long_planner():
    resolved = runner._resolve_prompt_file("plan", "long", AGENTS_DIR / "planner.md")
    assert resolved.name == "planner_long.md"


@pytest.mark.parametrize(
    "stage,video_type",
    [("plan", "short"), ("review", "long"), ("metadata", "long")],
)
def test_resolve_prompt_file_keeps_default(stage, video_type):
    prompt = AGENTS_DIR / "planner.md"
    assert runner._resolve_prompt_file(stage, video_type, prompt) == prompt


def test_resolve_prompt_file_falls_back_when_missing(tmp_path):
    prompt = tmp_path / "planner.md"
    prompt.write_text("base", encoding="utf-8")
    assert runner._resolve_prompt_file("plan", "long", prompt) == prompt


def test_long_plan_prompt_uses_curation_and_skips_generic_pacing(tmp_path):
    ws = _workspace(tmp_path, "long")
    prompt = runner.build_prompt("plan", ws, AGENTS_DIR / "planner.md")

    assert "Long-Form Video Planner Agent" in prompt
    assert "dropped_blocks" in prompt
    # The generic long-form pacing block would duplicate planner_long.md's rules.
    assert "## Pacing (long-form)" not in prompt


def test_short_plan_prompt_unchanged(tmp_path):
    ws = _workspace(tmp_path, "short")
    prompt = runner.build_prompt("plan", ws, AGENTS_DIR / "planner.md")

    assert "Video Planner Agent" in prompt
    assert "Long-Form Video Planner Agent" not in prompt
    assert "## Pacing (short-form)" in prompt


def test_long_review_prompt_gets_curation_notes_when_blocks_dropped(tmp_path):
    ws = _workspace(
        tmp_path,
        "long",
        dropped_blocks=[
            {"start": 10.0, "end": 40.0, "topic": "tangente", "reason": "off-topic"}
        ],
    )
    prompt = runner.build_prompt("review", ws, AGENTS_DIR / "reviewer.md")

    assert "## Curation Review (long-form)" in prompt
    assert "target_rationale" in prompt


def test_long_review_prompt_omits_curation_notes_without_blocks(tmp_path):
    ws = _workspace(tmp_path, "long")
    prompt = runner.build_prompt("review", ws, AGENTS_DIR / "reviewer.md")

    assert "## Curation Review (long-form)" not in prompt
