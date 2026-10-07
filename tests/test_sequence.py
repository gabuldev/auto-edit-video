"""Non-chronological edits: the plan's `sequence` (cold open / reordered
blocks), how the executor applies it, and the post-cut transcript of a
reordered timeline (a teaser plays the same words twice)."""
from __future__ import annotations

import json

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
