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


class _FakeVideos:
    def __init__(self, items):
        self.items, self.calls = items, []

    def videos(self):
        return self

    def list(self, part, id, maxResults):
        self.calls.append(id)
        ids = id.split(",")
        found = [i for i in self.items if i["id"] in ids]
        return type("R", (), {"execute": lambda _self: {"items": found}})()


def test_live_status_reads_the_status_of_each_video():
    service = _FakeVideos([
        {"id": "a", "status": {"privacyStatus": "public", "uploadStatus": "processed"}},
        {"id": "b", "status": {"privacyStatus": "private", "publishAt": "2026-10-28T19:51:00Z", "uploadStatus": "uploaded"}},
    ])
    live = yt.live_status(["a", "b", "gone"], service=service)
    assert live == {
        "a": {"privacy": "public", "publish_at": None, "upload_status": "processed"},
        "b": {"privacy": "private", "publish_at": "2026-10-28T19:51:00Z", "upload_status": "uploaded"},
    }  # "gone" (deleted on YouTube) just isn't there
    assert yt.live_status([], service=service) == {} and len(service.calls) == 1


def test_live_status_asks_50_at_a_time():
    service = _FakeVideos([])
    yt.live_status([f"v{i}" for i in range(120)], service=service)
    assert [len(c.split(",")) for c in service.calls] == [50, 50, 20]


class TestPublishLive:
    def test_unknown(self, lib):
        assert engine.publish_live("nope") is None

    def test_nothing_sent_or_not_connected(self, lib, monkeypatch):
        ws = _done_ws(lib)
        assert engine.publish_live("vid") == {"checked": False, "videos": {}}
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        monkeypatch.setattr(yt, "is_connected", lambda: False)
        assert engine.publish_live("vid", fetch=lambda ids: pytest.fail("asked")) == {"checked": False, "videos": {}}

    def test_asks_youtube_for_the_sent_ids(self, lib, monkeypatch):
        ws = _done_ws(lib)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        yt.add_record(ws, "youtube", {"video_id": "b", "url": "u"})
        monkeypatch.setattr(yt, "is_connected", lambda: True)
        asked = []
        live = engine.publish_live("vid", fetch=lambda ids: asked.append(ids) or {"a": {"privacy": "public"}})
        assert asked == [["a", "b"]]
        assert live == {"checked": True, "videos": {"a": {"privacy": "public"}}}

    def test_deleted_on_youtube_gets_marked(self, lib, monkeypatch):
        """Both deleted in Studio: publish.json says so, and "Publicado" goes."""
        ws = _done_ws(lib)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        yt.add_record(ws, "youtube", {"video_id": "b", "url": "u"})
        monkeypatch.setattr(yt, "is_connected", lambda: True)
        assert engine.summarize(ws)["published"]["count"] == 2
        engine.publish_live("vid", fetch=lambda ids: {"b": {"privacy": "private"}})
        assert [bool(r.get("removed")) for r in yt.read_record(ws)["youtube"]] == [True, False]
        assert engine.summarize(ws)["published"]["count"] == 1
        engine.publish_live("vid", fetch=lambda ids: {})
        assert engine.summarize(ws)["published"] is None
        # one that shows up again (another account was connected) loses the mark
        engine.publish_live("vid", fetch=lambda ids: {"a": {}})
        assert [bool(r.get("removed")) for r in yt.read_record(ws)["youtube"]] == [False, True]

    def test_failure_keeps_the_record(self, lib, monkeypatch):
        ws = _done_ws(lib)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        monkeypatch.setattr(yt, "is_connected", lambda: True)

        def offline(ids):
            raise OSError("sem rede")
        live = engine.publish_live("vid", fetch=offline)
        assert live["checked"] is False and "sem rede" in live["error"]


class TestRefreshPublished:
    """Edições asks YouTube once (all workspaces together) when it opens."""

    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(engine, "_published_checked_at", None)
        monkeypatch.setattr(yt, "is_connected", lambda: True)

    def _sent(self, lib, name, *ids):
        ws = lib / name
        ws.mkdir()
        (ws / "pipeline.json").write_text("{}")
        for i in ids:
            yt.add_record(ws, "youtube", {"video_id": i, "url": "u"})
        return ws

    def test_one_call_for_everything_and_marks_the_deleted(self, lib):
        a = self._sent(lib, "A", "a1", "a2")
        b = self._sent(lib, "B", "b1")
        calls = []
        out = engine.refresh_published(fetch=lambda ids: calls.append(ids) or {"a2": {}, "b1": {}})
        assert calls == [["a1", "a2", "b1"]] and out == {"checked": True, "changed": True}
        assert [bool(r.get("removed")) for r in yt.read_record(a)["youtube"]] == [True, False]
        assert not yt.read_record(b)["youtube"][0].get("removed")

    def test_at_most_once_a_minute(self, lib):
        self._sent(lib, "A", "a1")
        clock = iter([100.0, 130.0, 170.0, 170.0])
        now = lambda: next(clock)  # noqa: E731
        calls = []
        fetch = lambda ids: calls.append(ids) or {"a1": {}}  # noqa: E731
        assert engine.refresh_published(fetch=fetch, now=now)["checked"] is True
        assert engine.refresh_published(fetch=fetch, now=now) == {"checked": False, "changed": False}
        assert engine.refresh_published(fetch=fetch, now=now) == {"checked": True, "changed": False}
        assert len(calls) == 2

    def test_nothing_sent_offline_or_disconnected(self, lib, monkeypatch):
        assert engine.refresh_published(fetch=lambda ids: pytest.fail("asked"))["checked"] is False
        self._sent(lib, "A", "a1")

        def offline(ids):
            raise OSError("sem rede")
        out = engine.refresh_published(fetch=offline)
        assert out["checked"] is False and "sem rede" in out["error"]
        assert not yt.read_record(lib / "A")["youtube"][0].get("removed")  # nothing guessed
        monkeypatch.setattr(yt, "is_connected", lambda: False)
        assert engine.refresh_published(fetch=lambda ids: pytest.fail("asked"))["checked"] is False


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


def test_cancelled_connect_is_not_an_error(monkeypatch, tmp_path):
    """Cancelling the wait for the browser leaves it idle, with no error shown."""
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    import threading
    release = threading.Event()

    def waiting():
        release.wait(5)
        raise RuntimeError("access_denied")

    def cancel():
        release.set()
        return True
    monkeypatch.setattr(yt, "cancel_consent", cancel)
    assert engine.connect_youtube(connect=waiting)["connecting"] is True
    acct = engine.cancel_youtube_connect()
    assert acct["connecting"] is False and acct["error"] is None
    # the next attempt's real failure still shows (the cancel was that attempt's)
    engine.connect_youtube(connect=lambda: (_ for _ in ()).throw(RuntimeError("sem rede")))
    for _ in range(200):
        if not engine.youtube_account()["connecting"]:
            break
        time.sleep(0.01)
    assert engine.youtube_account()["error"] == "sem rede"


def test_open_url_only_youtube():
    calls = []
    run = lambda cmd, **k: calls.append(cmd)  # noqa: E731
    assert engine.open_url("https://www.youtube.com/watch?v=x", run=run)
    assert engine.open_url("https://studio.youtube.com/video/x/edit", run=run)
    assert not engine.open_url("https://evil.example/youtube.com/", run=run)
    assert not engine.open_url("file:///etc/passwd", run=run)
    # Configurações → YouTube links to the Google Cloud console, only there
    assert engine.open_url("https://console.cloud.google.com/auth/clients", run=run)
    assert not engine.open_url("https://console.cloud.google.com.evil.example/", run=run)
    assert len(calls) == 3


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

    def test_deleted_on_youtube_is_not_already_published(self, lib):
        """All sends deleted on YouTube: sending again needs no force."""
        ws = _done_ws(lib)
        yt.add_record(ws, "youtube", {"video_id": "a", "url": "u"})
        yt.mark_gone(ws, {"a"}, set())
        r = self._client().post("/api/videos/vid/publish/youtube", json={"title": "T"})
        assert r.status_code == 400 and "conectado" in r.get_json()["error"]  # past the 409

    def test_400_when_not_connected(self, lib):
        _done_ws(lib)
        r = self._client().post("/api/videos/vid/publish/youtube", json={"title": "T"})
        assert r.status_code == 400 and "conectado" in r.get_json()["error"]

    def test_open_url_rejects_other_hosts(self):
        r = self._client().post("/api/open-url", json={"url": "https://example.com"})
        assert r.status_code == 400

    def test_client_json_picked_in_the_app(self, lib, monkeypatch):
        """Configurações → YouTube: choosing the JSON is enough to connect."""
        monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
        c = self._client()
        assert c.get("/api/publish/youtube").get_json()["has_client_secret"] is False
        f = lib / "client_secret_123.apps.googleusercontent.com.json"
        f.write_text(json.dumps({"installed": {"client_id": "123.apps.googleusercontent.com", "client_secret": "s"}}))
        body = c.put("/api/publish/youtube/client", json={"path": str(f)}).get_json()
        assert body["has_client_secret"] is True and body["client_id"] == "123.apps.googleusercontent.com"

    def test_client_json_from_the_browser(self, lib, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
        raw = json.dumps({"installed": {"client_id": "b.apps.googleusercontent.com", "client_secret": "s"}})
        body = self._client().put("/api/publish/youtube/client", json={"content": raw}).get_json()
        assert body["client_id"] == "b.apps.googleusercontent.com"

    @pytest.mark.parametrize("name, data, message", [
        ("web.json", {"web": {"client_id": "w", "client_secret": "s"}}, "Aplicativo da Web"),
        ("video.mp4", {"installed": {"client_id": "x", "client_secret": "s"}}, ".json"),
    ])
    def test_client_json_refused(self, lib, monkeypatch, name, data, message):
        monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
        f = lib / name
        f.write_text(json.dumps(data))
        r = self._client().put("/api/publish/youtube/client", json={"path": str(f)})
        assert r.status_code == 400 and message in r.get_json()["error"]
        assert self._client().get("/api/publish/youtube").get_json()["has_client_secret"] is False

    def test_client_json_missing_file(self, lib):
        r = self._client().put("/api/publish/youtube/client", json={"path": str(lib / "nope.json")})
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
