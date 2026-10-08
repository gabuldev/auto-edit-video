"""Tests for publishing to YouTube: body/defaults rules, the resumable upload
loop (fake service — no network), the publish record, and the engine/API
wiring around it."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import api, engine
from auto_edit.publish import youtube as yt


# ── defaults / tags / body ────────────────────────────────────────────────────

class TestDefaults:
    def test_long_uses_youtube_fields(self):
        d = yt.defaults(
            {"type": "long"},
            {"youtube_title": " Título ", "youtube_description": "desc", "tags": ["a", "b"]},
        )
        assert d == {"title": "Título", "description": "desc", "tags": ["a", "b"]}

    def test_short_builds_description_from_hook_and_hashtags(self):
        d = yt.defaults(
            {"type": "short"},
            {"short_title": "Curto", "hook": "E se...?", "hashtags": ["nfc", "#dev brasil"]},
        )
        assert d["title"] == "Curto"
        assert d["description"] == "E se...?\n\n#nfc #devbrasil"
        assert d["tags"] == ["nfc", "dev brasil"]

    def test_missing_metadata_is_empty_not_an_error(self):
        assert yt.defaults({"type": "long"}, None) == {"title": "", "description": "", "tags": []}


class TestCleanTags:
    def test_strips_hash_and_dedupes_case_insensitively(self):
        assert yt.clean_tags(["#ESP32", "esp32", " iot ", ""]) == ["ESP32", "iot"]

    def test_stops_at_500_chars_counting_quotes_and_commas(self):
        tags = ["x" * 99] * 1 + [f"t{i} " + "y" * 95 for i in range(10)]
        out = yt.clean_tags(tags)
        cost = sum(len(t) + (2 if " " in t else 0) for t in out) + len(out) - 1
        assert cost <= yt.TAGS_MAX_CHARS
        assert len(out) < len(tags)


class TestBuildBody:
    def _body(self, **over):
        args = {"title": "Oi", "description": "d", "tags": ["a"], "privacy": "unlisted"}
        args.update(over)
        return yt.build_body(**args)

    def test_basic(self):
        b = self._body(language="pt")
        assert b["snippet"]["title"] == "Oi"
        assert b["snippet"]["defaultLanguage"] == "pt"
        assert b["snippet"]["categoryId"] == yt.DEFAULT_CATEGORY
        assert b["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}

    @pytest.mark.parametrize(
        "over",
        [{"title": "  "}, {"title": "x" * 101}, {"title": "a <b>"}, {"description": "<"}, {"privacy": "secret"}],
    )
    def test_rejects(self, over):
        with pytest.raises(yt.PublishError):
            self._body(**over)

    def test_schedule_forces_private_and_utc(self):
        when = (datetime.now(timezone(timedelta(hours=-3))) + timedelta(days=1)).replace(microsecond=0)
        b = self._body(privacy="public", publish_at=when.isoformat())
        assert b["status"]["privacyStatus"] == "private"
        assert b["status"]["publishAt"] == when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def test_schedule_in_the_past_or_without_timezone(self):
        with pytest.raises(yt.PublishError):
            self._body(publish_at="2020-01-01T00:00:00Z")
        with pytest.raises(yt.PublishError):
            self._body(publish_at="2099-01-01T00:00:00")


# ── thumbnail ─────────────────────────────────────────────────────────────────

class TestThumbnail:
    def test_small_png_goes_as_is(self, tmp_path):
        from PIL import Image
        p = tmp_path / "t.png"
        Image.new("RGB", (64, 36), "red").save(p)
        assert yt.prepare_thumbnail(p, tmp_path) == p

    def test_big_png_becomes_jpeg_under_2mb(self, tmp_path):
        import os
        from PIL import Image
        p = tmp_path / "t.png"
        Image.frombytes("RGB", (1280, 720), os.urandom(1280 * 720 * 3)).save(p)
        assert p.stat().st_size > yt.THUMB_MAX_BYTES
        out = yt.prepare_thumbnail(p, tmp_path)
        assert out.suffix == ".jpg" and out.stat().st_size <= yt.THUMB_MAX_BYTES


# ── upload (fake service) ─────────────────────────────────────────────────────

def _http_error(status=403, message="nope"):
    import httplib2
    from googleapiclient.errors import HttpError
    content = json.dumps({"error": {"message": message}}).encode()
    return HttpError(httplib2.Response({"status": status}), content)


class _Status:
    def __init__(self, frac):
        self._f = frac

    def progress(self):
        return self._f


class _Insert:
    def __init__(self, steps):
        self._steps = iter(steps)

    def next_chunk(self):
        step = next(self._steps)
        if isinstance(step, Exception):
            raise step
        return step


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _FakeYT:
    def __init__(self, steps, thumb_error=None):
        self.steps = steps
        self.thumb_error = thumb_error
        self.inserted = None
        self.thumb_for = None

    def videos(self):
        fake = self

        class V:
            def insert(self, part, body, media_body):
                fake.inserted = body
                return _Insert(fake.steps)
        return V()

    def thumbnails(self):
        fake = self

        class T:
            def set(self, videoId, media_body):
                def run():
                    if fake.thumb_error:
                        raise fake.thumb_error
                    fake.thumb_for = videoId
                    return {}
                return _Exec(run)
        return T()


class TestUpload:
    def _video(self, tmp_path):
        v = tmp_path / "v.mp4"
        v.write_bytes(b"\0" * 1024)
        return v

    def test_reports_progress_and_sets_thumbnail(self, tmp_path):
        thumb = tmp_path / "t.png"
        thumb.write_bytes(b"png")
        fake = _FakeYT([(_Status(0.4), None), (_Status(0.9), None), (None, {"id": "abc"})])
        seen = []
        res = yt.upload(self._video(tmp_path), {"snippet": {}}, thumbnail=thumb, on_progress=seen.append, service=fake)
        assert res == {"video_id": "abc", "url": "https://www.youtube.com/watch?v=abc", "warnings": [],
                       "captions": False, "comment_id": None}
        assert seen == [0.4, 0.9, 1.0]
        assert fake.thumb_for == "abc"

    def test_rejected_thumbnail_is_a_warning(self, tmp_path):
        thumb = tmp_path / "t.png"
        thumb.write_bytes(b"png")
        fake = _FakeYT([(None, {"id": "abc"})], thumb_error=_http_error(403, "verify your account"))
        res = yt.upload(self._video(tmp_path), {}, thumbnail=thumb, service=fake)
        assert res["video_id"] == "abc"
        assert "verify your account" in res["warnings"][0]

    def test_rejected_upload_raises_with_the_api_message(self, tmp_path):
        fake = _FakeYT([_http_error(400, "quotaExceeded")])
        with pytest.raises(yt.PublishError, match="quotaExceeded"):
            yt.upload(self._video(tmp_path), {}, service=fake)


def test_record_keeps_history(tmp_path):
    yt.add_record(tmp_path, "youtube", {"video_id": "a"})
    yt.add_record(tmp_path, "youtube", {"video_id": "b"})
    rec = yt.read_record(tmp_path)
    assert [e["video_id"] for e in rec["youtube"]] == ["a", "b"]
    assert all("published_at" in e for e in rec["youtube"])


# ── engine ────────────────────────────────────────────────────────────────────

def _done_ws(root: Path, wid="vid", vtype="long", metadata=None, output=True, stage="done"):
    ws = root / wid
    ws.mkdir(parents=True)
    (ws / "pipeline.json").write_text(json.dumps({
        "video_name": wid, "type": vtype, "language": "pt", "current_stage": stage,
        "created_at": "2026-01-01T00:00:00+00:00", "stages": {},
    }))
    (ws / "metadata.json").write_text(json.dumps(metadata or {
        "youtube_title": "Título", "youtube_description": "Desc", "tags": ["a"],
    }))
    if output:
        out = root / "output"
        out.mkdir(exist_ok=True)
        (out / f"{wid}_final.mp4").write_bytes(b"\0" * 2048)
        (out / f"{wid}_thumbnail.png").write_bytes(b"png")
    return ws


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    return tmp_path


class TestPublishState:
    def test_unknown(self, lib):
        assert engine.publish_state("nope") is None

    def test_not_done(self, lib):
        _done_ws(lib, stage="execute")
        st = engine.publish_state("vid")
        assert st["eligible"] is False and "terminou" in st["reason"]

    def test_done_without_output(self, lib):
        _done_ws(lib, output=False)
        assert engine.publish_state("vid")["eligible"] is False

    def test_long_defaults_and_thumbnail(self, lib):
        _done_ws(lib)
        st = engine.publish_state("vid")
        assert st["eligible"] is True
        assert st["defaults"]["title"] == "Título"
        assert st["defaults"]["privacy"] == "private"
        assert st["thumbnail"] is True
        assert st["account"]["connected"] is False

    def test_short_has_no_custom_thumbnail(self, lib):
        _done_ws(lib, vtype="short", metadata={"short_title": "S", "hook": "h", "hashtags": []})
        st = engine.publish_state("vid")
        assert st["thumbnail"] is False and st["defaults"]["title"] == "S"


class TestPublishJob:
    def test_needs_connection(self, lib):
        _done_ws(lib)
        with pytest.raises(yt.PublishError, match="não conectado"):
            engine.JobManager().publish_youtube("vid", {"title": "T"})

    def test_refuses_a_second_upload_without_force(self, lib, monkeypatch):
        ws = _done_ws(lib)
        monkeypatch.setattr(yt, "is_connected", lambda: True)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        with pytest.raises(yt.PublishError, match="já foi enviado"):
            engine.JobManager().publish_youtube("vid", {"title": "T"})

    def test_bad_fields_fail_before_spawning(self, lib, monkeypatch):
        _done_ws(lib)
        monkeypatch.setattr(yt, "is_connected", lambda: True)
        mgr = engine.JobManager()
        with pytest.raises(yt.PublishError):
            mgr.publish_youtube("vid", {"title": ""})
        assert mgr.job_for_video("vid") is None

    def test_run_publish_records_and_emits(self, lib):
        ws = _done_ws(lib)
        body = yt.build_body(title="T", description="", tags=[], privacy="unlisted")
        calls = {}

        def fake_upload(video, body, *, thumbnail, on_progress, **_):
            calls["video"], calls["thumb"] = video, thumbnail
            on_progress(0.5)
            on_progress(1.0)
            return {"video_id": "xyz", "url": "https://www.youtube.com/watch?v=xyz", "warnings": ["w"]}

        evs = []
        entry = engine.run_publish_youtube(
            ws, body, video=lib / "output" / "vid_final.mp4",
            thumbnail=lib / "output" / "vid_thumbnail.png", emit=evs.append, upload=fake_upload,
        )
        assert entry["privacy"] == "unlisted" and entry["warnings"] == ["w"]
        assert [e["pct"] for e in evs if e["type"] == "progress"] == [50, 100]
        assert evs[-1] == {"type": "done", "status": "done", "url": entry["url"], "video_id": "xyz"}
        assert yt.read_record(ws)["youtube"][0]["video_id"] == "xyz"


def test_connect_youtube_runs_in_background(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    import threading
    release = threading.Event()

    def fake_connect():
        release.wait(2)
        raise yt.PublishError("cancelado")

    st = engine.connect_youtube(connect=fake_connect)
    assert st["connecting"] is True
    assert engine.connect_youtube(connect=fake_connect)["connecting"] is True  # no second flow
    release.set()
    for _ in range(200):
        if not engine.youtube_account()["connecting"]:
            break
        time.sleep(0.01)
    acct = engine.youtube_account()
    assert acct["connecting"] is False and acct["error"] == "cancelado"


def test_open_url_only_youtube():
    calls = []
    run = lambda cmd, **k: calls.append(cmd)  # noqa: E731
    assert engine.open_url("https://www.youtube.com/watch?v=x", run=run)
    assert engine.open_url("https://studio.youtube.com/video/x/edit", run=run)
    assert not engine.open_url("https://evil.example/youtube.com/", run=run)
    assert not engine.open_url("file:///etc/passwd", run=run)
    assert len(calls) == 2


# ── HTTP ──────────────────────────────────────────────────────────────────────

class TestPublishEndpoints:
    def _client(self):
        pytest.importorskip("flask")
        return api.create_app(engine.JobManager()).test_client()

    def test_state(self, lib):
        _done_ws(lib)
        body = self._client().get("/api/videos/vid/publish").get_json()
        assert body["eligible"] is True and body["defaults"]["title"] == "Título"

    def test_409_when_already_published(self, lib):
        ws = _done_ws(lib)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        r = self._client().post("/api/videos/vid/publish/youtube", json={"title": "T"})
        assert r.status_code == 409

    def test_400_when_not_connected(self, lib):
        _done_ws(lib)
        r = self._client().post("/api/videos/vid/publish/youtube", json={"title": "T"})
        assert r.status_code == 400 and "conectado" in r.get_json()["error"]

    def test_open_url_rejects_other_hosts(self):
        r = self._client().post("/api/open-url", json={"url": "https://example.com"})
        assert r.status_code == 400


class TestClientConfig:
    def test_env_json_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        secret = tmp_path / "cs.json"
        secret.write_text(json.dumps({"installed": {"client_id": "env"}}))
        monkeypatch.setenv("AUTO_EDIT_YT_CLIENT_SECRET", str(secret))
        assert yt.client_config()["installed"]["client_id"] == "env"

    def test_falls_back_to_the_insights_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
        from auto_edit import config as cfg
        (cfg.tokens_dir() / "youtube.json").write_text(
            json.dumps({"client_id": "cid", "client_secret": "cs", "token_uri": "https://t"})
        )
        conf = yt.client_config()["installed"]
        assert (conf["client_id"], conf["client_secret"], conf["token_uri"]) == ("cid", "cs", "https://t")

    def test_none_without_either(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
        assert yt.client_config() is None
