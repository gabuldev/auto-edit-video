"""Tests for auto_edit/shorts.py."""
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_edit import cli as cli_mod
from auto_edit.cli import app
from auto_edit.shorts import (
    DEFAULT_MAX_DURATION,
    ShortsError,
    format_clips_table,
    load_clips_plan,
    long_source_video,
    overlapping_indices,
    overwrite_warning,
    parse_pick,
    require_finished_long,
    seed_short_workspace,
    snap_clip_to_words,
    sort_clips_by_score,
    validate_clips,
)

runner = CliRunner()


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
        assert "candidato 1 do plano" in rejected[0]

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


class TestSortClipsByScore:
    def test_orders_by_score_descending(self):
        ordered = sort_clips_by_score([clip(0, 30), {**clip(40, 70), "score": 9}])
        assert ordered[0]["score"] == 9

    def test_missing_or_null_score_goes_last(self):
        clips = [
            {"start": 0.0, "end": 30.0, "hook": "sem nota"},
            {"start": 40.0, "end": 70.0, "hook": "nula", "score": None},
            {"start": 80.0, "end": 110.0, "hook": "com nota", "score": 3},
        ]
        ordered = sort_clips_by_score(clips)
        assert ordered[0]["hook"] == "com nota"
        assert {c["hook"] for c in ordered[1:]} == {"sem nota", "nula"}

    def test_ties_keep_the_original_order(self):
        a = {**clip(0, 30, "a"), "score": 5}
        b = {**clip(40, 70, "b"), "score": 5}
        assert [c["hook"] for c in sort_clips_by_score([a, b])] == ["a", "b"]


class TestOverlap:
    def test_flags_both_sides_of_an_overlap(self):
        assert overlapping_indices([clip(0, 30), clip(20, 50), clip(60, 90)]) == {0, 1}

    def test_touching_windows_are_not_an_overlap(self):
        assert overlapping_indices([clip(0, 30), clip(30, 60)]) == set()

    def test_table_marks_the_overlapping_rows(self):
        table = format_clips_table([clip(0, 30), clip(20, 50)])
        assert table.count("sobrep") >= 2


class TestRejectionLabels:
    def test_rejection_names_the_position_in_the_plan_not_the_table_row(self):
        _valid, rejected = validate_clips(
            [clip(10.0, 40.0), clip(40.0, 10.0)], source_duration=378.0
        )
        assert "candidato 2 do plano" in rejected[0]


class TestFormatClipsTableScore:
    def test_null_score_renders_as_a_dash_instead_of_exploding(self):
        table = format_clips_table(
            [{"start": 10.0, "end": 40.0, "hook": "h", "score": None}]
        )
        assert "-" in table

    def test_missing_score_renders_as_a_dash(self):
        assert format_clips_table([{"start": 10.0, "end": 40.0, "hook": "h"}])


class TestLoadClipsPlanBounds:
    def test_the_post_cut_duration_wins_over_the_models_claim(self, tmp_path):
        # O modelo diz que o long tem 600s; o post-cut diz 378.75. Um clipe em
        # 400-430 está FORA do vídeo e tem de ser rejeitado.
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "source_duration": 600.0,
            "clips": [{"start": 400.0, "end": 430.0, "hook": "h", "score": 8}],
        }))
        valid, rejected = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert valid == []
        assert "378" in rejected[0]

    def test_a_smaller_claim_is_honoured(self, tmp_path):
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "source_duration": 100.0,
            "clips": [{"start": 110.0, "end": 140.0, "hook": "h", "score": 8}],
        }))
        valid, rejected = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert valid == []
        assert "100" in rejected[0]

    def test_the_returned_clips_are_already_sorted_by_score(self, tmp_path):
        ws = make_long_ws(tmp_path)
        (ws / "clips_plan.json").write_text(json.dumps({
            "clips": [
                {"start": 10.0, "end": 40.0, "hook": "fraco", "score": 3},
                {"start": 50.0, "end": 80.0, "hook": "forte", "score": 9},
            ],
        }))
        valid, _ = load_clips_plan(ws, max_duration=DEFAULT_MAX_DURATION)
        assert [c["hook"] for c in valid] == ["forte", "fraco"]


class TestOverwriteWarning:
    def test_warns_when_the_target_workspace_holds_a_different_window(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        seed_short_workspace(
            long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 1
        )
        warning = overwrite_warning(
            long_ws, LONG_PIPELINE, {"start": 100.0, "end": 130.0, "hook": "h"}, 1
        )
        assert warning and "DJI_0128_short1" in warning

    def test_no_warning_for_the_same_window(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        clip_body = {"start": 10.0, "end": 40.0, "hook": "h"}
        seed_short_workspace(long_ws, LONG_PIPELINE, clip_body, 1)
        assert overwrite_warning(long_ws, LONG_PIPELINE, clip_body, 1) is None

    def test_no_warning_when_the_workspace_does_not_exist(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        assert overwrite_warning(
            long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": "h"}, 7
        ) is None


class TestSeedContext:
    def test_a_hook_starting_with_an_em_dash_keeps_its_characters(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        hook = "— e aí a impressora parou —"
        ws = seed_short_workspace(
            long_ws, LONG_PIPELINE, {"start": 10.0, "end": 40.0, "hook": hook}, 1
        )
        context = json.loads((ws / "pipeline.json").read_text())["context"]
        assert context.endswith(hook)

    def test_no_long_context_still_yields_the_hook(self, tmp_path):
        long_ws = make_long_ws(tmp_path)
        ws = seed_short_workspace(
            long_ws, {**LONG_PIPELINE, "context": ""},
            {"start": 10.0, "end": 40.0, "hook": "o gancho"}, 1,
        )
        context = json.loads((ws / "pipeline.json").read_text())["context"]
        assert context == "trecho: o gancho"


# ── CLI (`auto-edit shorts`) ────────────────────────────────────────────────

PLAN = {
    "source_duration": 378.75,
    "notes": "",
    "clips": [
        {"start": 10.0, "end": 40.0, "hook": "gancho um", "reason": "r", "score": 8},
        {"start": 100.0, "end": 140.0, "hook": "gancho dois", "reason": "r", "score": 6},
    ],
}


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Workspace de long pronto + subprocess.run e ralph.sh neutralizados."""
    long_ws = make_long_ws(tmp_path)
    monkeypatch.setattr(cli_mod, "get_workspace", lambda video, **kw: long_ws)
    assert cli_mod.RALPH_SCRIPT.exists(), "ralph.sh do repo é usado como está"

    calls: list[list[str]] = []
    rc = {"code": 0}

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        # O clipper de verdade escreve o clips_plan.json; o dublê também, senão
        # o passo seguinte não teria o que ler.
        if _is_clipper(cmd) and rc["code"] == 0:
            _write_plan(long_ws)
        return subprocess.CompletedProcess(cmd, rc["code"])

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    return {"ws": long_ws, "calls": calls, "rc": rc}


def _is_clipper(cmd: list[str]) -> bool:
    return "--agent" in cmd


def _write_plan(long_ws: Path, plan=None) -> None:
    (long_ws / "clips_plan.json").write_text(json.dumps(plan or PLAN))


class TestShortsCommand:
    def test_pick_without_a_plan_errors_and_never_calls_the_clipper(self, cli_env):
        result = runner.invoke(app, ["shorts", "v.mp4", "--pick", "1"])
        assert result.exit_code == 1
        assert "clips_plan.json" in result.stdout
        assert cli_env["calls"] == []

    def test_all_without_a_plan_errors_too(self, cli_env):
        result = runner.invoke(app, ["shorts", "v.mp4", "--all"])
        assert result.exit_code == 1
        assert cli_env["calls"] == []

    def test_no_flags_with_a_plan_reprints_it_without_calling_the_clipper(self, cli_env):
        # Renumerar os candidatos embaixo de quem já leu a tabela faria o
        # `--pick 2` seguinte apontar pra outro clipe. `--replan` é o caminho
        # explícito pra regenerar.
        _write_plan(cli_env["ws"])
        result = runner.invoke(app, ["shorts", "v.mp4"])
        assert result.exit_code == 0
        assert "gancho um" in result.stdout
        assert cli_env["calls"] == []
        assert not (cli_env["ws"].parent / "DJI_0128_short1").exists()

    def test_no_flags_says_the_table_came_from_the_plan_on_disk(self, cli_env):
        _write_plan(cli_env["ws"])
        result = runner.invoke(app, ["shorts", "v.mp4"])
        assert "--replan" in result.stdout

    def test_no_flags_without_a_plan_runs_the_clipper_once_and_prints_the_table(self, cli_env):
        assert not (cli_env["ws"] / "clips_plan.json").exists()
        result = runner.invoke(app, ["shorts", "v.mp4"])
        assert result.exit_code == 0
        assert len(cli_env["calls"]) == 1
        assert _is_clipper(cli_env["calls"][0])
        assert (cli_env["ws"] / "clips_plan.json").exists()
        assert "gancho um" in result.stdout
        assert not (cli_env["ws"].parent / "DJI_0128_short1").exists()

    def test_pick_with_an_existing_plan_does_not_rerun_the_clipper(self, cli_env):
        _write_plan(cli_env["ws"])
        result = runner.invoke(app, ["shorts", "v.mp4", "--pick", "1"])
        assert result.exit_code == 0
        assert not any(_is_clipper(c) for c in cli_env["calls"])
        assert len([c for c in cli_env["calls"] if not _is_clipper(c)]) == 1
        assert (cli_env["ws"].parent / "DJI_0128_short1").exists()
        assert not (cli_env["ws"].parent / "DJI_0128_short2").exists()

    def test_all_seeds_every_candidate_with_distinct_names(self, cli_env):
        _write_plan(cli_env["ws"])
        result = runner.invoke(app, ["shorts", "v.mp4", "--all"])
        assert result.exit_code == 0
        names = set()
        for i in (1, 2):
            ws = cli_env["ws"].parent / f"DJI_0128_short{i}"
            assert ws.exists()
            names.add(json.loads((ws / "pipeline.json").read_text())["video_name"])
        assert names == {"DJI_0128_short1", "DJI_0128_short2"}

    def test_replan_reruns_the_clipper_even_with_a_plan_on_disk(self, cli_env):
        _write_plan(cli_env["ws"])
        result = runner.invoke(app, ["shorts", "v.mp4", "--replan"])
        assert result.exit_code == 0
        assert [c for c in cli_env["calls"] if _is_clipper(c)]

    def test_a_failing_short_aborts_the_remaining_picks(self, cli_env):
        _write_plan(cli_env["ws"])
        cli_env["rc"]["code"] = 3
        result = runner.invoke(app, ["shorts", "v.mp4", "--all"])
        assert result.exit_code == 3
        assert len([c for c in cli_env["calls"] if not _is_clipper(c)]) == 1

    def test_zero_candidates_prints_the_models_notes(self, cli_env):
        _write_plan(cli_env["ws"], {"source_duration": 378.75, "notes": "nada se sustenta sozinho", "clips": []})
        result = runner.invoke(app, ["shorts", "v.mp4"])
        assert result.exit_code == 0
        assert "nada se sustenta sozinho" in result.stdout

    def test_the_clipper_receives_the_max_dur_cap(self, cli_env, monkeypatch):
        seen: dict = {}

        def fake_run(cmd, *args, **kwargs):
            seen.update(kwargs.get("env") or {})
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        _write_plan(cli_env["ws"])
        runner.invoke(app, ["shorts", "v.mp4", "--replan", "--max-dur", "45"])
        assert seen.get("AUTO_EDIT_CLIP_MAX_DUR") == "45"
