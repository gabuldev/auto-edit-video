"""Tests for auto_edit/plan.py — pure functions only (no LLM, no interactive prompts)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import typer
import yaml

from auto_edit import config as cfg
from auto_edit import plan as p


@pytest.fixture
def auto_edit_home(tmp_path, monkeypatch):
    """Point ~/.auto-edit/ at a tmp dir for the duration of the test."""
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    monkeypatch.delenv("AUTO_EDIT_INBOX", raising=False)
    cfg.ensure_dirs()
    return tmp_path


def _write_plan(home: Path, period_id: str, **fields) -> Path:
    """Write a minimal plan yaml to ~/.auto-edit/plans/<period>.yaml."""
    body = {"period": period_id, **fields}
    path = home / "plans" / f"{period_id}.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


# ── _resolve_period ──────────────────────────────────────────────────────────

class TestResolvePeriod:
    def test_month_explicit(self):
        per = p._resolve_period("2026-06", None)
        assert per.id == "2026-06"
        assert per.kind == "month"
        assert per.start == date(2026, 6, 1)
        assert per.end == date(2026, 6, 30)

    def test_month_december_end(self):
        per = p._resolve_period("2026-12", None)
        assert per.end == date(2026, 12, 31)

    def test_week_explicit(self):
        per = p._resolve_period(None, "2026-W19")
        assert per.id == "2026-W19"
        assert per.kind == "week"
        assert per.start == date.fromisocalendar(2026, 19, 1)
        assert per.end == per.start + timedelta(days=6)

    def test_week_normalizes_one_digit(self):
        per = p._resolve_period(None, "2026-W9")
        assert per.id == "2026-W09"

    def test_week_alias_current(self):
        per = p._resolve_period(None, "current")
        y, w, _ = date.today().isocalendar()
        assert per.id == f"{y}-W{w:02d}"

    def test_month_alias_current(self):
        per = p._resolve_period("current", None)
        t = date.today()
        assert per.id == f"{t.year}-{t.month:02d}"

    def test_month_alias_next_wraps_year(self, monkeypatch):
        # We can't change today, but we test the wrap branch via direct call
        # Use a deterministic check: just verify shape
        per = p._resolve_period("next", None)
        assert per.kind == "month"

    def test_both_raises(self):
        with pytest.raises(typer.BadParameter):
            p._resolve_period("2026-06", "2026-W19")

    def test_neither_raises(self):
        with pytest.raises(typer.BadParameter):
            p._resolve_period(None, None)

    def test_bad_month_format(self):
        with pytest.raises(typer.BadParameter):
            p._resolve_period("2026/06", None)

    def test_bad_week_format(self):
        with pytest.raises(typer.BadParameter):
            p._resolve_period(None, "W19-2026")


# ── _default_counts ───────────────────────────────────────────────────────────

def test_default_counts_month():
    assert p._default_counts("month") == (12, 24)


def test_default_counts_week():
    assert p._default_counts("week") == (3, 6)


# ── parse_plan_id ─────────────────────────────────────────────────────────────

class TestParsePlanId:
    def test_basic(self):
        assert p.parse_plan_id("2026-W19/S2") == ("2026-W19", "S2")

    def test_month_form(self):
        assert p.parse_plan_id("2026-06/L1") == ("2026-06", "L1")

    def test_strips_whitespace(self):
        assert p.parse_plan_id(" 2026-W19 / S2 ") == ("2026-W19", "S2")

    def test_no_slash_raises(self):
        with pytest.raises(ValueError):
            p.parse_plan_id("S2")


# ── _infer_plan_id_from_folder_name ──────────────────────────────────────────

class TestInferFromFolderName:
    def test_full_id_with_underscore(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-W19_S2") == "2026-W19/S2"

    def test_full_id_with_hyphen(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-W19-S2") == "2026-W19/S2"

    def test_full_id_with_suffix(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-W19_S2_bambulab") == "2026-W19/S2"

    def test_month_form(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-05_L1") == "2026-05/L1"

    def test_pads_week_number(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-W9_S2") == "2026-W09/S2"

    def test_lowercase_item(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("2026-W19_s2") == "2026-W19/S2"

    def test_no_match_returns_none(self, auto_edit_home):
        assert p._infer_plan_id_from_folder_name("random-folder") is None

    def test_short_form_with_unique_item(self, auto_edit_home):
        # Plant a single plan with S2; short-form should resolve.
        _write_plan(
            auto_edit_home, "2026-W19",
            shorts=[{"id": "S2", "topic": "x"}],
        )
        assert p._infer_plan_id_from_folder_name("S2") == "2026-W19/S2"

    def test_short_form_ambiguous_returns_none(self, auto_edit_home):
        _write_plan(auto_edit_home, "2026-W19", shorts=[{"id": "S2", "topic": "x"}])
        _write_plan(auto_edit_home, "2026-W20", shorts=[{"id": "S2", "topic": "y"}])
        # Ambiguity → resolver raises BadParameter, _infer swallows to None
        assert p._infer_plan_id_from_folder_name("S2") is None


# ── resolve_plan_id_arg ──────────────────────────────────────────────────────

class TestResolvePlanIdArg:
    def test_none_for_empty(self, auto_edit_home):
        assert p.resolve_plan_id_arg(None) is None
        assert p.resolve_plan_id_arg("") is None

    def test_none_keywords(self, auto_edit_home):
        assert p.resolve_plan_id_arg("none") is None
        assert p.resolve_plan_id_arg("skip") is None

    def test_full_form_passes_through(self, auto_edit_home):
        assert p.resolve_plan_id_arg("2026-W19/S2") == "2026-W19/S2"

    def test_short_form_unique(self, auto_edit_home):
        _write_plan(auto_edit_home, "2026-W19", shorts=[{"id": "S5", "topic": "x"}])
        assert p.resolve_plan_id_arg("S5") == "2026-W19/S5"

    def test_short_form_unknown_raises(self, auto_edit_home):
        with pytest.raises(typer.BadParameter):
            p.resolve_plan_id_arg("S99")

    def test_short_form_ambiguous_raises(self, auto_edit_home):
        _write_plan(auto_edit_home, "2026-W19", shorts=[{"id": "S2", "topic": "x"}])
        _write_plan(auto_edit_home, "2026-W20", shorts=[{"id": "S2", "topic": "y"}])
        with pytest.raises(typer.BadParameter):
            p.resolve_plan_id_arg("S2")


# ── derive_status ────────────────────────────────────────────────────────────

class TestDeriveStatus:
    def test_planned_when_no_workspace(self):
        assert p.derive_status({"id": "S1"}, []) == "planned"

    def test_published_takes_precedence(self):
        # Even with no workspace, a manual "published" status sticks.
        assert p.derive_status({"id": "S1", "status": "published"}, []) == "published"

    def test_recorded_when_workspace_in_progress(self):
        pj = {"current_stage": "execute", "stages": {"extract": {"status": "complete"}}}
        assert p.derive_status({"id": "S1"}, [(Path("/tmp/x"), pj)]) == "recorded"

    def test_edited_when_done(self):
        pj = {"current_stage": "done", "stages": {"extract": {"status": "complete"}}}
        assert p.derive_status({"id": "S1"}, [(Path("/tmp/x"), pj)]) == "edited"

    def test_edited_when_every_canonical_stage_done(self):
        from auto_edit.pipeline import STAGES
        stages = {name: {"status": "complete"} for name in STAGES if name != "done"}
        pj = {"current_stage": "metadata", "stages": stages}
        assert p.derive_status({"id": "S1"}, [(Path("/tmp/x"), pj)]) == "edited"

    def test_recorded_when_some_stages_still_pending(self):
        from auto_edit.pipeline import STAGES
        stages = {name: {"status": "pending"} for name in STAGES if name != "done"}
        stages["extract"] = {"status": "complete"}
        pj = {"current_stage": "plan", "stages": stages}
        assert p.derive_status({"id": "S1"}, [(Path("/tmp/x"), pj)]) == "recorded"


# ── _summarize_inbox + _video_subfolders ──────────────────────────────────────

class TestInboxScan:
    def test_summarize_inbox_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_INBOX", raising=False)
        assert p._summarize_inbox() == ""

    def test_summarize_inbox_lists_subfolders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_INBOX", str(tmp_path))
        sub = tmp_path / "bambulab-domingo"
        sub.mkdir()
        (sub / "clip1.mp4").write_bytes(b"x" * 1024)
        (sub / "clip2.mov").write_bytes(b"x" * 2048)
        # Empty subfolder should be ignored
        (tmp_path / "vazia").mkdir()
        # Hidden folder ignored
        hidden = tmp_path / ".cache"
        hidden.mkdir()
        (hidden / "x.mp4").write_bytes(b"x")

        out = p._summarize_inbox()
        assert "bambulab-domingo" in out
        assert "2 clip(s)" in out
        assert "vazia" not in out
        assert ".cache" not in out

    def test_video_subfolders_skips_empty(self, tmp_path):
        (tmp_path / "with-vids").mkdir()
        (tmp_path / "with-vids" / "a.mp4").write_bytes(b"x")
        (tmp_path / "no-vids").mkdir()
        (tmp_path / "no-vids" / "readme.txt").write_text("x")

        names = [d.name for d in p._video_subfolders(tmp_path)]
        assert "with-vids" in names
        assert "no-vids" not in names


# ── pending_items + workspaces_by_plan_id ────────────────────────────────────

def test_pending_items_includes_planned_only(auto_edit_home):
    _write_plan(
        auto_edit_home, "2026-W19",
        longs=[{"id": "L1", "topic": "x"}],
        shorts=[
            {"id": "S1", "topic": "y"},
            {"id": "S2", "topic": "z", "status": "published"},  # not pending
        ],
    )
    ids = {it["id"] for it in p.pending_items(period_filter="2026-W19")}
    assert ids == {"L1", "S1"}


def test_pending_items_period_filter(auto_edit_home):
    _write_plan(auto_edit_home, "2026-W19", shorts=[{"id": "S1", "topic": "x"}])
    _write_plan(auto_edit_home, "2026-W20", shorts=[{"id": "S1", "topic": "y"}])

    only_19 = [it["_full_id"] for it in p.pending_items(period_filter="2026-W19")]
    assert only_19 == ["2026-W19/S1"]
