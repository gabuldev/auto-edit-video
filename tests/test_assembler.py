import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.assembler import _flatten_clips, _build_video_filter, _pad_to_cover


def test_flatten_clips_preserves_order():
    clip_map = {"blocks": [
        {"id": 1, "vo_start": 0.0, "vo_end": 2.0, "clips": [
            {"file": "a.mp4", "in": 0.0, "out": 1.0},
            {"file": "b.mp4", "in": 1.0, "out": 2.0}]},
        {"id": 2, "vo_start": 2.0, "vo_end": 3.0, "clips": [
            {"file": "c.mp4", "in": 0.0, "out": 1.0}]},
    ]}
    flat = _flatten_clips(clip_map)
    assert [c["file"] for c in flat] == ["a.mp4", "b.mp4", "c.mp4"]


def test_build_video_filter_has_trim_and_concat():
    clips = [{"file": "a.mp4", "in": 0.0, "out": 1.0, "_idx": 0},
             {"file": "b.mp4", "in": 1.0, "out": 2.5, "_idx": 1}]
    filt = _build_video_filter(clips, reframe=(1080, 1920))
    assert filt.count("trim=") == 2
    assert "concat=n=2" in filt
    assert "scale=1080:1920" in filt
    assert "[outv]" in filt


def test_pad_stretches_last_clip_when_short():
    flat = [{"file": "a.mp4", "in": 0.0, "out": 1.0, "_idx": 0},
            {"file": "b.mp4", "in": 0.0, "out": 1.0, "_idx": 1}]
    padded = _pad_to_cover(flat, vo_duration=3.0)
    assert padded[-1]["out"] - padded[-1]["in"] == 2.0


def test_pad_noop_when_already_covers():
    flat = [{"file": "a.mp4", "in": 0.0, "out": 2.0, "_idx": 0}]
    padded = _pad_to_cover(flat, vo_duration=1.5)
    assert padded[-1]["out"] == 2.0
