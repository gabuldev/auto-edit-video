"""Long-video subtitles from the post-cut transcript, and sending them (plus
the pinned comment) with the YouTube upload."""
import json

import pytest

from auto_edit import engine, subtitles
from auto_edit.publish import youtube as yt


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


class TestGroup:
    def test_pause_starts_a_new_caption(self):
        caps = subtitles.group({"words": [_w("Oi", 0.0, 0.3), _w("gente.", 0.3, 0.8), _w("Hoje", 2.0, 2.3)]})
        assert [c["text"] for c in caps] == ["Oi gente.", "Hoje"]

    def test_lines_stay_within_42_and_two_lines(self):
        words = [_w(f"palavra{i}", i * 0.3, i * 0.3 + 0.25) for i in range(60)]
        for cap in subtitles.group({"words": words}):
            lines = cap["text"].split("\n")
            assert len(lines) <= 2
            assert all(len(line) <= subtitles.LINE_CHARS for line in lines)

    def test_long_runs_are_split_by_time(self):
        words = [_w("a", i * 0.5, i * 0.5 + 0.4) for i in range(40)]
        caps = subtitles.group({"words": words})
        assert all(c["end"] - c["start"] <= subtitles.MAX_SECONDS + 0.5 for c in caps)

    def test_short_caption_is_held_but_not_into_the_next(self):
        caps = subtitles.group({"words": [_w("Oi", 0.0, 0.2), _w("tchau", 0.95, 1.2)]})
        assert caps[0]["end"] <= caps[1]["start"]
        caps = subtitles.group({"words": [_w("Fim", 5.0, 5.2)]})
        assert caps[0]["end"] == pytest.approx(6.0)

    def test_bad_words_are_skipped(self):
        assert subtitles.group({"words": [{"word": "x"}, _w(" ", 0, 1)]}) == []


def test_srt_format():
    srt = subtitles.to_srt([{"start": 0.0, "end": 3725.5, "text": "linha um\nlinha dois"}])
    assert srt == "1\n00:00:00,000 --> 01:02:05,500\nlinha um\nlinha dois\n"


def test_write_for_workspace(tmp_path):
    (tmp_path / "post_cut_transcription.json").write_text(json.dumps({"words": [_w("Olá.", 0.0, 0.5)]}), encoding="utf-8")
    dest = subtitles.write_for_workspace(tmp_path, tmp_path / "v.srt")
    assert dest.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> ")
    assert subtitles.write_for_workspace(tmp_path / "nope", tmp_path / "x.srt") is None


# ── upload: captions + comment ────────────────────────────────────────────────

def _http_error(message):
    import httplib2
    from googleapiclient.errors import HttpError
    return HttpError(httplib2.Response({"status": 403}), json.dumps({"error": {"message": message}}).encode())


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _FakeYT:
    def __init__(self, caption_error=None, comment_error=None):
        self.calls = {}
        self.caption_error = caption_error
        self.comment_error = comment_error

    def videos(self):
        class V:
            def insert(self, part, body, media_body):
                class R:
                    def next_chunk(self):
                        return None, {"id": "vid1"}
                return R()
        return V()

    def captions(self):
        fake = self

        class C:
            def insert(self, part, body, media_body):
                def run():
                    if fake.caption_error:
                        raise fake.caption_error
                    fake.calls["captions"] = body
                    return {"id": "cap1"}
                return _Exec(run)
        return C()

    def commentThreads(self):
        fake = self

        class T:
            def insert(self, part, body):
                def run():
                    if fake.comment_error:
                        raise fake.comment_error
                    fake.calls["comment"] = body
                    return {"id": "c1"}
                return _Exec(run)
        return T()


class TestUploadExtras:
    def _video(self, tmp_path):
        v = tmp_path / "v.mp4"
        v.write_bytes(b"\0")
        srt = tmp_path / "v.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")
        return v, srt

    def test_sends_captions_and_comment(self, tmp_path):
        v, srt = self._video(tmp_path)
        fake = _FakeYT()
        res = yt.upload(v, {}, captions=srt, language="pt", comment="Terminal ou app?", service=fake)
        assert res["captions"] is True and res["comment_id"] == "c1" and res["warnings"] == []
        assert fake.calls["captions"]["snippet"] == {"videoId": "vid1", "language": "pt", "name": "", "isDraft": False}
        assert fake.calls["comment"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Terminal ou app?"

    def test_refusals_are_warnings_not_failures(self, tmp_path):
        v, srt = self._video(tmp_path)
        fake = _FakeYT(caption_error=_http_error("forbidden"), comment_error=_http_error("commentsDisabled"))
        res = yt.upload(v, {}, captions=srt, comment="?", service=fake)
        assert res["video_id"] == "vid1" and res["captions"] is False and res["comment_id"] is None
        assert any("legenda" in w for w in res["warnings"])
        assert any("privado" in w for w in res["warnings"])


def _done_ws(root, vtype="long", srt=True):
    ws = root / "vid"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"video_name": "vid", "type": vtype, "language": "pt",
                                                  "current_stage": "done", "stages": {}}), encoding="utf-8")
    (ws / "metadata.json").write_text(json.dumps({"youtube_title": "T", "pinned_comment": "App ou terminal?"}), encoding="utf-8")
    out = root / "output"
    out.mkdir()
    (out / "vid_final.mp4").write_bytes(b"\0" * 64)
    if srt:
        (out / "vid.srt").write_text("1\n", encoding="utf-8")
    return ws


class TestEngine:
    @pytest.fixture
    def lib(self, tmp_path, monkeypatch):
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
        return tmp_path

    def test_state_offers_captions_and_comment_on_a_long(self, lib):
        _done_ws(lib)
        st = engine.publish_state("vid")
        assert st["captions"] is True and st["pinned_comment"] == "App ou terminal?"

    def test_short_gets_no_caption_track(self, lib):
        _done_ws(lib, vtype="short")
        assert engine.publish_state("vid")["captions"] is False

    def test_run_publish_passes_extras_and_records_them(self, lib):
        ws = _done_ws(lib)
        seen = {}

        def fake_upload(video, body, **kw):
            seen.update(kw)
            return {"video_id": "x", "url": "u", "warnings": [], "captions": True, "comment_id": "c"}

        body = yt.build_body(title="T", description="", tags=[], privacy="unlisted")
        entry = engine.run_publish_youtube(ws, body, video=lib / "output" / "vid_final.mp4", thumbnail=None,
                                           emit=lambda e: None, captions=lib / "output" / "vid.srt",
                                           language="pt", comment="?", upload=fake_upload)
        assert seen["captions"].name == "vid.srt" and seen["language"] == "pt" and seen["comment"] == "?"
        assert entry["captions"] is True and entry["comment_id"] == "c"
