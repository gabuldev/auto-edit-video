import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auto_edit import pipeline


def test_short_sequence_matches_legacy_order():
    seq = pipeline.stage_sequence("short")
    assert seq == ["extract", "plan", "review", "execute", "caption",
                   "evaluate", "metadata", "thumbnail", "done"]


def test_long_sequence_has_overlay_not_caption():
    seq = pipeline.stage_sequence("long")
    assert "overlay" in seq and "caption" not in seq


def test_narrated_sequence():
    seq = pipeline.stage_sequence("narrated")
    assert seq == ["parse-script", "extract-vo", "align-blocks",
                   "analyze-clips", "match", "review", "assemble",
                   "caption", "metadata", "thumbnail", "done"]


def test_init_materializes_only_sequence_stages(tmp_path):
    p = pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx")
    assert set(p["stages"]) == set(pipeline.stage_sequence("narrated")) - {"done"}
    assert "plan" not in p["stages"]


def test_set_stage_status_advances_within_type(tmp_path):
    pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx")
    p = pipeline.set_stage_status(tmp_path, "parse-script", "complete")
    assert p["current_stage"] == "extract-vo"


def test_init_stores_narrated_inputs(tmp_path):
    p = pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx",
                      voice_path=Path("/tmp/vo.mp3"),
                      clips_dir=Path("/tmp/brolls"))
    assert p["voice_path"].endswith("vo.mp3")
    assert p["clips_dir"].endswith("brolls")
