"""Evaluate judges the planned cut before anything renders, so a rejection
only replays plan → review → evaluate. And the cold open's teaser always
plays whole sentences, and steps aside when the evaluator blamed it."""
import json
from pathlib import Path

from auto_edit import pipeline as pl
from auto_edit import postcut, sequence


def test_evaluate_comes_before_any_render():
    order = pl.STAGES
    assert order.index("evaluate") < order.index("execute") < order.index("overlay")
    assert order.index("review") < order.index("evaluate")


def _ws(tmp_path: Path, plan: dict, segments=None, words=None, **pipe):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "iteration": 1, "max_iterations": 3,
                                                  "stages": {}, **pipe}), encoding="utf-8")
    (ws / "reviewed_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (ws / "transcription.json").write_text(json.dumps({
        "duration": 60.0, "segments": segments or [], "words": words or [],
    }), encoding="utf-8")
    return ws


def test_approved_plan_moves_on_to_execute(tmp_path):
    ws = tmp_path / "w"
    ws.mkdir()
    pl.init(ws, video_path=tmp_path / "v.mp4", video_type="long", context="c")
    pl.set_stage(ws, "evaluate")
    pl.set_stage_status(ws, "evaluate", "complete")
    assert pl.load(ws)["current_stage"] == "execute"


class TestPlannedTranscript:
    def test_matches_the_cut_the_executor_will_make(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_END_PADDING", "0")
        words = [{"word": "um", "start": 1.0, "end": 1.5}, {"word": "cortado", "start": 12.0, "end": 13.0},
                 {"word": "dois", "start": 30.0, "end": 30.5}]
        ws = _ws(tmp_path, {"kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 40}]}, words=words)
        result = postcut.planned(ws)
        assert [(w["word"], w["start"]) for w in result["words"]] == [("um", 1.0), ("dois", 20.0)]
        assert "before render" in result["derived_from"]
        assert json.loads((ws / "post_cut_transcription.json").read_text(encoding="utf-8"))["duration"] == 30.0

    def test_follows_the_plans_sequence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_END_PADDING", "0")
        words = [{"word": "um", "start": 1.0, "end": 1.5}, {"word": "dois", "start": 30.0, "end": 30.5}]
        ws = _ws(tmp_path, {"kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 40}],
                            "sequence": [{"start": 20, "end": 60}, {"start": 0, "end": 20}]}, words=words)
        assert [w["word"] for w in postcut.planned(ws)["words"]] == ["dois", "um"]

    def test_nothing_to_judge(self, tmp_path):
        assert postcut.planned(tmp_path) is None


SEGMENTS = [
    {"start": 20.0, "end": 24.0, "text": "A gente libera esses dados pro AI,"},
    {"start": 24.0, "end": 27.0, "text": "ela interpreta tudo."},
    {"start": 27.0, "end": 45.0, "text": "uma frase muito longa"},
]


class TestTeaserSentences:
    def test_widened_to_whole_lines(self):
        assert sequence.snap_to_sentences(21.5, 25.0, SEGMENTS) == (20.0, 27.0)

    def test_drops_trailing_lines_past_the_limit(self):
        assert sequence.snap_to_sentences(21.0, 30.0, SEGMENTS) == (20.0, 27.0)

    def test_none_when_a_single_line_is_too_long(self):
        assert sequence.snap_to_sentences(30.0, 35.0, SEGMENTS) is None

    def test_merge_uses_the_whole_sentence(self, tmp_path):
        ws = _ws(tmp_path, {"kept_segments": [{"start": 0, "end": 60}]}, segments=SEGMENTS, cold_open=True)
        (ws / "cold_open.json").write_text(json.dumps({"teaser": {"start": 21.5, "end": 25.0, "reason": "r"}}), encoding="utf-8")
        sequence.merge_cold_open(ws)
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        assert plan["sequence"][0] == {"start": 20.0, "end": 27.0, "role": "teaser"}

    def test_teaser_across_a_cut_is_refused(self, tmp_path):
        """0133: the plan cut through the sentence, the teaser played a fragment."""
        ws = _ws(tmp_path, {"kept_segments": [{"start": 0, "end": 22}, {"start": 25, "end": 60}]},
                 segments=SEGMENTS, cold_open=True)
        (ws / "cold_open.json").write_text(json.dumps({"teaser": {"start": 20.0, "end": 27.0}}), encoding="utf-8")
        notes = sequence.merge_cold_open(ws)
        assert "sequence" not in json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        assert any("atravessa um corte" in n for n in notes)


class TestEvaluatorBlame:
    def test_skips_the_teaser_after_a_complaint(self, tmp_path):
        ws = _ws(tmp_path, {"kept_segments": [{"start": 0, "end": 60}]}, segments=SEGMENTS, cold_open=True,
                 iteration=2, evaluator_feedback="Remove the opening teaser at 0:00-0:04.5 on the final timeline")
        (ws / "cold_open.json").write_text(json.dumps({"teaser": {"start": 20.0, "end": 27.0}}), encoding="utf-8")
        notes = sequence.merge_cold_open(ws)
        assert "sequence" not in json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        assert "pulado nesta volta" in notes[0]

    def test_unrelated_feedback_keeps_it(self, tmp_path):
        ws = _ws(tmp_path, {}, iteration=2, evaluator_feedback="O final corta no meio da frase.")
        assert sequence.blamed_by_evaluator(ws) is False
        ws2 = _ws(tmp_path / "b", {}, iteration=1, evaluator_feedback="teaser ruim")
        assert sequence.blamed_by_evaluator(ws2) is False  # first iteration: no previous teaser
