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
