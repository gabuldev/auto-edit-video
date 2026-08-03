"""Cut boundaries get snapped out of spoken words before execution."""
from __future__ import annotations

import json
from pathlib import Path

from auto_edit import snap

# "olá" 0.0-0.5 | "mundo" 1.0-1.6 | gap | "tchau" 4.0-4.6
WORDS = [
    {"word": "olá", "start": 0.0, "end": 0.5},
    {"word": "mundo", "start": 1.0, "end": 1.6},
    {"word": "tchau", "start": 4.0, "end": 4.6},
]
DURATION = 6.0


def test_boundary_inside_word_moves_out():
    cuts, notes = snap.snap_cuts(
        [{"start": 1.3, "end": 3.0, "type": "silence"}], WORDS, DURATION
    )

    # 1.3 sits inside "mundo" (1.0-1.6) -> cut starts after it
    assert cuts == [{"start": 1.6, "end": 3.0, "type": "silence"}]
    assert "mundo" in notes[0]


def test_both_boundaries_snap():
    cuts, _ = snap.snap_cuts([{"start": 0.2, "end": 4.3}], WORDS, DURATION)

    assert cuts[0]["start"] == 0.5  # end of "olá"
    assert cuts[0]["end"] == 4.0  # start of "tchau"


def test_boundaries_already_in_gaps_untouched():
    cuts, notes = snap.snap_cuts([{"start": 1.8, "end": 3.5}], WORDS, DURATION)

    assert cuts == [{"start": 1.8, "end": 3.5}]
    assert notes == []


def test_cut_fully_inside_one_word_is_dropped():
    cuts, notes = snap.snap_cuts([{"start": 1.1, "end": 1.5}], WORDS, DURATION)

    assert cuts == []
    assert "nothing left" in notes[0]


def test_malformed_cut_is_dropped():
    cuts, notes = snap.snap_cuts([{"start": "x", "end": 3.0}], WORDS, DURATION)

    assert cuts == []
    assert "malformed" in notes[0]


def test_overlapping_cuts_merge():
    cuts, _ = snap.snap_cuts(
        [{"start": 1.8, "end": 3.0, "reason": "a"}, {"start": 2.5, "end": 3.8, "reason": "b"}],
        WORDS,
        DURATION,
    )

    assert len(cuts) == 1
    assert (cuts[0]["start"], cuts[0]["end"]) == (1.8, 3.8)
    assert cuts[0]["reason"] == "a + b"


def test_rebuild_kept_is_the_complement():
    kept = snap.rebuild_kept([{"start": 1.6, "end": 4.0}], DURATION)

    assert kept == [{"start": 0.0, "end": 1.6}, {"start": 4.0, "end": 6.0}]


def test_rebuild_kept_carries_summaries_by_overlap():
    kept = snap.rebuild_kept(
        [{"start": 1.6, "end": 4.0}],
        DURATION,
        previous=[
            {"start": 0.0, "end": 1.5, "summary": "abertura"},
            {"start": 4.1, "end": 6.0, "summary": "fecho"},
        ],
    )

    assert kept[0]["summary"] == "abertura"
    assert kept[1]["summary"] == "fecho"


def test_snap_plan_keeps_curation_fields():
    plan = {
        "cuts": [{"start": 1.3, "end": 3.0}],
        "kept_segments": [{"start": 0.0, "end": 1.3, "summary": "intro"}],
        "target_rationale": "denso",
        "dropped_blocks": [{"start": 1.3, "end": 3.0, "topic": "x"}],
    }
    snapped, _ = snap.snap_plan(plan, WORDS, DURATION)

    assert snapped["target_rationale"] == "denso"
    assert snapped["dropped_blocks"] == plan["dropped_blocks"]
    assert snapped["cuts"][0]["start"] == 1.6
    assert snapped["kept_segments"][0] == {"start": 0.0, "end": 1.6, "summary": "intro"}


def test_no_cut_clips_a_word_after_snapping():
    cuts, _ = snap.snap_cuts(
        [{"start": 0.3, "end": 1.2}, {"start": 1.4, "end": 4.2}], WORDS, DURATION
    )

    for cut in cuts:
        for w in WORDS:
            assert not (w["start"] < cut["start"] < w["end"])
            assert not (w["start"] < cut["end"] < w["end"])


def _workspace(tmp_path: Path, plan: dict, words=WORDS, duration=DURATION) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "reviewed_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (ws / "transcription.json").write_text(
        json.dumps({"duration": duration, "words": words, "segments": []}), encoding="utf-8"
    )
    return ws


def test_main_rewrites_plan_and_backs_up_original(tmp_path, capsys):
    ws = _workspace(
        tmp_path,
        {"cuts": [{"start": 1.3, "end": 3.0}], "kept_segments": [{"start": 3.0, "end": 6.0}]},
    )
    assert snap.main(ws) == 0

    written = json.loads((ws / "reviewed_plan.json").read_text())
    backup = json.loads((ws / "reviewed_plan.pre_snap.json").read_text())

    assert written["cuts"][0]["start"] == 1.6
    assert backup["cuts"][0]["start"] == 1.3
    assert "snapped cut" in capsys.readouterr().out


def test_main_leaves_clean_plan_alone(tmp_path, capsys):
    ws = _workspace(
        tmp_path,
        {
            "cuts": [{"start": 1.8, "end": 3.5}],
            "kept_segments": [{"start": 0.0, "end": 1.8}, {"start": 3.5, "end": 6.0}],
        },
    )
    assert snap.main(ws) == 0

    assert not (ws / "reviewed_plan.pre_snap.json").exists()
    assert "already sat in word gaps" in capsys.readouterr().out


def test_main_repairs_kept_segments_that_disagree_with_cuts(tmp_path, capsys):
    """The agent sometimes emits kept_segments that aren't the complement of cuts."""
    ws = _workspace(
        tmp_path,
        {"cuts": [{"start": 1.8, "end": 3.5}], "kept_segments": [{"start": 0.0, "end": 1.8}]},
    )
    assert snap.main(ws) == 0

    kept = json.loads((ws / "reviewed_plan.json").read_text())["kept_segments"]
    assert kept == [{"start": 0.0, "end": 1.8}, {"start": 3.5, "end": 6.0}]
    assert (ws / "reviewed_plan.pre_snap.json").exists()


def test_main_without_word_timestamps_is_a_noop(tmp_path, capsys):
    ws = _workspace(tmp_path, {"cuts": [{"start": 1.3, "end": 3.0}]}, words=[])
    assert snap.main(ws) == 0

    assert json.loads((ws / "reviewed_plan.json").read_text())["cuts"][0]["start"] == 1.3
    assert "leaving the plan untouched" in capsys.readouterr().out


def test_main_without_workspace_files_is_a_noop(tmp_path, capsys):
    ws = tmp_path / "empty"
    ws.mkdir()
    assert snap.main(ws) == 0
    assert "Nothing to do" in capsys.readouterr().out


# -- Splice repairs ------------------------------------------------------------

# "gostei muito, eu indico," | cut | "eu indico para vocês"
REPEAT_WORDS = [
    {"word": "muito,", "start": 0.0, "end": 0.5},
    {"word": "eu", "start": 0.6, "end": 0.9},
    {"word": "indico,", "start": 0.9, "end": 1.4},
    {"word": "eu", "start": 3.0, "end": 3.3},
    {"word": "indico", "start": 3.3, "end": 3.9},
    {"word": "para", "start": 3.9, "end": 4.2},
    {"word": "vocês", "start": 4.2, "end": 4.8},
]


def test_repeated_phrase_across_splice_is_removed():
    cuts, notes = snap.dedupe_splices([{"start": 1.4, "end": 3.0}], REPEAT_WORDS)

    # "eu indico" repeats after the cut -> extend through the second copy
    assert cuts[0]["end"] == 3.9
    assert "eu indico" in notes[0]


def test_single_repeated_word_is_not_enough():
    words = [
        {"word": "e", "start": 0.0, "end": 0.2},
        {"word": "e", "start": 1.0, "end": 1.2},
        {"word": "pronto", "start": 1.2, "end": 1.8},
    ]
    cuts, notes = snap.dedupe_splices([{"start": 0.2, "end": 1.0}], words)

    assert cuts[0]["end"] == 1.0
    assert notes == []


def test_dedupe_ignores_punctuation_and_case():
    words = [
        {"word": "muita", "start": 0.0, "end": 0.4},
        {"word": "gente", "start": 0.4, "end": 0.8},
        {"word": "atualizou.", "start": 0.8, "end": 1.4},
        {"word": "Muita", "start": 3.0, "end": 3.4},
        {"word": "gente", "start": 3.4, "end": 3.8},
        {"word": "atualizou", "start": 3.8, "end": 4.4},
        {"word": "hoje", "start": 4.4, "end": 4.9},
    ]
    cuts, _ = snap.dedupe_splices([{"start": 1.4, "end": 3.0}], words)

    assert cuts[0]["end"] == 4.4


# "não tem problema" | cut ate "Só" | "que, galera, eu atualizei"
ORPHAN_WORDS = [
    {"word": "problema.", "start": 0.0, "end": 0.6},
    {"word": "Só", "start": 2.0, "end": 2.3},
    {"word": "que,", "start": 2.4, "end": 2.8},
    {"word": "galera,", "start": 2.8, "end": 3.3},
]


def test_orphaned_opener_rewinds_the_boundary():
    cuts, notes = snap.unorphan_splices([{"start": 0.6, "end": 2.4}], ORPHAN_WORDS)

    assert cuts[0]["end"] == 2.0  # "Só" comes back
    assert "orphaned" in notes[0]


def test_capitalized_opener_is_not_an_orphan():
    """"Só que…" legitimately opens a sentence; only lowercase is wreckage."""
    cuts, notes = snap.unorphan_splices([{"start": 0.6, "end": 2.0}], ORPHAN_WORDS)

    assert cuts[0]["end"] == 2.0
    assert notes == []


def test_continuous_sentence_across_a_trim_is_not_an_orphan():
    """"…essa peça aqui, ⟹ que não deu certo" is one sentence, not wreckage."""
    words = [
        {"word": "aqui,", "start": 0.0, "end": 0.6},
        {"word": "hmm", "start": 1.0, "end": 1.4},
        {"word": "que", "start": 2.4, "end": 2.8},
        {"word": "não", "start": 2.8, "end": 3.1},
    ]
    cuts, notes = snap.unorphan_splices([{"start": 0.6, "end": 2.4}], words)

    assert cuts[0]["end"] == 2.4
    assert notes == []


def test_pure_silence_cut_before_a_fragment_is_left_alone():
    """The cut removed no words, so it did not create the dangling fragment."""
    words = [
        {"word": "problema.", "start": 0.0, "end": 0.6},
        {"word": "que,", "start": 2.4, "end": 2.8},
    ]
    cuts, notes = snap.unorphan_splices([{"start": 0.8, "end": 2.4}], words)

    assert cuts[0]["end"] == 2.4
    assert notes == []


def test_orphan_head_too_far_back_is_reported_not_fixed():
    words = [
        {"word": "problema.", "start": 0.0, "end": 0.6},
        {"word": "vamos", "start": 1.0, "end": 1.3},
        {"word": "ver", "start": 1.3, "end": 1.6},
        {"word": "só", "start": 5.0, "end": 5.3},
        {"word": "que,", "start": 9.0, "end": 9.4},
    ]
    cuts, notes = snap.unorphan_splices([{"start": 0.6, "end": 9.0}], words)

    assert cuts[0]["end"] == 9.0  # untouched -- rescuing it would revive 8s
    assert "too far back" in notes[0]


def test_snap_plan_applies_snap_then_grammar_repairs():
    plan = {"cuts": [{"start": 1.35, "end": 3.0}], "kept_segments": []}
    snapped, notes = snap.snap_plan(plan, REPEAT_WORDS, 6.0)

    # 1.35 sits inside "indico," (0.9-1.4) -> snaps to 1.4, then dedupe extends
    assert snapped["cuts"][0]["start"] == 1.4
    assert snapped["cuts"][0]["end"] == 3.9
    assert any("snapped" in n for n in notes)
    assert any("repeated" in n for n in notes)


# -- Segment-edge guard --------------------------------------------------------

# Whisper dropped "Só" from the word list, but the segment text still has it.
GAP_WORDS = [
    {"word": "problema.", "start": 4.1, "end": 4.5},
    {"word": "que,", "start": 5.7, "end": 6.0},
]
GAP_SEGMENTS = [
    {"start": 0.8, "end": 4.5, "text": "Até que eu imprimo, não tem problema."},
    {"start": 5.2, "end": 8.0, "text": "Só que, galera, eu atualizei aquela vez"},
]


def test_boundary_just_inside_a_segment_start_is_pulled_back():
    cuts, notes = snap.snap_cuts(
        [{"start": 4.6, "end": 5.3}], GAP_WORDS, 10.0, GAP_SEGMENTS
    )

    assert cuts[0]["end"] == 5.2  # the unlisted "Só" survives
    assert "missing a word" in notes[0]


def test_boundary_just_after_a_segment_end_is_pushed_out():
    cuts, _ = snap.snap_cuts([{"start": 4.4, "end": 5.0}], [], 10.0, GAP_SEGMENTS)

    assert cuts[0]["start"] == 4.5


def test_boundary_well_inside_a_segment_is_left_alone():
    """A long pause inside one segment is still a legitimate silence trim."""
    cuts, notes = snap.snap_cuts(
        [{"start": 6.2, "end": 7.4}], GAP_WORDS, 10.0, GAP_SEGMENTS
    )

    assert (cuts[0]["start"], cuts[0]["end"]) == (6.2, 7.4)
    assert notes == []


def test_segments_are_optional():
    cuts, _ = snap.snap_cuts([{"start": 4.6, "end": 5.3}], GAP_WORDS, 10.0)

    assert cuts[0]["end"] == 5.3


# --- fake silences over audible speech -------------------------------------
# 0.5s buckets over 6s: quiet everywhere except 1.5-2.5s, which is speech the
# word list never reported.
ENERGY = [-50.0, -50.0, -50.0, -15.0, -15.0, -50.0, -50.0, -50.0, -50.0, -50.0, -50.0, -50.0]
RESOLUTION = 0.5


def test_silence_cut_over_speech_is_dropped():
    cuts, notes = snap.trim_loud_silences(
        [{"start": 1.6, "end": 2.4, "type": "silence"}], ENERGY, RESOLUTION
    )
    assert cuts == []
    assert "that is speech, not silence" in notes[0]


def test_silence_cut_over_room_tone_survives():
    cuts, notes = snap.trim_loud_silences(
        [{"start": 3.0, "end": 4.0, "type": "silence"}], ENERGY, RESOLUTION
    )
    assert cuts == [{"start": 3.0, "end": 4.0, "type": "silence"}]
    assert notes == []


def test_silence_cut_is_trimmed_back_to_the_quiet_part():
    cuts, notes = snap.trim_loud_silences(
        [{"start": 1.6, "end": 4.0, "type": "silence"}], ENERGY, RESOLUTION
    )
    assert cuts[0]["start"] == 2.5
    assert cuts[0]["end"] == 4.0
    assert "edges were over audible speech" in notes[0]


def test_content_cuts_are_never_second_guessed_by_energy():
    cut = {"start": 1.6, "end": 2.4, "type": "content"}
    cuts, notes = snap.trim_loud_silences([cut], ENERGY, RESOLUTION)
    assert cuts == [cut]
    assert notes == []


def test_no_energy_map_leaves_cuts_alone():
    cut = {"start": 1.6, "end": 2.4, "type": "silence"}
    assert snap.trim_loud_silences([cut], [], 0.5) == ([cut], [])
    assert snap.trim_loud_silences([cut], ENERGY, 0.0) == ([cut], [])


def test_snap_plan_drops_a_fake_silence_before_snapping():
    plan = {"cuts": [{"start": 1.7, "end": 2.3, "type": "silence"}], "kept_segments": []}
    snapped, notes = snap.snap_plan(plan, WORDS, DURATION, [], ENERGY, RESOLUTION)
    assert snapped["cuts"] == []
    assert snapped["kept_segments"] == [{"start": 0.0, "end": DURATION}]
    assert any("that is speech" in n for n in notes)
