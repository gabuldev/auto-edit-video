import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.clip_analyzer import _frame_timestamps, _is_video


def test_frame_timestamps_spreads_across_duration():
    ts = _frame_timestamps(10.0, n=5)
    assert len(ts) == 5
    assert ts[0] > 0 and ts[-1] < 10.0
    assert ts == sorted(ts)


def test_frame_timestamps_short_clip():
    ts = _frame_timestamps(1.0, n=5)
    assert all(0 < t < 1.0 for t in ts)


def test_is_video_by_extension():
    assert _is_video(Path("a.mp4"))
    assert _is_video(Path("a.MOV"))
    assert not _is_video(Path("a.txt"))
