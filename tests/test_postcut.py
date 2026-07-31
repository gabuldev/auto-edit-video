"""The evaluate stage gets a transcript of the edited video, not the raw one."""
from __future__ import annotations

import json
from pathlib import Path

from auto_edit import postcut

# 0-2s kept, 2-5s cut, 5-8s kept  ->  final timeline is 5s long
INTERVALS = [(0.0, 2.0), (5.0, 8.0)]
TRANSCRIPTION = {
    "duration": 8.0,
    "words": [
        {"word": "olá", "start": 0.1, "end": 0.6},
        {"word": "mundo", "start": 1.0, "end": 1.8},
        {"word": "cortado", "start": 3.0, "end": 3.8},  # inside the cut
        {"word": "tchau", "start": 5.2, "end": 5.9},
        {"word": "gente", "start": 7.0, "end": 7.6},
    ],
    "segments": [
        {"start": 0.0, "end": 1.8, "text": "olá mundo"},
        {"start": 3.0, "end": 3.8, "text": "cortado"},
        {"start": 5.0, "end": 7.6, "text": "tchau gente"},
    ],
}


def test_kept_words_shift_onto_the_final_timeline():
    result = postcut.remap(TRANSCRIPTION, INTERVALS)

    assert [w["word"] for w in result["words"]] == ["olá", "mundo", "tchau", "gente"]
    # 5.2s in the source is 2.2s in the edit (3s of cut removed before it)
    assert result["words"][2]["start"] == 2.2
    assert result["duration"] == 5.0


def test_words_inside_a_cut_disappear():
    result = postcut.remap(TRANSCRIPTION, INTERVALS)

    assert all(w["word"] != "cortado" for w in result["words"])


def test_word_straddling_a_boundary_is_dropped():
    """Half a word is not a word -- it must not appear in the transcript."""
    transcription = {
        "duration": 8.0,
        "words": [{"word": "meio", "start": 1.8, "end": 2.4}],
        "segments": [],
    }
    result = postcut.remap(transcription, INTERVALS)

    assert result["words"] == []


def test_segment_cut_through_is_flagged_partial():
    transcription = {
        "duration": 8.0,
        "words": [],
        "segments": [{"start": 1.0, "end": 6.0, "text": "frase atravessada pelo corte"}],
    }
    result = postcut.remap(transcription, INTERVALS)

    assert result["segments"][0]["partial"] is True


def test_intact_segment_is_not_flagged():
    result = postcut.remap(TRANSCRIPTION, INTERVALS)
    intact = [s for s in result["segments"] if s["text"] == "olá mundo"]

    assert intact and "partial" not in intact[0]


def test_segment_fully_inside_a_cut_disappears():
    result = postcut.remap(TRANSCRIPTION, INTERVALS)

    assert all(s["text"] != "cortado" for s in result["segments"])


def _workspace(tmp_path: Path, applied=None, plan=None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "transcription.json").write_text(json.dumps(TRANSCRIPTION), encoding="utf-8")
    if applied is not None:
        (ws / "applied_intervals.json").write_text(json.dumps(applied), encoding="utf-8")
    if plan is not None:
        (ws / "reviewed_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return ws


def test_prefers_intervals_actually_used_by_ffmpeg(tmp_path):
    ws = _workspace(
        tmp_path,
        applied={"intervals": [{"start": 0.0, "end": 2.0}, {"start": 5.0, "end": 8.0}]},
        plan={"kept_segments": [{"start": 0.0, "end": 8.0}]},  # must be ignored
    )
    assert postcut.main(ws) == 0

    result = json.loads((ws / "post_cut_transcription.json").read_text())
    assert result["duration"] == 5.0


def test_falls_back_to_the_plan_with_executor_padding(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_END_PADDING", "0.2")
    ws = _workspace(tmp_path, plan={"kept_segments": [{"start": 0.0, "end": 1.8}]})

    intervals = postcut.load_intervals(ws, 8.0)

    assert intervals == [(0.0, 2.0)]  # 1.8 + 0.2 padding, as the executor does


def test_main_reports_what_the_edit_removed(tmp_path, capsys):
    ws = _workspace(tmp_path, applied={"intervals": [{"start": 0.0, "end": 2.0}]})
    assert postcut.main(ws) == 0

    out = capsys.readouterr().out
    assert "3 removed by the edit" in out


def test_main_without_intervals_is_a_noop(tmp_path, capsys):
    ws = _workspace(tmp_path)
    assert postcut.main(ws) == 0

    assert not (ws / "post_cut_transcription.json").exists()
    assert "No cut intervals" in capsys.readouterr().out


def test_main_without_transcription_is_a_noop(tmp_path, capsys):
    ws = tmp_path / "empty"
    ws.mkdir()
    assert postcut.main(ws) == 0
    assert "skipping" in capsys.readouterr().out
