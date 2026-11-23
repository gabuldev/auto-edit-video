"""The LAN listener for real (auto_edit/lan.py, #145): TLS with the pinned
certificate, a paired device gets in, anyone else gets 401."""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
import time
import urllib.error
import urllib.request

import pytest

from auto_edit import api, engine, lan


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    pytest.importorskip("cryptography")
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    manager = lan.Lan()
    monkeypatch.setattr(lan, "manager", manager)
    monkeypatch.setattr(manager, "_announce", lambda port, fp: None)  # no mDNS on CI
    app = api.create_app()
    local = app.test_client()
    port = _free_port()
    yield manager, local, port
    manager.stop()


def _call(port: int, path: str, *, token: str | None = None, body=None, fingerprint: str | None = None):
    """(status, json, peer certificate fingerprint) over the LAN listener."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # self-signed: checked by fingerprint below, like the app
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with ctx.wrap_socket(raw) as tls:
            seen = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
            return res.status, json.loads(res.read() or b"null"), seen
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"null"), seen


def _wait(port: int) -> None:
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("o listener não subiu")


def test_off_by_default(setup):
    manager, local, _ = setup
    state = local.get("/api/lan").get_json()
    assert state["enabled"] is False and state["running"] is False
    assert state["fingerprint"] is None and state["devices"] == []


def test_a_paired_device_gets_in_and_anyone_else_gets_401(setup):
    manager, local, port = setup
    state = local.put("/api/lan", json={"enabled": True, "port": port}).get_json()
    assert state["running"] is True, state["error"]
    _wait(port)

    # Not paired: 401 on routes and on the SSE.
    assert _call(port, "/api/health")[0] == 401
    assert _call(port, "/api/library", token="inventado")[0] == 401
    assert _call(port, "/api/videos/x/events")[0] == 401
    # The management routes are only for this machine, even with a token.
    assert _call(port, "/api/lan")[0] == 403

    pairing = local.post("/api/lan/pairing").get_json()
    assert pairing["port"] == port
    assert f"fp={pairing['fingerprint']}" in pairing["url"] and f"code={pairing['code']}" in pairing["url"]

    status, body, seen = _call(port, "/api/pair", body={"code": pairing["code"], "name": "Pixel 8"})
    assert status == 200
    assert seen == pairing["fingerprint"]  # the certificate is the one in the QR
    token = body["token"]

    status, health, _ = _call(port, "/api/health", token=token)
    assert status == 200 and health["ok"] is True
    assert _call(port, "/api/library", token=token)[0] == 200

    # The code was used: a second device can't reuse it.
    assert _call(port, "/api/pair", body={"code": pairing["code"]})[0] == 403

    devices = local.get("/api/lan").get_json()["devices"]
    assert [d["name"] for d in devices] == ["Pixel 8"]
    assert devices[0]["last_seen"]
    # Only the token's hash is on disk.
    saved = (manager.folder / "devices.json").read_text()
    assert token not in saved

    assert local.delete(f"/api/lan/devices/{devices[0]['id']}").status_code == 200
    assert _call(port, "/api/health", token=token)[0] == 401

    local.put("/api/lan", json={"enabled": False})
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()


def test_the_certificate_survives_a_restart(setup):
    manager, local, port = setup
    first = local.put("/api/lan", json={"enabled": True, "port": port}).get_json()["fingerprint"]
    local.put("/api/lan", json={"enabled": False})
    again = local.put("/api/lan", json={"enabled": True, "port": port}).get_json()["fingerprint"]
    assert first == again  # a paired phone keeps trusting it


def test_wrong_codes_drop_the_pairing(setup, monkeypatch):
    manager, local, _ = setup
    monkeypatch.setattr(manager, "start", lambda: None)
    local.put("/api/lan", json={"enabled": True})
    code = local.post("/api/lan/pairing").get_json()["code"]
    for _ in range(lan.PAIR_MAX_FAILS):
        assert local.post("/api/pair", json={"code": "chute"}).status_code == 403
    assert local.post("/api/pair", json={"code": code}).status_code == 403


def test_an_expired_code_is_refused(setup, monkeypatch):
    manager, local, _ = setup
    monkeypatch.setattr(manager, "start", lambda: None)
    local.put("/api/lan", json={"enabled": True})
    code = local.post("/api/lan/pairing").get_json()["code"]
    monkeypatch.setattr(lan, "_now", lambda: time.time() + lan.PAIR_TTL + 1)
    res = local.post("/api/pair", json={"code": code})
    assert res.status_code == 403 and "expirado" in res.get_json()["error"]


def test_a_port_in_use_is_reported(setup):
    manager, local, port = setup
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", port))
        busy.listen()
        state = local.put("/api/lan", json={"enabled": True, "port": port}).get_json()
    assert state["enabled"] is True and state["running"] is False
    assert str(port) in state["error"]
