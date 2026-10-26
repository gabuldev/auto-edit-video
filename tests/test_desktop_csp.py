"""The desktop app's Content-Security-Policy must allow what the UI loads:
the installed app enforces it, a browser serving desktop/ui doesn't — so a
missing source only breaks for people who downloaded the app."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
UI = ROOT / "desktop" / "ui"


def _csp() -> dict[str, list[str]]:
    conf = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    out = {}
    for part in conf["app"]["security"]["csp"].split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


def _ui_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(UI.rglob("*.js")))


def test_blob_images_are_allowed_when_the_ui_makes_them():
    # Estilos previews: fetch → blob → URL.createObjectURL → <img src="blob:…">.
    if "createObjectURL" in _ui_source():
        assert "blob:" in _csp()["img-src"], "img-src must allow blob: (style previews show broken images)"


def test_engine_is_reachable_for_images_and_requests():
    csp = _csp()
    for directive in ("img-src", "connect-src"):
        assert "http://127.0.0.1:8760" in csp[directive]


def test_event_streams_go_to_the_engine():
    if re.search(r"new EventSource\(", _ui_source()):
        assert "http://127.0.0.1:8760" in _csp()["connect-src"]


def test_linux_update_check_reaches_github():
    # Linux (.deb/.rpm) asks GitHub for the latest release from the webview.
    if "api.github.com" in _ui_source():
        assert "https://api.github.com" in _csp()["connect-src"]


def _conf() -> dict:
    return json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))


def test_updater_has_a_real_public_key_and_the_release_endpoint():
    # A placeholder key makes every check fail: nobody would ever see an update.
    up = _conf()["plugins"]["updater"]
    assert up["pubkey"] and "PENDING" not in up["pubkey"]
    assert up["endpoints"] == ["https://github.com/gabuldev/auto-edit-video/releases/latest/download/latest.json"]


def test_update_ui_has_the_permissions_it_calls():
    # window.__TAURI__ exists only with withGlobalTauri; each plugin call needs its permission.
    assert _conf()["app"]["withGlobalTauri"] is True
    caps = json.loads((ROOT / "desktop" / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8"))
    src = (UI / "js" / "update.js").read_text(encoding="utf-8")
    needs = {"T.updater.": "updater:default", "T.process.relaunch": "process:allow-restart", "T.opener.": "opener:default"}
    for call, perm in needs.items():
        if call in src:
            assert perm in caps["permissions"], f"{call} needs {perm}"


def test_release_config_only_turns_on_updater_artifacts():
    rel = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.release.conf.json").read_text(encoding="utf-8"))
    assert rel["bundle"] == {"createUpdaterArtifacts": True}
