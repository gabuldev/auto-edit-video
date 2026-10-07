"""Tests for YouTube chapters: the rules YouTube enforces silently, the
description block, the in-place normalization of metadata.json, and every
place the description is read from."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import chapters as ch
from auto_edit import engine, pipeline, runner
from auto_edit.publish import youtube as yt

GOOD = [
    {"start": 3, "title": "Abertura"},
    {"start": 55, "title": "A nova interface"},
    {"start": 140, "title": "Pipeline por dentro"},
    {"start": 420, "title": "O que vem por aí"},
]


class TestNormalize:
    def test_keeps_valid_and_snaps_first_to_zero(self):
        kept, notes = ch.normalize(GOOD, duration=569)
        assert [c["start"] for c in kept] == [0, 55, 140, 420]
        assert notes == []

    def test_sorts_out_of_order(self):
        kept, _ = ch.normalize(list(reversed(GOOD)))
        assert [c["title"] for c in kept] == ["Abertura", "A nova interface", "Pipeline por dentro", "O que vem por aí"]

    def test_drops_chapters_shorter_than_10s(self):
        kept, notes = ch.normalize(GOOD + [{"start": 145, "title": "colado"}])
        assert "colado" not in [c["title"] for c in kept]
        assert any("colado" in n for n in notes)

    def test_fewer_than_three_is_nothing(self):
        kept, notes = ch.normalize(GOOD[:2])
        assert kept == []
        assert "3" in notes[-1]

    def test_drops_starts_outside_the_video(self):
        kept, notes = ch.normalize(GOOD + [{"start": 565, "title": "fim"}, {"start": -1, "title": "antes"}], duration=569)
        titles = [c["title"] for c in kept]
        assert "fim" not in titles and "antes" not in titles
        assert len(notes) == 2

    def test_bad_items_and_whitespace(self):
        kept, notes = ch.normalize(GOOD + [{"start": "x", "title": "a"}, {"start": 300, "title": "  muito \n  espaço "}, {"start": 500}])
        assert {"start": 300, "title": "muito espaço"} in kept
        assert len(notes) == 2

    def test_not_a_list(self):
        assert ch.normalize(None) == ([], [])
        assert ch.normalize("0:00 x")[0] == []


class TestFormat:
    def test_stamp(self):
        assert ch.stamp(0) == "0:00"
        assert ch.stamp(65.9) == "1:05"
        assert ch.stamp(3725) == "1:02:05"

    def test_block_and_description(self):
        kept, _ = ch.normalize(GOOD)
        block = ch.format_block(kept)
        assert block.splitlines() == ["Capítulos:", "0:00 Abertura", "0:55 A nova interface", "2:20 Pipeline por dentro", "7:00 O que vem por aí"]
        desc = ch.description_with_chapters("Texto.", kept)
        assert desc == f"Texto.\n\n{block}"
        assert ch.description_with_chapters(desc, kept) == desc  # idempotent

    def test_no_chapters_leaves_description(self):
        assert ch.description_with_chapters("Texto.  ", []) == "Texto."


def _ws(tmp_path, metadata, duration=569.0):
    ws = tmp_path / "vid"
    ws.mkdir()
    (ws / "metadata.json").write_text(json.dumps(metadata))
    (ws / "post_cut_transcription.json").write_text(json.dumps({
        "duration": duration,
        "segments": [
            {"start": 0.0, "end": 4.1, "text": "Fala galera"},
            {"start": 55.3, "end": 57.0, "text": " Olha isso daqui "},
        ],
    }))
    return ws


class TestApply:
    def test_normalizes_in_place(self, tmp_path):
        ws = _ws(tmp_path, {"youtube_title": "T", "chapters": GOOD + [{"start": 600, "title": "fora"}]})
        notes = ch.apply(ws)
        meta = json.loads((ws / "metadata.json").read_text(encoding="utf-8"))
        assert [c["start"] for c in meta["chapters"]] == [0, 55, 140, 420]
        assert meta["youtube_title"] == "T"
        assert any("fora" in n for n in notes)

    def test_short_without_chapters_is_untouched(self, tmp_path):
        ws = _ws(tmp_path, {"short_title": "S"})
        before = (ws / "metadata.json").read_text(encoding="utf-8")
        assert ch.apply(ws) == []
        assert (ws / "metadata.json").read_text(encoding="utf-8") == before


class TestPrompt:
    def _pipeline_ws(self, tmp_path, vtype):
        ws = _ws(tmp_path, {})
        (ws / "pipeline.json").write_text(json.dumps({"type": vtype, "context": "c", "language": "pt", "stages": {}}))
        return ws

    def test_long_prompt_has_timestamps(self, tmp_path):
        ws = self._pipeline_ws(tmp_path, "long")
        prompt = runner.build_prompt("metadata", ws, Path("agents/metadata.md"))
        assert "[0:00] Fala galera" in prompt
        assert "[0:55] Olha isso daqui" in prompt
        assert "Duration: 9:29" in prompt

    def test_short_prompt_stays_plain(self, tmp_path):
        ws = self._pipeline_ws(tmp_path, "short")
        prompt = runner.build_prompt("metadata", ws, Path("agents/metadata.md"))
        assert "[0:00]" not in prompt
        assert "Fala galera Olha isso daqui" in prompt


def test_every_description_reader_includes_chapters(tmp_path, monkeypatch):
    kept, _ = ch.normalize(GOOD)
    meta = {"youtube_title": "T", "youtube_description": "Desc.", "tags": [], "chapters": kept}

    txt = tmp_path / "notes.txt"
    pipeline._write_metadata_txt(txt, meta, "long")
    assert "0:55 A nova interface" in txt.read_text(encoding="utf-8")

    assert "0:55 A nova interface" in yt.defaults({"type": "long"}, meta)["description"]

    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    ws = tmp_path / "w"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"video_name": "w", "type": "long", "current_stage": "done", "stages": {}}))
    (ws / "metadata.json").write_text(json.dumps(meta))
    assert "0:55 A nova interface" in engine.result("w")["metadata"]["youtube_description"]
    # the file itself keeps them apart
    assert json.loads((ws / "metadata.json").read_text(encoding="utf-8"))["youtube_description"] == "Desc."
