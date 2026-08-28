"""Tests for auto_edit/shorts.py."""
import pytest

from auto_edit.shorts import (
    DEFAULT_MAX_DURATION,
    ShortsError,
    parse_pick,
    snap_clip_to_words,
    validate_clips,
)


def clip(start, end, hook="gancho"):
    return {"start": start, "end": end, "hook": hook, "reason": "r", "score": 7}


class TestValidateClips:
    def test_keeps_a_well_formed_clip(self):
        valid, rejected = validate_clips([clip(10.0, 40.0)], source_duration=378.0)
        assert len(valid) == 1
        assert rejected == []
        assert valid[0]["start"] == 10.0

    def test_rejects_end_before_start(self):
        valid, rejected = validate_clips([clip(40.0, 10.0)], source_duration=378.0)
        assert valid == []
        assert "1:" in rejected[0]

    def test_rejects_clip_past_the_end_of_the_video(self):
        valid, rejected = validate_clips([clip(360.0, 400.0)], source_duration=378.0)
        assert valid == []

    def test_rejects_clip_longer_than_the_cap(self):
        valid, rejected = validate_clips(
            [clip(0.0, 120.0)], source_duration=378.0, max_duration=DEFAULT_MAX_DURATION
        )
        assert valid == []
        assert "90" in rejected[0]

    def test_rejects_clip_shorter_than_the_floor(self):
        valid, rejected = validate_clips([clip(10.0, 12.0)], source_duration=378.0)
        assert valid == []

    def test_rejects_non_numeric_boundaries(self):
        valid, rejected = validate_clips(
            [{"start": "abc", "end": 40.0, "hook": "h"}], source_duration=378.0
        )
        assert valid == []
        assert rejected

    def test_one_bad_clip_does_not_drop_the_good_ones(self):
        valid, rejected = validate_clips(
            [clip(10.0, 40.0), clip(40.0, 10.0), clip(50.0, 90.0)],
            source_duration=378.0,
        )
        assert len(valid) == 2
        assert len(rejected) == 1

    def test_empty_list_is_empty_not_an_error(self):
        assert validate_clips([], source_duration=378.0) == ([], [])


class TestParsePick:
    def test_single_index(self):
        assert parse_pick("1", count=3) == [0]

    def test_comma_separated_is_sorted_and_deduped(self):
        assert parse_pick("3,1,3", count=3) == [0, 2]

    def test_tolerates_spaces(self):
        assert parse_pick(" 1 , 2 ", count=3) == [0, 1]

    def test_zero_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("0", count=3)

    def test_index_past_the_end_is_rejected_and_lists_the_valid_range(self):
        with pytest.raises(ShortsError, match="1-3"):
            parse_pick("9", count=3)

    def test_non_numeric_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("a", count=3)

    def test_empty_string_is_rejected(self):
        with pytest.raises(ShortsError):
            parse_pick("", count=3)


WORDS = [
    {"word": "Galera,", "start": 0.0, "end": 0.62},
    {"word": "a", "start": 0.68, "end": 0.86},
    {"word": "saga", "start": 0.86, "end": 1.26},
    {"word": "continua.", "start": 2.44, "end": 3.10},
    {"word": "Entao", "start": 4.00, "end": 4.40},
]


class TestSnapClipToWords:
    def test_start_moves_forward_to_the_next_word_onset(self):
        start, _ = snap_clip_to_words(0.70, 3.10, WORDS)
        assert start == 0.86

    def test_end_moves_back_to_the_previous_word_tail(self):
        _, end = snap_clip_to_words(0.0, 2.90, WORDS)
        assert end == 1.26

    def test_boundaries_already_on_word_edges_are_untouched(self):
        assert snap_clip_to_words(0.86, 3.10, WORDS) == (0.86, 3.10)

    def test_window_with_no_words_is_left_alone(self):
        assert snap_clip_to_words(10.0, 20.0, WORDS) == (10.0, 20.0)

    def test_empty_word_list_is_left_alone(self):
        assert snap_clip_to_words(1.0, 2.0, []) == (1.0, 2.0)

    def test_words_with_bad_timestamps_are_ignored(self):
        words = [{"word": "x", "start": None, "end": 1.0}, *WORDS]
        assert snap_clip_to_words(0.70, 3.10, words)[0] == 0.86

    def test_word_straddling_end_edge_is_not_snapped(self):
        # Only word in window straddles the end edge (starts inside, ends outside).
        # Window is returned unchanged to avoid cutting mid-syllable.
        assert snap_clip_to_words(0.9, 1.0, WORDS) == (0.9, 1.0)

    def test_straddling_words_are_excluded_from_snap(self):
        # Words straddling either edge (start or end) are not fully contained.
        # Only "saga" (0.86-1.26) is fully contained in (0.70, 3.0).
        # "a" straddles start (0.68-0.86, starts before 0.70).
        # "continua." straddles end (2.44-3.10, ends after 3.0).
        assert snap_clip_to_words(0.70, 3.0, WORDS) == (0.86, 1.26)
