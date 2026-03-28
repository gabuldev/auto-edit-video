"""Tests for tools/captioner.py — remap, interval building, word grouping."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.captioner import (
    _remap,
    _build_kept_intervals,
    _remap_words,
    _group_words,
)


# ── _remap ───────────────────────────────────────────────────────────────────


class TestRemap:
    def test_within_first_segment(self):
        kept = [(5.0, 15.0), (20.0, 30.0)]
        assert _remap(7.0, kept) == 2.0  # 7.0 - 5.0

    def test_within_second_segment(self):
        kept = [(5.0, 15.0), (20.0, 30.0)]
        # accumulated = 10.0 (from first segment), then 22.0 - 20.0 = 2.0
        assert _remap(22.0, kept) == 12.0

    def test_in_cut_region(self):
        kept = [(5.0, 15.0), (20.0, 30.0)]
        assert _remap(17.0, kept) is None  # between segments = cut

    def test_before_first_segment(self):
        kept = [(5.0, 15.0)]
        assert _remap(2.0, kept) is None  # before first kept

    def test_after_last_segment(self):
        kept = [(5.0, 15.0)]
        assert _remap(20.0, kept) is None  # after last kept

    def test_at_segment_boundary_start(self):
        kept = [(5.0, 15.0)]
        assert _remap(5.0, kept) == 0.0  # exactly at start

    def test_at_segment_boundary_end(self):
        kept = [(5.0, 15.0)]
        assert _remap(15.0, kept) == 10.0  # exactly at end


# ── _build_kept_intervals ───────────────────────────────────────────────────


class TestBuildKeptIntervals:
    def test_from_kept_segments(self):
        plan = {"kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}
        result = _build_kept_intervals(plan, 60.0)
        assert result == [(0.0, 10.0), (20.0, 30.0)]

    def test_from_cuts(self):
        plan = {"cuts": [{"start": 10, "end": 20}]}
        result = _build_kept_intervals(plan, 60.0)
        assert result == [(0.0, 10.0), (20.0, 60.0)]

    def test_cut_at_start(self):
        plan = {"cuts": [{"start": 0, "end": 5}]}
        result = _build_kept_intervals(plan, 60.0)
        assert result == [(5.0, 60.0)]

    def test_multiple_cuts(self):
        plan = {"cuts": [{"start": 5, "end": 10}, {"start": 20, "end": 25}]}
        result = _build_kept_intervals(plan, 60.0)
        assert result == [(0.0, 5.0), (10.0, 20.0), (25.0, 60.0)]


# ── _remap_words ─────────────────────────────────────────────────────────────


class TestRemapWords:
    def test_words_in_kept_region(self):
        words = [
            {"word": "hello", "start": 6.0, "end": 7.0},
            {"word": "world", "start": 8.0, "end": 9.0},
        ]
        kept = [(5.0, 15.0)]
        remapped, _ = _remap_words(words, [], kept)
        assert len(remapped) == 2
        assert remapped[0]["start"] == 1.0  # 6.0 - 5.0
        assert remapped[1]["word"] == "world"

    def test_words_in_cut_region_dropped(self):
        words = [
            {"word": "kept", "start": 6.0, "end": 7.0},
            {"word": "cut", "start": 17.0, "end": 18.0},  # in gap
        ]
        kept = [(5.0, 15.0), (20.0, 30.0)]
        remapped, _ = _remap_words(words, [], kept)
        assert len(remapped) == 1
        assert remapped[0]["word"] == "kept"

    def test_segments_remapped(self):
        segments = [{"text": "hello", "start": 6.0, "end": 9.0}]
        kept = [(5.0, 15.0)]
        _, remapped_segs = _remap_words([], segments, kept)
        assert len(remapped_segs) == 1
        assert remapped_segs[0]["start"] == 1.0

    def test_missing_fields_skipped(self):
        words = [{"word": "bad_entry"}]  # no start/end
        kept = [(0.0, 10.0)]
        remapped, _ = _remap_words(words, [], kept)
        assert len(remapped) == 0


# ── _group_words ─────────────────────────────────────────────────────────────


class TestGroupWords:
    def test_groups_max_4_words(self):
        words = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(8)]
        groups = _group_words(words)
        for group in groups:
            assert len(group) <= 4

    def test_gap_breaks_group(self):
        words = [
            {"word": "a", "start": 0.0, "end": 0.2},
            {"word": "b", "start": 0.3, "end": 0.5},
            {"word": "c", "start": 2.0, "end": 2.2},  # big gap
        ]
        groups = _group_words(words)
        assert len(groups) >= 2

    def test_empty_input(self):
        assert _group_words([]) == []
