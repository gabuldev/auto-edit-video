"""The pinned comment the metadata stage writes reaches the output notes."""
from auto_edit import pipeline


def test_long_notes_carry_the_pinned_comment(tmp_path):
    txt = tmp_path / "n.txt"
    pipeline._write_metadata_txt(txt, {"youtube_title": "T", "pinned_comment": "Terminal ou app?"}, "long")
    assert "COMENTÁRIO PRA FIXAR:\nTerminal ou app?" in txt.read_text(encoding="utf-8")


def test_short_notes_carry_the_pinned_comment(tmp_path):
    txt = tmp_path / "n.txt"
    pipeline._write_metadata_txt(txt, {"short_title": "S", "pinned_comment": "ESP32 ou Pi?"}, "short")
    assert "COMENTÁRIO PRA FIXAR:\nESP32 ou Pi?" in txt.read_text(encoding="utf-8")


def test_old_metadata_without_it_has_no_section(tmp_path):
    txt = tmp_path / "n.txt"
    pipeline._write_metadata_txt(txt, {"youtube_title": "T"}, "long")
    assert "COMENTÁRIO" not in txt.read_text(encoding="utf-8")
