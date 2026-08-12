"""Tests for tools/executor.py — cut plan validation, interval building, and filter generation."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.executor import (
    _validate_plan,
    _build_keep_intervals,
    _invert_cuts,
    _merge_intervals,
    _build_filter,
    MIN_INTERVAL_DURATION,
)


# ── _validate_plan ───────────────────────────────────────────────────────────


class TestValidatePlan:
    def test_empty_plan_raises(self):
        with pytest.raises(ValueError, match="neither kept_segments nor cuts"):
            _validate_plan({}, 60.0)

    def test_valid_kept_segments(self):
        plan = {"kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}
        _validate_plan(plan, 60.0)  # should not raise

    def test_valid_cuts(self):
        plan = {"cuts": [{"start": 5, "end": 10}]}
        _validate_plan(plan, 60.0)  # should not raise

    def test_negative_start_raises(self):
        plan = {"kept_segments": [{"start": -1, "end": 10}]}
        with pytest.raises(ValueError, match="negative"):
            _validate_plan(plan, 60.0)

    def test_end_exceeds_duration_raises(self):
        plan = {"kept_segments": [{"start": 0, "end": 9999}]}
        with pytest.raises(ValueError, match="exceeds video duration"):
            _validate_plan(plan, 60.0)

    def test_end_within_tolerance(self):
        # end = duration + 0.5 should pass (1s tolerance)
        plan = {"kept_segments": [{"start": 0, "end": 60.5}]}
        _validate_plan(plan, 60.0)  # should not raise

    def test_empty_interval_raises(self):
        plan = {"kept_segments": [{"start": 10, "end": 10}]}
        with pytest.raises(ValueError, match="empty interval"):
            _validate_plan(plan, 60.0)

    def test_inverted_interval_raises(self):
        plan = {"kept_segments": [{"start": 20, "end": 10}]}
        with pytest.raises(ValueError, match="empty interval"):
            _validate_plan(plan, 60.0)

    def test_missing_start_raises(self):
        plan = {"kept_segments": [{"end": 10}]}
        with pytest.raises(ValueError, match="missing/invalid"):
            _validate_plan(plan, 60.0)

    def test_invalid_type_raises(self):
        plan = {"kept_segments": [{"start": "abc", "end": 10}]}
        with pytest.raises(ValueError, match="missing/invalid"):
            _validate_plan(plan, 60.0)

    def test_degenerate_cut_is_tolerated_with_kept_segments(self):
        # Real case: LLM planner emits a micro-inverted cut (0.08s) that is not
        # even used (kept_segments drives output). Must not crash the pipeline.
        plan = {
            "kept_segments": [{"start": 0, "end": 60}],
            "cuts": [{"start": 33.62, "end": 33.54}],
        }
        _validate_plan(plan, 60.0)  # should not raise

    def test_degenerate_cut_only_is_tolerated(self):
        # A degenerate cut is a no-op; dropping it (keep everything) beats crashing.
        plan = {"cuts": [{"start": 30, "end": 10}]}
        _validate_plan(plan, 60.0)  # should not raise

    def test_cut_missing_field_still_raises(self):
        plan = {"cuts": [{"start": 30}]}
        with pytest.raises(ValueError, match="missing/invalid"):
            _validate_plan(plan, 60.0)


# ── _invert_cuts ─────────────────────────────────────────────────────────────


class TestInvertCuts:
    def test_no_cuts(self):
        result = _invert_cuts([], 60.0)
        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 60.0

    def test_single_cut_in_middle(self):
        cuts = [{"start": 10, "end": 20}]
        result = _invert_cuts(cuts, 60.0)
        assert len(result) == 2
        assert result[0] == {"start": 0.0, "end": 10.0}
        assert result[1] == {"start": 20.0, "end": 60.0}

    def test_cut_at_start(self):
        cuts = [{"start": 0, "end": 5}]
        result = _invert_cuts(cuts, 60.0)
        assert len(result) == 1
        assert result[0]["start"] == 5.0

    def test_cut_at_end(self):
        cuts = [{"start": 55, "end": 60}]
        result = _invert_cuts(cuts, 60.0)
        assert len(result) == 1
        assert result[0]["end"] == 55.0

    def test_degenerate_cut_dropped(self):
        # Inverted cut (start>=end) is a no-op — must be ignored, not regress cursor.
        cuts = [{"start": 10, "end": 20}, {"start": 33.62, "end": 33.54}]
        result = _invert_cuts(cuts, 60.0)
        assert result == [{"start": 0.0, "end": 10.0}, {"start": 20.0, "end": 60.0}]


# ── _merge_intervals ─────────────────────────────────────────────────────────


class TestMergeIntervals:
    def test_empty(self):
        assert _merge_intervals([]) == []

    def test_no_overlap(self):
        intervals = [(0, 5), (10, 15)]
        assert _merge_intervals(intervals) == [(0, 5), (10, 15)]

    def test_overlap(self):
        intervals = [(0, 10), (5, 15)]
        assert _merge_intervals(intervals) == [(0, 15)]

    def test_touching(self):
        intervals = [(0, 5), (5, 10)]
        assert _merge_intervals(intervals) == [(0, 10)]

    def test_contained(self):
        intervals = [(0, 20), (5, 10)]
        assert _merge_intervals(intervals) == [(0, 20)]


# ── _build_keep_intervals ───────────────────────────────────────────────────


class TestBuildKeepIntervals:
    def test_from_kept_segments(self):
        plan = {"kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}
        intervals = _build_keep_intervals(plan, 60.0)
        assert len(intervals) == 2
        # end should have END_PADDING applied
        assert intervals[0][1] > 10.0

    def test_from_cuts(self):
        plan = {"cuts": [{"start": 10, "end": 20}]}
        intervals = _build_keep_intervals(plan, 60.0)
        assert len(intervals) == 2

    def test_filters_subframe_intervals(self):
        # All segments so small that even after END_PADDING they remain sub-frame
        # Use cuts that leave only a tiny gap (< MIN_INTERVAL_DURATION)
        # Use cuts to create a tiny kept interval where padding doesn't help.
        plan2 = {"cuts": [{"start": 0, "end": 59.99}]}
        # Only kept: [59.99, 60.0] = 0.01s. After padding: end = min(60.0, 60.0+0.2) = 60.0.
        # Interval = 0.01s < MIN_INTERVAL_DURATION.
        with pytest.raises(RuntimeError, match="shorter than 1 frame"):
            _build_keep_intervals(plan2, 60.0)

    def test_keeps_normal_intervals(self):
        plan = {"kept_segments": [{"start": 0, "end": 1}]}
        intervals = _build_keep_intervals(plan, 60.0)
        assert len(intervals) == 1
        assert intervals[0][1] - intervals[0][0] >= MIN_INTERVAL_DURATION


# ── end padding vs. silence ─────────────────────────────────────────────────
# 0.1s buckets: speech until 10.0s, then the pause the cut removes.
SPEECH_DB, ROOM_DB = -14.0, -30.0
ENERGY = [SPEECH_DB] * 100 + [ROOM_DB] * 100 + [SPEECH_DB] * 400
ENERGY_RES = 0.1


class TestEndPaddingStopsAtSilence:
    def test_padding_does_not_reach_into_a_silent_cut(self):
        """The 0.2s tail guard was re-adding the head of every camera move."""
        plan = {"kept_segments": [{"start": 0, "end": 10.0}]}
        intervals = _build_keep_intervals(plan, 60.0, ENERGY, ENERGY_RES)
        assert intervals[0][1] == 10.0

    def test_padding_still_protects_a_word_tail(self):
        """Audio still audible past the boundary — the pad is doing its job."""
        plan = {"kept_segments": [{"start": 0, "end": 5.0}]}
        intervals = _build_keep_intervals(plan, 60.0, ENERGY, ENERGY_RES)
        assert intervals[0][1] == pytest.approx(5.2)

    def test_padding_stops_where_the_speech_stops(self):
        """Boundary 0.1s before the pause: pad that 0.1s, not the full 0.2s."""
        plan = {"kept_segments": [{"start": 0, "end": 9.9}]}
        intervals = _build_keep_intervals(plan, 60.0, ENERGY, ENERGY_RES)
        assert intervals[0][1] == pytest.approx(10.0)

    def test_no_energy_map_keeps_the_old_blind_padding(self):
        plan = {"kept_segments": [{"start": 0, "end": 10.0}]}
        assert _build_keep_intervals(plan, 60.0)[0][1] == pytest.approx(10.2)

    def test_boundary_that_lands_on_a_float_bucket_edge_terminates(self):
        """68.8/0.1 is 687.9999…, so bucket 688 starts at exactly 68.8 again.

        Walking the map by recomputing the next edge as (index+1)*resolution
        then never advances past the boundary — the executor hangs forever.
        """
        plan = {"kept_segments": [{"start": 0, "end": 68.8}]}
        intervals = _build_keep_intervals(plan, 120.0, [-14.0] * 1200, 0.1)
        assert intervals[0][1] == pytest.approx(69.0)


# ── _build_filter ────────────────────────────────────────────────────────────


class TestBuildFilter:
    def test_single_interval(self):
        f = _build_filter([(0.0, 10.0)])
        assert "trim=start=0.000:end=10.000" in f
        assert "concat=n=1" in f
        assert "loudnorm" in f

    def test_multiple_intervals(self):
        f = _build_filter([(0.0, 5.0), (10.0, 15.0)])
        assert "concat=n=2" in f
        assert "[v0]" in f
        assert "[v1]" in f

    def test_loudnorm_present(self):
        f = _build_filter([(0.0, 10.0)])
        assert "loudnorm=I=-16:TP=-1.5:LRA=11" in f
        assert "[outa_raw]" in f
        assert "[outa]" in f


# ── _resolve_reframe ─────────────────────────────────────────────────────────

class TestResolveReframe:
    def test_short_landscape_reframes(self):
        from tools.executor import _resolve_reframe
        assert _resolve_reframe("short", 1920, 1080) == (1080, 1920)

    def test_short_already_vertical_skips(self):
        from tools.executor import _resolve_reframe
        assert _resolve_reframe("short", 1080, 1920) is None

    def test_long_never_reframes(self):
        from tools.executor import _resolve_reframe
        assert _resolve_reframe("long", 1920, 1080) is None

    def test_env_no_reframe_disables(self, monkeypatch):
        from tools.executor import _resolve_reframe
        monkeypatch.setenv("AUTO_EDIT_NO_REFRAME", "1")
        assert _resolve_reframe("short", 1920, 1080) is None

    def test_env_no_reframe_zero_still_reframes(self, monkeypatch):
        from tools.executor import _resolve_reframe
        monkeypatch.setenv("AUTO_EDIT_NO_REFRAME", "0")
        assert _resolve_reframe("short", 1920, 1080) == (1080, 1920)
