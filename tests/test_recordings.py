"""Biblioteca: the recordings in the inbox (auto_edit/recordings.py + the API)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from auto_edit import api, engine, recordings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTO_EDIT_WORKSPACE", str(tmp_path / "lib"))
    monkeypatch.setenv("AUTO_EDIT_INBOX", str(tmp_path / "inbox"))
    (tmp_path / "inbox").mkdir()
    return tmp_path


def _clip(path: Path, mtime: float, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def _probe(path):
    return {"duration": 7.5, "width": 1080, "height": 1920}


class TestParseProbe:
    def _payload(self, **stream):
        return json.dumps({"streams": [{"width": 1920, "height": 1080, **stream}], "format": {"duration": "7.600000"}})

    def test_phone_portrait_is_turned_upright(self):
        # iPhone: stored 1920x1080 with a -90 display rotation
        out = recordings.parse_probe(self._payload(side_data_list=[{"rotation": -90}]))
        assert out == {"duration": 7.6, "width": 1080, "height": 1920}

    def test_old_rotate_tag_too(self):
        assert recordings.parse_probe(self._payload(tags={"rotate": "90"}))["width"] == 1080

    def test_landscape_stays(self):
        assert recordings.parse_probe(self._payload())["width"] == 1920

    def test_garbage_is_empty(self):
        assert recordings.parse_probe("not json") == {}


class TestListing:
    def test_walks_subfolders_newest_first_with_the_folder(self, home):
        inbox = home / "inbox"
        _clip(inbox / "a.mp4", 1_700_000_000)
        _clip(inbox / "viagem" / "dia 1" / "b.MOV", 1_700_000_100)
        _clip(inbox / ".escondida" / "c.mp4", 1_700_000_200)  # hidden: skipped
        _clip(inbox / "notas.txt", 1_700_000_300)  # not a video: skipped
        _clip(inbox / "1" / "2" / "3" / "4" / "fundo.mp4", 1_700_000_400)  # deeper than 3 levels
        out = recordings.listing(inbox, probe=_probe)
        assert [(r["name"], r["folder"]) for r in out["recordings"]] == [("b.MOV", "viagem/dia 1"), ("a.mp4", "")]
        first = out["recordings"][0]
        assert first["ext"] == "mov" and first["height"] == 1920 and first["edits"] == []

    def test_media_info_is_probed_once(self, home):
        _clip(home / "inbox" / "a.mp4", 1_700_000_000)
        calls = []
        def probe(p):
            calls.append(p)
            return _probe(p)
        recordings.listing(home / "inbox", probe=probe)
        recordings.listing(home / "inbox", probe=probe)
        assert len(calls) == 1
        _clip(home / "inbox" / "a.mp4", 1_700_000_500, b"changed")  # a changed file is probed again
        recordings.listing(home / "inbox", probe=probe)
        assert len(calls) == 2

    def test_missing_folder(self, home):
        out = recordings.listing(home / "nao-existe", probe=_probe)
        assert out["exists"] is False and out["recordings"] == []


class TestEdits:
    def test_a_recording_knows_its_edits(self, home, monkeypatch):
        monkeypatch.setattr(recordings, "probe_media", _probe)
        clip = _clip(home / "inbox" / "IMG_1.MOV", 1_700_000_000)
        ws = home / "lib" / "IMG_1"
        ws.mkdir(parents=True)
        (ws / "pipeline.json").write_text(json.dumps({
            "video_path": str(clip), "video_name": "IMG_1", "type": "short", "name": "Unboxing",
            "current_stage": "done", "stages": {}, "created_at": "2026-01-01T00:00:00+00:00",
        }))
        rec = engine.recordings_view(engine.list_library())["recordings"][0]
        assert rec["edits"] == [{"id": "IMG_1", "name": "Unboxing", "status": "done"}]


class TestThumbnail:
    def test_only_videos_inside_the_inbox(self, home, monkeypatch):
        monkeypatch.setattr(recordings, "thumbnail", lambda p: p)
        inside = _clip(home / "inbox" / "sub" / "a.mp4", 1_700_000_000)
        outside = _clip(home / "fora.mp4", 1_700_000_000)
        text = _clip(home / "inbox" / "a.txt", 1_700_000_000)
        assert engine.recording_thumbnail(str(inside)) == inside.resolve()
        assert engine.recording_thumbnail(str(outside)) is None
        assert engine.recording_thumbnail(str(text)) is None
        assert engine.recording_thumbnail(str(home / "inbox" / ".." / "fora.mp4")) is None
        assert engine.recording_thumbnail("") is None

    def test_real_frame(self, home):
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not installed")
        clip = home / "inbox" / "clip.mp4"
        made = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=10", str(clip)],
            capture_output=True,
        )
        if made.returncode != 0:
            pytest.skip("ffmpeg can't make the test clip")
        thumb = recordings.thumbnail(clip)
        assert thumb and thumb.read_bytes()[:2] == b"\xff\xd8"  # a JPEG
        assert recordings.thumbnail(clip) == thumb  # cached


class TestEndpoint:
    def test_recordings_and_thumb_routes(self, home, monkeypatch):
        pytest.importorskip("flask")
        monkeypatch.setattr(recordings, "probe_media", _probe)
        _clip(home / "inbox" / "a.mp4", 1_700_000_000)
        client = api.create_app().test_client()
        body = client.get("/api/recordings").get_json()
        assert body["exists"] is True and body["recordings"][0]["name"] == "a.mp4"
        assert client.get("/api/recordings/thumb", query_string={"path": str(home / "fora.mp4")}).status_code == 404
