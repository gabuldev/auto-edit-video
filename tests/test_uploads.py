"""Resumable uploads into the inbox (auto_edit/uploads.py, #146)."""
from __future__ import annotations

import os

import pytest

from auto_edit import api, engine, uploads


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTO_EDIT_INBOX", str(tmp_path / "inbox"))
    (tmp_path / "inbox").mkdir()
    return api.create_app().test_client()


def _put(client, upload_id, offset, data):
    return client.put(f"/api/uploads/{upload_id}?offset={offset}", data=data,
                      content_type="application/octet-stream")


def test_chunks_land_in_the_inbox(client, tmp_path):
    data = os.urandom(3000)
    up = client.post("/api/uploads", json={"name": "gravação.mov", "size": len(data)})
    assert up.status_code == 201
    uid = up.get_json()["id"]
    assert up.get_json()["offset"] == 0

    r = _put(client, uid, 0, data[:1000]).get_json()
    assert r["offset"] == 1000 and r["done"] is False
    # The phone lost the answer and asks where it stopped.
    assert client.get(f"/api/uploads/{uid}").get_json()["offset"] == 1000
    r = _put(client, uid, 1000, data[1000:]).get_json()
    assert r["done"] is True
    dest = tmp_path / "inbox" / "Celular" / "gravação.mov"
    assert r["path"] == str(dest.resolve())
    assert dest.read_bytes() == data
    assert not list((tmp_path / "inbox" / uploads.FOLDER).glob("*.part"))


def test_a_resent_chunk_never_duplicates_bytes(client):
    uid = client.post("/api/uploads", json={"name": "a.mp4", "size": 10}).get_json()["id"]
    _put(client, uid, 0, b"01234")
    again = _put(client, uid, 0, b"01234")  # the same chunk twice
    assert again.status_code == 409
    assert again.get_json()["upload"]["offset"] == 5
    assert _put(client, uid, 5, b"56789").get_json()["done"] is True


def test_more_than_announced_is_refused(client):
    uid = client.post("/api/uploads", json={"name": "a.mp4", "size": 4}).get_json()["id"]
    res = _put(client, uid, 0, b"123456")
    assert res.status_code == 400
    assert client.get(f"/api/uploads/{uid}").get_json()["offset"] == 0


def test_a_taken_name_gets_a_number(client, tmp_path):
    for _ in range(2):
        uid = client.post("/api/uploads", json={"name": "clip.mp4", "size": 2}).get_json()["id"]
        path = _put(client, uid, 0, b"ab").get_json()["path"]
    assert path.endswith("clip (2).mp4")


@pytest.mark.parametrize("body", [
    {"name": "notas.txt", "size": 10},
    {"name": "a.mp4", "size": 0},
    {"name": "a.mp4", "size": "10"},
    {"name": "", "size": 10},
])
def test_bad_starts_are_refused(client, body):
    assert client.post("/api/uploads", json=body).status_code == 400


def test_names_cannot_escape_the_inbox(client, tmp_path):
    up = client.post("/api/uploads", json={"name": "../../etc/x.mp4", "size": 1}).get_json()
    assert up["name"] == "x.mp4"
    assert client.get("/api/uploads/..%2f..%2fx").status_code == 404


def test_cancel_drops_the_partial(client, tmp_path):
    uid = client.post("/api/uploads", json={"name": "a.mp4", "size": 10}).get_json()["id"]
    _put(client, uid, 0, b"123")
    assert client.delete(f"/api/uploads/{uid}").status_code == 200
    assert client.get(f"/api/uploads/{uid}").status_code == 404
    assert not list((tmp_path / "inbox" / uploads.FOLDER).iterdir())


def test_downloads_resume_with_range(client, tmp_path, monkeypatch):
    """Downloading the result to the phone resumes too (Range on file/<kind>)."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"0123456789")
    monkeypatch.setattr(engine, "artifact_path", lambda vid, kind: video)
    res = client.get("/api/videos/x/file/video", headers={"Range": "bytes=4-"})
    assert res.status_code == 206 and res.data == b"456789"
