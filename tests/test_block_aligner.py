import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.block_aligner import _normalize, _align_blocks


def test_normalize_strips_punct_and_case():
    assert _normalize("A Tower, Bridge!") == "a tower bridge"


def test_align_exact_phrases():
    words = [
        {"word": "a", "start": 0.0, "end": 0.2},
        {"word": "ponte", "start": 0.2, "end": 0.6},
        {"word": "abriu", "start": 0.6, "end": 1.0},
        {"word": "ele", "start": 2.0, "end": 2.2},
        {"word": "pulou", "start": 2.2, "end": 2.6},
    ]
    blocks = [
        {"id": 1, "narration": "A ponte abriu"},
        {"id": 2, "narration": "Ele pulou"},
    ]
    out = _align_blocks(words, blocks, vo_duration=2.6)
    assert out[0]["vo_start"] == 0.0
    assert abs(out[0]["vo_end"] - 2.0) < 0.01   # contiguous: ends where block 2 begins
    assert abs(out[1]["vo_start"] - 2.0) < 0.01
    assert abs(out[1]["vo_end"] - 2.6) < 0.01   # last block ends at vo_duration


def test_align_tolerates_small_variation():
    words = [
        {"word": "ficou", "start": 0.0, "end": 0.4},
        {"word": "muito", "start": 0.4, "end": 0.8},
        {"word": "maneira", "start": 0.8, "end": 1.2},
    ]
    blocks = [{"id": 1, "narration": "ficou muito maneiro"}]
    out = _align_blocks(words, blocks, vo_duration=1.2)
    assert out[0]["vo_start"] == 0.0
    assert abs(out[0]["vo_end"] - 1.2) < 0.01


def test_blocks_are_contiguous_no_gap():
    words = [{"word": f"w{i}", "start": i * 1.0, "end": i * 1.0 + 0.5} for i in range(6)]
    blocks = [
        {"id": 1, "narration": "w0 w1 w2"},
        {"id": 2, "narration": "w3 w4 w5"},
    ]
    out = _align_blocks(words, blocks, vo_duration=5.5)
    assert out[1]["vo_start"] == out[0]["vo_end"]


def test_more_blocks_than_voice_no_negative_durations():
    # 2 words of voice but 3 scripted blocks — extra blocks must not go negative
    words = [
        {"word": "ola", "start": 0.0, "end": 0.5},
        {"word": "mundo", "start": 0.5, "end": 1.0},
    ]
    blocks = [
        {"id": 1, "narration": "ola mundo"},
        {"id": 2, "narration": "bloco extra um"},
        {"id": 3, "narration": "bloco extra dois"},
    ]
    out = _align_blocks(words, blocks, vo_duration=1.0)
    assert len(out) == 3
    for b in out:
        assert b["vo_end"] >= b["vo_start"], b
        assert 0.0 <= b["vo_start"] <= 1.0
        assert 0.0 <= b["vo_end"] <= 1.0
    # starts must be monotonic non-decreasing
    starts = [b["vo_start"] for b in out]
    assert starts == sorted(starts)
