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
