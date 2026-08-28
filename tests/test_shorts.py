"""Tests for auto_edit/shorts.py."""
import json
from pathlib import Path

import pytest

from auto_edit.shorts import (
    DEFAULT_MAX_DURATION,
    ShortsError,
    format_clips_table,
    load_clips_plan,
    long_source_video,
    parse_pick,
    require_finished_long,
    seed_short_workspace,
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


LONG_PIPELINE = {
    "video_path": "/videos/DJI_0128.MP4",
    "video_name": "DJI_0128",
    "type": "long",
    "context": "resolvi o problema do bmcu",
    "language": "pt",
    "whisper_model": "small",
    "current_stage": "done",
    "stages": {},
}

POST_CUT = {
    "duration": 378.75,
    "segments": [],
    "words": [{"word": "Galera,", "start": 0.0, "end": 0.62}],
}


def make_long_ws(tmp_path: Path, pipeline=None, with_video=True) -> Path:
    ws = tmp_path / "workspace" / "DJI_0128"
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps(pipeline or LONG_PIPELINE))
    (ws / "post_cut_transcription.json").write_text(json.dumps(POST_CUT))
    if with_video:
        (ws / "edited_video.mp4").write_bytes(b"fake")
    return ws


class TestRequireFinishedLong:
    def test_returns_the_pipeline_when_the_long_is_done(self, tmp_path):
        ws = make_long_ws(tmp_path)
        assert require_finished_long(ws)["video_name"] == "DJI_0128"

    def test_missing_pipeline_json_points_at_the_long_command(self, tmp_path):
        ws = tmp_path / "workspace" / "nada"
        ws.mkdir(parents=True)
        with pytest.raises(ShortsError, match="auto-edit long"):
            require_finished_long(ws)

    def test_unfinished_pipeline_names_the_current_stage(self, tmp_path):
        ws = make_long_ws(tmp_path, {**LONG_PIPELINE, "current_stage": "execute"})
        with pytest.raises(ShortsError, match="execute"):
            require_finished_long(ws)

    def test_a_short_workspace_is_refused(self, tmp_path):
        ws = make_long_ws(tmp_path, {**LONG_PIPELINE, "type": "short"})
        with pytest.raises(ShortsError, match="long"):
            require_finished_long(ws)


class TestLongSourceVideo:
    def test_returns_the_edited_video(self, tmp_path):
        ws = make_long_ws(tmp_path)
        assert long_source_video(ws).name == "edited_video.mp4"

    def test_missing_edited_video_points_at_resume(self, tmp_path):
        ws = make_long_ws(tmp_path, with_video=False)
        with pytest.raises(ShortsError, match="--from execute"):
            long_source_video(ws)


class TestSeedShortWorkspace:
    def seed(self, tmp_path, index=1, start=10.0, end=40.0):
        long_ws = make_long_ws(tmp_path)
        clip = {"start": start, "end": end, "hook": "a impressora parava"}
        return long_ws, seed_short_workspace(long_ws, LONG_PIPELINE, clip, index)

    def test_creates_a_sibling_workspace_named_after_the_clip(self, tmp_path):
        long_ws, ws = self.seed(tmp_path, index=2)
        assert ws.name == "DJI_0128_short2"
        assert ws.parent == long_ws.parent

    def test_video_name_is_unique_per_clip(self, tmp_path):
        _, ws = self.seed(tmp_path, index=3)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["video_name"] == "DJI_0128_short3"

    def test_source_is_the_edited_long(self, tmp_path):
        long_ws, ws = self.seed(tmp_path)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["video_path"] == str((long_ws / "edited_video.mp4").resolve())

    def test_type_is_short_and_starts_at_execute(self, tmp_path):
        _, ws = self.seed(tmp_path)
        pipeline = json.loads((ws / "pipeline.json").read_text())
        assert pipeline["type"] == "short"
        assert pipeline["current_stage"] == "execute"

    def test_agent_stages_are_skipped(self, tmp_path):
        _, ws = self.seed(tmp_path)
        stages = json.loads((ws / "pipeline.json").read_text())["stages"]
        for stage in ("extract", "plan", "review", "overlay", "evaluate"):
            assert stages[stage]["status"] == "skip", stage
        for stage in ("execute", "caption", "metadata", "thumbnail"):
            assert stages[stage]["status"] == "pending", stage

    def test_transcription_is_the_long_post_cut(self, tmp_path):
        _, ws = self.seed(tmp_path)
        assert json.loads((ws / "transcription.json").read_text()) == POST_CUT

    def test_reviewed_plan_keeps_only_the_clip_window(self, tmp_path):
        _, ws = self.seed(tmp_path, start=10.0, end=40.0)
        plan = json.loads((ws / "reviewed_plan.json").read_text())
        assert plan["approved"] is True
        assert plan["cuts"] == []
        assert len(plan["kept_segments"]) == 1
        assert plan["kept_segments"][0]["start"] == 10.0
        assert plan["kept_segments"][0]["end"] == 40.0

    def test_clip_window_is_snapped_to_word_boundaries(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        (long_ws / "post_cut_transcription.json").write_text(json.dumps({
            "duration": 378.75,
            "segments": [],
            "words": [
                {"word": "a", "start": 10.5, "end": 10.9},
                {"word": "b", "start": 11.0, "end": 39.0},
            ],
        }))
        ws = seed_short_workspace(
            long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 1
        )
        kept = json.loads((ws / "reviewed_plan.json").read_text())["kept_segments"][0]
        assert (kept["start"], kept["end"]) == (10.5, 39.0)

    def test_context_carries_the_long_context_and_the_hook(self, tmp_path):
        _, ws = self.seed(tmp_path)
        context = json.loads((ws / "pipeline.json").read_text())["context"]
        assert "bmcu" in context
        assert "a impressora parava" in context

    def test_reseeding_replaces_the_previous_plan(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        seed_short_workspace(long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 1)
        ws = seed_short_workspace(long_ws, LONG_PIPELINE, {"start": 50.0, "end": 80.0, "hook": "h"}, 1)
        kept = json.loads((ws / "reviewed_plan.json").read_text())["kept_segments"][0]
        assert kept["start"] == 50.0


class TestLoadClipsPlan:
    def test_reads_and_validates(self, tmp_path):
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "source_duration": 378.75,
            "clips": [
                {"start": 10.0, "end": 40.0, "hook": "h", "reason": "r", "score": 8},
                {"start": 400.0, "end": 430.0, "hook": "x", "reason": "r", "score": 5},
            ],
        }))
        valid, rejected = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert len(valid) == 1
        assert len(rejected) == 1

    def test_missing_plan_points_at_running_without_pick(self, tmp_path):
        ws = make_long_ws(tmp_path)
        with pytest.raises(ShortsError, match="--pick"):
            load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)

    def test_falls_back_to_the_transcription_duration(self, tmp_path):
        # O agente pode omitir source_duration; o post-cut tem a verdade.
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "clips": [{"start": 10.0, "end": 40.0, "hook": "h"}]
        }))
        valid, _ = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert len(valid) == 1


class TestFormatClipsTable:
    def test_numbers_the_clips_from_one(self):
        table = format_clips_table([
            {"start": 10.0, "end": 40.0, "hook": "gancho um", "reason": "r", "score": 8},
            {"start": 50.0, "end": 90.0, "hook": "gancho dois", "reason": "r", "score": 6},
        ])
        assert "1" in table and "2" in table
        assert "gancho um" in table

    def test_shows_the_duration(self):
        table = format_clips_table([
            {"start": 10.0, "end": 40.0, "hook": "h", "reason": "r", "score": 8}
        ])
        assert "30" in table

    def test_empty_list_says_so(self):
        assert "nenhum" in format_clips_table([]).lower()
