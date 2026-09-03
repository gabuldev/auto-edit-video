"""Tests for the benchmark metrics — the numbers that decide the comparison.

A wrong metric would hand a verdict to the wrong planner, so the arithmetic is
pinned here against a hand-built recording: speech in 0–20s and 30–60s, silence
in between, words every 0.5s lasting 0.4s.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks import metrics


def _recording(tmp_path: Path) -> Path:
    words = []
    for span in ((0.0, 20.0), (30.0, 60.0)):
        t = span[0]
        while t < span[1]:
            words.append({"word": "pa", "start": round(t, 2), "end": round(t + 0.4, 2)})
            t += 0.5
    # 0.5s per bucket; the quiet stretch sits far below the speech level.
    energy = [(-45.0 if 20 <= i * 0.5 < 30 else -18.0) for i in range(120)]
    path = tmp_path / "transcription.json"
    path.write_text(
        json.dumps(
            {
                "duration": 60.0,
                "resolution_seconds": 0.5,
                "energy_db": energy,
                "words": words,
                "segments": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _plan(tmp_path: Path, name: str, cuts: list[dict], kept: list[dict], blocks=None) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps({"cuts": cuts, "kept_segments": kept, "dropped_blocks": blocks or []}),
        encoding="utf-8",
    )
    return path


class TestIntervals:
    def test_skips_malformed_and_sorts(self, tmp_path):
        plan = {"kept_segments": [{"start": 5, "end": 6}, {"start": 1}, {"start": 3, "end": 2}]}
        assert metrics.intervals(plan) == [(5.0, 6.0)]

    def test_overlap_of_disjoint_sets_is_zero(self):
        assert metrics.overlap([(0.0, 1.0)], [(2.0, 3.0)]) == 0.0

    def test_overlap_counts_only_shared_time(self):
        assert metrics.overlap([(0.0, 10.0)], [(5.0, 20.0)]) == 5.0


class TestWordsClipped:
    def test_boundary_in_silence_clips_nothing(self, tmp_path):
        words = json.loads(_recording(tmp_path).read_text())["words"]
        assert metrics.words_clipped(words, [(20.0, 30.0)]) == 0

    def test_boundary_inside_a_word_is_counted(self, tmp_path):
        words = json.loads(_recording(tmp_path).read_text())["words"]
        # 10.2 falls inside the word spanning 10.0–10.4.
        assert metrics.words_clipped(words, [(10.2, 30.0)]) == 1

    def test_both_boundaries_inside_words_count_once_each(self, tmp_path):
        words = json.loads(_recording(tmp_path).read_text())["words"]
        assert metrics.words_clipped(words, [(10.2, 30.0), (45.15, 50.0)]) == 2

    def test_boundary_exactly_on_a_word_edge_is_clean(self, tmp_path):
        words = json.loads(_recording(tmp_path).read_text())["words"]
        assert metrics.words_clipped(words, [(10.4, 30.0)]) == 0


class TestCompare:
    def test_reports_both_arms_and_agreement(self, tmp_path):
        transcription = _recording(tmp_path)
        clean = _plan(
            tmp_path, "clean",
            [{"start": 20.0, "end": 30.0, "type": "silence"}],
            [{"start": 0.0, "end": 20.0}, {"start": 30.0, "end": 60.0}],
        )
        eager = _plan(
            tmp_path, "eager",
            [{"start": 10.2, "end": 30.0, "type": "block"}, {"start": 45.15, "end": 50.0}],
            [{"start": 0.0, "end": 10.2}, {"start": 30.0, "end": 45.15}, {"start": 50.0, "end": 60.0}],
            blocks=[{"start": 10.2, "end": 30.0}],
        )
        report = metrics.compare(transcription, {"nosso": clean, "gemini": eager})

        ours, theirs = report["arms"]["nosso"], report["arms"]["gemini"]
        assert ours["final_duration"] == 50.0 and ours["removed_pct"] == 16.7
        assert ours["words_clipped"] == 0 and theirs["words_clipped"] == 2
        assert theirs["dropped_blocks"] == 1
        # The eager plan keeps a strict subset, so everything it kept is shared.
        assert report["agreement"]["only_in_gemini"] == 0.0
        assert 0.0 < report["agreement"]["iou"] < 1.0

    def test_silence_left_is_measured_against_this_recording(self, tmp_path):
        transcription = _recording(tmp_path)
        keeps_silence = _plan(tmp_path, "lazy", [], [{"start": 0.0, "end": 60.0}])
        report = metrics.compare(transcription, {"lazy": keeps_silence})
        # The whole 10s quiet stretch survives, and the threshold is adaptive.
        assert report["arms"]["lazy"]["silence_left"] >= 9.5
        assert -45.0 < report["arms"]["lazy"]["silence_threshold_db"] < -18.0

    def test_render_makes_a_table(self, tmp_path):
        transcription = _recording(tmp_path)
        plan = _plan(tmp_path, "p", [], [{"start": 0.0, "end": 60.0}])
        text = metrics.render(metrics.compare(transcription, {"nosso": plan}))
        assert "| duração final | 60.0s |" in text
