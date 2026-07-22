"""Tests for auto_edit/pipeline.py — state machine, stage transitions, error persistence."""
import pytest
from auto_edit import pipeline as pl


@pytest.fixture
def workspace(tmp_path):
    """Create a temp workspace with a minimal pipeline.json."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    # Create a dummy video path
    video = tmp_path / "test.mp4"
    video.write_text("")  # empty placeholder
    pl.init(ws, video, "short", "test context")
    return ws


class TestInit:
    def test_creates_pipeline_json(self, workspace):
        assert (workspace / "pipeline.json").exists()

    def test_stages_present(self, workspace):
        p = pl.load(workspace)
        for stage in pl.STAGES[:-1]:  # all except "done"
            assert stage in p["stages"]

    def test_short_skips_overlay(self, workspace):
        p = pl.load(workspace)
        assert p["stages"]["overlay"]["status"] == "skip"

    def test_short_has_caption(self, workspace):
        p = pl.load(workspace)
        assert p["stages"]["caption"]["status"] == "pending"

    def test_long_skips_caption(self, tmp_path):
        ws = tmp_path / "long_ws"
        ws.mkdir()
        video = tmp_path / "test.mp4"
        video.write_text("")
        pl.init(ws, video, "long", "test")
        p = pl.load(ws)
        assert p["stages"]["caption"]["status"] == "skip"

    def test_long_has_overlay(self, tmp_path):
        ws = tmp_path / "long_ws"
        ws.mkdir()
        video = tmp_path / "test.mp4"
        video.write_text("")
        pl.init(ws, video, "long", "test")
        p = pl.load(ws)
        assert p["stages"]["overlay"]["status"] == "pending"

    def test_initial_stage_is_extract(self, workspace):
        p = pl.load(workspace)
        assert p["current_stage"] == "extract"

    def test_default_whisper_model(self, workspace):
        p = pl.load(workspace)
        assert p["whisper_model"] == "base"  # default from init params

    def test_plan_id_default_none(self, workspace):
        p = pl.load(workspace)
        assert p["plan_id"] is None

    def test_plan_id_persisted(self, tmp_path):
        ws = tmp_path / "linked_ws"
        ws.mkdir()
        video = tmp_path / "v.mp4"
        video.write_text("")
        pl.init(ws, video, "short", "ctx", plan_id="2026-W19/S2")
        assert pl.load(ws)["plan_id"] == "2026-W19/S2"


class TestSetStageStatus:
    def test_mark_complete_advances(self, workspace):
        p = pl.set_stage_status(workspace, "extract", "complete")
        assert p["current_stage"] == "plan"
        assert "completed_at" in p["stages"]["extract"]

    def test_mark_failed_records_time(self, workspace):
        p = pl.set_stage_status(workspace, "extract", "failed")
        assert "failed_at" in p["stages"]["extract"]

    def test_mark_failed_with_error(self, workspace):
        p = pl.set_stage_status(workspace, "extract", "failed", error="something broke")
        assert p["stages"]["extract"]["error"] == "something broke"

    def test_error_truncated_to_2000(self, workspace):
        long_error = "x" * 5000
        p = pl.set_stage_status(workspace, "extract", "failed", error=long_error)
        assert len(p["stages"]["extract"]["error"]) == 2000

    def test_complete_skips_overlay_for_short(self, workspace):
        # Complete all stages up to execute
        for stage in ["extract", "plan", "review", "execute"]:
            pl.set_stage_status(workspace, stage, "complete")
        p = pl.load(workspace)
        # Should skip overlay and go to caption
        assert p["current_stage"] == "caption"

    def test_mark_running(self, workspace):
        p = pl.set_stage_status(workspace, "extract", "running")
        assert p["stages"]["extract"]["status"] == "running"


class TestLoopBack:
    def test_increments_iteration(self, workspace):
        p = pl.load(workspace)
        assert p["iteration"] == 1
        p = pl.loop_back(workspace)
        assert p["iteration"] == 2

    def test_resets_stages(self, workspace):
        # Complete some stages first
        for stage in ["extract", "plan", "review", "execute"]:
            pl.set_stage_status(workspace, stage, "complete")
        p = pl.loop_back(workspace)
        assert p["stages"]["plan"]["status"] == "pending"
        assert p["stages"]["review"]["status"] == "pending"
        assert p["current_stage"] == "plan"
        # extract should remain complete
        assert p["stages"]["extract"]["status"] == "complete"


class TestSetStage:
    def test_sets_stage_and_resets_forward(self, workspace):
        for stage in ["extract", "plan", "review"]:
            pl.set_stage_status(workspace, stage, "complete")
        p = pl.set_stage(workspace, "plan")
        assert p["current_stage"] == "plan"
        assert p["stages"]["plan"]["status"] == "pending"
        assert p["stages"]["review"]["status"] == "pending"
        assert p["stages"]["extract"]["status"] == "complete"


# ── _merge_target ────────────────────────────────────────────────────────────

class TestMergeTarget:
    def test_all_portrait_picks_portrait(self):
        from auto_edit.cli import _merge_target
        res = [(2192, 2928), (2192, 2928), (2208, 2928), (2128, 2848)]
        w, h = _merge_target(res)
        assert h > w  # stays portrait
        assert (w, h) == (2192, 2928)  # most common resolution wins

    def test_all_portrait_tie_largest_area_wins(self):
        from auto_edit.cli import _merge_target
        res = [(2192, 2928), (2208, 2928), (2128, 2848)]
        assert _merge_target(res) == (2208, 2928)

    def test_all_landscape_picks_largest_16_9(self):
        from auto_edit.cli import _merge_target
        res = [(1920, 1080), (3840, 2160), (1280, 720)]
        assert _merge_target(res) == (3840, 2160)

    def test_mixed_orientation_majority_wins(self):
        from auto_edit.cli import _merge_target
        res = [(1080, 1920), (1080, 1920), (1920, 1080)]
        w, h = _merge_target(res)
        assert h > w

    def test_landscape_no_16_9_defaults_1080p(self):
        from auto_edit.cli import _merge_target
        res = [(1440, 1080), (1600, 1200)]
        assert _merge_target(res) == (1920, 1080)

    def test_odd_dimensions_rounded_even(self):
        from auto_edit.cli import _merge_target
        res = [(1081, 1921), (1081, 1921), (721, 1281)]
        w, h = _merge_target(res)
        assert w % 2 == 0 and h % 2 == 0
