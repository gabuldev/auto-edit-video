"""Non-chronological edits: the plan's `sequence` (cold open / reordered
blocks), how the executor applies it, and the post-cut transcript of a
reordered timeline (a teaser plays the same words twice)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_edit import postcut, sequence

# 0-10 kept, 10-20 cut, 20-40 kept, 40-50 cut, 50-60 kept
KEPT = [(0.0, 10.0), (20.0, 40.0), (50.0, 60.0)]


class TestApply:
    def test_no_sequence_is_chronological(self):
        assert sequence.apply(KEPT, None) == (KEPT, [])
        assert sequence.apply(KEPT, []) == (KEPT, [])

    def test_reorders_blocks(self):
        seq = [{"start": 50, "end": 60}, {"start": 0, "end": 45}]
        out, notes = sequence.apply(KEPT, seq)
        assert out == [(50.0, 60.0), (0.0, 10.0), (20.0, 40.0)]
        assert notes == []

    def test_window_never_brings_back_a_cut(self):
        """A block spanning 0-45 plays only what was kept inside it."""
        out, _ = sequence.apply(KEPT, [{"start": 0, "end": 60}])
        assert out == KEPT

    def test_teaser_plays_twice(self):
        seq = [
            {"start": 25, "end": 30, "role": "teaser"},
            {"start": 0, "end": 60},
        ]
        out, notes = sequence.apply(KEPT, seq)
        assert out == [(25.0, 30.0), (0.0, 10.0), (20.0, 40.0), (50.0, 60.0)]
        assert notes == []

    def test_blocks_missing_kept_content_fall_back(self):
        out, notes = sequence.apply(KEPT, [{"start": 50, "end": 60}, {"start": 0, "end": 30}])
        assert out == KEPT
        assert "cobrem" in notes[0]

    def test_overlapping_blocks_fall_back(self):
        out, notes = sequence.apply(KEPT, [{"start": 20, "end": 60}, {"start": 0, "end": 30}])
        assert out == KEPT
        assert "sobrepõem" in notes[0]

    @pytest.mark.parametrize("bad", [
        "0-60",
        [{"start": "x", "end": 60}],
        [{"start": 30, "end": 10}],
        [{"start": 0, "end": 60, "role": "outro"}],
    ])
    def test_malformed_falls_back(self, bad):
        out, notes = sequence.apply(KEPT, bad)
        assert out == KEPT and notes

    def test_teaser_length_limits(self):
        too_short = [{"start": 25, "end": 26, "role": "teaser"}, {"start": 0, "end": 60}]
        out, notes = sequence.apply(KEPT, too_short)
        assert out == KEPT and "ignorado" in notes[0]

        too_long = [{"start": 20, "end": 40, "role": "teaser"}, {"start": 0, "end": 60}]
        out, notes = sequence.apply(KEPT, too_long)
        assert out == KEPT and "ignorado" in notes[0]

    def test_teasers_total_cap(self):
        seq = [
            {"start": 20, "end": 32, "role": "teaser"},
            {"start": 0, "end": 10, "role": "teaser"},
            {"start": 0, "end": 60},
        ]
        out, notes = sequence.apply(KEPT, seq)
        # second teaser dropped: (0, 10) plays once, as part of the block
        assert out == [(20.0, 32.0), (0.0, 10.0), (20.0, 40.0), (50.0, 60.0)]
        assert any("20" in n for n in notes)

    def test_teaser_inside_a_cut_is_ignored(self):
        out, notes = sequence.apply(KEPT, [{"start": 12, "end": 18, "role": "teaser"}, {"start": 0, "end": 60}])
        assert out == KEPT and "ignorado" in notes[0]

    def test_adjacent_pieces_are_merged(self):
        """Teaser 30-40 followed by a block that starts at 40 in the source."""
        kept = [(0.0, 60.0)]
        seq = [{"start": 30, "end": 40, "role": "teaser"}, {"start": 40, "end": 60}, {"start": 0, "end": 40}]
        out, _ = sequence.apply(kept, seq)
        assert out == [(30.0, 60.0), (0.0, 40.0)]


TRANSCRIPTION = {
    "duration": 60.0,
    "words": [
        {"word": "abertura", "start": 1.0, "end": 2.0},
        {"word": "gancho", "start": 26.0, "end": 27.0},
        {"word": "fim", "start": 55.0, "end": 56.0},
    ],
    "segments": [
        {"start": 0.5, "end": 2.5, "text": "abertura"},
        {"start": 25.5, "end": 27.5, "text": "gancho"},
        {"start": 54.0, "end": 57.0, "text": "fim"},
    ],
}


class TestPostcutReordered:
    def test_teaser_words_appear_twice_at_their_playback_times(self):
        playback, _ = sequence.apply(KEPT, [{"start": 25, "end": 30, "role": "teaser"}, {"start": 0, "end": 60}])
        result = postcut.remap(TRANSCRIPTION, playback)
        assert [(w["word"], w["start"]) for w in result["words"]] == [
            ("gancho", 1.0),     # teaser: 25-30 plays at 0-5
            ("abertura", 6.0),   # body starts at 5
            ("gancho", 21.0),    # 5 + 10 (0-10) + 6 (20→26)
            ("fim", 40.0),       # 5 + 10 + 20 + 5
        ]
        assert result["duration"] == 45.0
        assert [s["text"] for s in result["segments"]] == ["gancho", "abertura", "gancho", "fim"]

    def test_reordered_blocks(self):
        playback, _ = sequence.apply(KEPT, [{"start": 50, "end": 60}, {"start": 0, "end": 45}])
        result = postcut.remap(TRANSCRIPTION, playback)
        assert [(w["word"], w["start"]) for w in result["words"]] == [("fim", 5.0), ("abertura", 11.0), ("gancho", 26.0)]

    def test_teaser_cutting_a_sentence_is_partial(self):
        result = postcut.remap(TRANSCRIPTION, [(26.0, 30.0), (0.0, 10.0)])
        assert result["segments"][0]["partial"] is True


def test_executor_writes_the_playback_order(tmp_path, monkeypatch):
    import tools.executor as executor
    from auto_edit import snap

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"video_path": str(tmp_path / "v.mp4"), "type": "long"}))
    (ws / "reviewed_plan.json").write_text(json.dumps({
        "kept_segments": [{"start": 0, "end": 10}, {"start": 20, "end": 40}, {"start": 50, "end": 60}],
        "sequence": [{"start": 25, "end": 30, "role": "teaser"}, {"start": 0, "end": 60}],
    }))
    monkeypatch.setenv("AUTO_EDIT_END_PADDING", "0")
    monkeypatch.setattr(executor, "_get_duration", lambda v: 60.0)
    monkeypatch.setattr(snap, "load_energy_map", lambda w: ([], 0.0))
    monkeypatch.setattr(executor, "snap_start_to_audio_onset", lambda iv, v: iv)
    cut = {}
    monkeypatch.setattr(executor, "_run_ffmpeg_cuts", lambda v, iv, out, reframe=None: cut.setdefault("iv", iv))

    executor.execute(ws)

    expected = [(25.0, 30.0), (0.0, 10.0), (20.0, 40.0), (50.0, 60.0)]
    assert cut["iv"] == expected
    applied = json.loads((ws / "applied_intervals.json").read_text())["intervals"]
    assert [(i["start"], i["end"]) for i in applied] == expected


# ── cold open: agent answer → plan ────────────────────────────────────────────

def _cold_ws(tmp_path, answer=None, cold_open=True, sequence_in_plan=None):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "cold_open": cold_open, "stages": {}}))
    plan = {"kept_segments": [{"start": s, "end": e} for s, e in KEPT], "cuts": []}
    if sequence_in_plan:
        plan["sequence"] = sequence_in_plan
    (ws / "reviewed_plan.json").write_text(json.dumps(plan))
    if answer is not None:
        (ws / sequence.COLD_OPEN_FILE).write_text(json.dumps(answer))
    return ws


class TestColdOpen:
    def test_wants_only_when_asked_and_no_sequence(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_COLD_OPEN", raising=False)
        assert sequence.wants_cold_open(_cold_ws(tmp_path / "a"))
        assert not sequence.wants_cold_open(_cold_ws(tmp_path / "b", cold_open=False))
        assert not sequence.wants_cold_open(_cold_ws(tmp_path / "c", sequence_in_plan=[{"start": 0, "end": 60}]))
        monkeypatch.setenv("AUTO_EDIT_COLD_OPEN", "1")
        assert sequence.wants_cold_open(_cold_ws(tmp_path / "d", cold_open=False))

    def test_merge_writes_teaser_then_everything(self, tmp_path):
        ws = _cold_ws(tmp_path, {"teaser": {"start": 52, "end": 58, "reason": "o resultado"}})
        notes = sequence.merge_cold_open(ws)
        plan = json.loads((ws / "reviewed_plan.json").read_text())
        assert plan["sequence"][0] == {"start": 52.0, "end": 58.0, "role": "teaser"}
        assert plan["cold_open"]["reason"] == "o resultado"
        played, problems = sequence.apply(KEPT, plan["sequence"])
        assert problems == [] and played == [(52.0, 58.0)] + KEPT
        assert "52.0" in notes[0]

    @pytest.mark.parametrize("answer, expected", [
        ({"teaser": None, "reason": "já abre no gancho"}, "já abre no gancho"),
        ({"teaser": {"start": 2, "end": 8}}, "abertura"),          # only 2s of kept before it
        ({"teaser": {"start": 12, "end": 18}}, "ignorado"),        # inside the 10-20 cut
        ({"teaser": {"start": "x", "end": 8}}, "start/end"),
    ])
    def test_merge_skips_without_touching_the_plan(self, tmp_path, answer, expected):
        ws = _cold_ws(tmp_path, answer)
        before = (ws / "reviewed_plan.json").read_text()
        notes = sequence.merge_cold_open(ws)
        assert expected in " ".join(notes)
        assert (ws / "reviewed_plan.json").read_text() == before


def test_cold_open_prompt_lists_kept_lines_on_the_source_timeline(tmp_path):
    from auto_edit import runner

    ws = _cold_ws(tmp_path)
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c", "stages": {}}))
    (ws / "transcription.json").write_text(json.dumps({"duration": 60, "segments": [
        {"start": 1.0, "end": 3.0, "text": "abertura"},
        {"start": 12.0, "end": 15.0, "text": "cortado"},
        {"start": 25.0, "end": 28.0, "text": "gancho forte"},
    ]}))
    prompt = runner.build_prompt("coldopen", ws, Path("agents/cold_open.md"))
    assert "[1.0–3.0] abertura" in prompt
    assert "[25.0–28.0] gancho forte" in prompt
    assert "cortado" not in prompt


def test_set_cold_open_survives_reload(tmp_path):
    from auto_edit import pipeline as pl

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"stages": {}}))
    pl.set_cold_open(ws)
    assert pl.load(ws)["cold_open"] is True


# ── reordering blocks ─────────────────────────────────────────────────────────

class TestNormalizeBlocks:
    def test_gaps_and_overlaps_become_a_partition_in_the_agents_order(self):
        blocks = [{"start": 21, "end": 41}, {"start": 0, "end": 18}, {"start": 39, "end": 55}]
        out = sequence.normalize_blocks(blocks, KEPT)
        assert out == [{"start": 21.0, "end": 39.0}, {"start": 0.0, "end": 21.0}, {"start": 39.0, "end": 120.0}]
        played, notes = sequence.apply(KEPT, out)
        assert notes == []
        assert sorted(played) == sorted(KEPT) or sum(e - s for s, e in played) == sum(e - s for s, e in KEPT)

    def test_needs_two_valid_blocks(self):
        assert sequence.normalize_blocks([{"start": 0, "end": 60}], KEPT) == []
        assert sequence.normalize_blocks([{"start": "x", "end": 1}, {"start": 2, "end": 3}], KEPT) == []
        assert sequence.normalize_blocks(None, KEPT) == []


def _flags_ws(tmp_path, answer, cold_open=False, reorder=True):
    ws = _cold_ws(tmp_path, answer, cold_open=cold_open)
    p = json.loads((ws / "pipeline.json").read_text(encoding="utf-8"))
    p["reorder"] = reorder
    (ws / "pipeline.json").write_text(json.dumps(p), encoding="utf-8")
    return ws


class TestReorderMerge:
    def test_reorder_only(self, tmp_path):
        ws = _flags_ws(tmp_path, {"teaser": None, "blocks": [{"start": 45, "end": 60}, {"start": 0, "end": 45}],
                                  "order_reason": "resultado antes"})
        notes = sequence.merge_cold_open(ws)
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        played, problems = sequence.apply(KEPT, plan["sequence"])
        assert problems == [] and played == [(50.0, 60.0), (0.0, 10.0), (20.0, 40.0)]
        assert plan["reorder"]["reason"] == "resultado antes"
        assert "cold_open" not in plan
        assert any("reordenado" in n for n in notes)

    def test_teaser_and_reorder_together(self, tmp_path):
        ws = _flags_ws(tmp_path, {"teaser": {"start": 52, "end": 58, "reason": "r"},
                                  "blocks": [{"start": 45, "end": 60}, {"start": 0, "end": 45}]}, cold_open=True)
        sequence.merge_cold_open(ws)
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        played, _ = sequence.apply(KEPT, plan["sequence"])
        # the new order already opens on the teaser's block: no teaser, no repeat
        assert played == [(50.0, 60.0), (0.0, 10.0), (20.0, 40.0)]
        assert "cold_open" not in plan

    def test_teaser_kept_when_its_block_is_not_first(self, tmp_path):
        ws = _flags_ws(tmp_path, {"teaser": {"start": 25, "end": 30, "reason": "r"},
                                  "blocks": [{"start": 45, "end": 60}, {"start": 0, "end": 45}]}, cold_open=True)
        sequence.merge_cold_open(ws)
        plan = json.loads((ws / "reviewed_plan.json").read_text(encoding="utf-8"))
        played, _ = sequence.apply(KEPT, plan["sequence"])
        assert played == [(25.0, 30.0), (50.0, 60.0), (0.0, 10.0), (20.0, 40.0)]

    def test_same_order_writes_nothing(self, tmp_path):
        ws = _flags_ws(tmp_path, {"blocks": [{"start": 0, "end": 30}, {"start": 30, "end": 60}]})
        before = (ws / "reviewed_plan.json").read_text(encoding="utf-8")
        notes = sequence.merge_cold_open(ws)
        assert (ws / "reviewed_plan.json").read_text(encoding="utf-8") == before
        assert "mesma ordem" in notes[0]

    def test_blocks_ignored_when_reorder_not_asked(self, tmp_path):
        ws = _flags_ws(tmp_path, {"teaser": None, "blocks": [{"start": 45, "end": 60}, {"start": 0, "end": 45}]},
                       cold_open=True, reorder=False)
        before = (ws / "reviewed_plan.json").read_text(encoding="utf-8")
        sequence.merge_cold_open(ws)
        assert (ws / "reviewed_plan.json").read_text(encoding="utf-8") == before

    def test_wants_when_only_reorder(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_COLD_OPEN", raising=False)
        monkeypatch.delenv("AUTO_EDIT_REORDER", raising=False)
        assert sequence.wants_cold_open(_flags_ws(tmp_path, None))


def test_prompt_says_what_is_allowed(tmp_path):
    from auto_edit import runner

    ws = _flags_ws(tmp_path, None)
    (ws / "transcription.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    prompt = runner.build_prompt("coldopen", ws, Path("agents/cold_open.md"))
    assert "Reordering allowed: yes" in prompt
    assert "Cold open (teaser) wanted: no" in prompt
