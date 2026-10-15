"""Styles: tokens are validated into something that always renders, presets
and the person's own styles, the active one, the preview and the API."""
import json
import sys

import pytest

from auto_edit import api, engine, settings, styles


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


class TestValidate:
    def test_empty_is_the_default(self):
        assert styles.validate({}) == styles.validate(None) == styles.DEFAULT_TOKENS

    def test_bad_values_fall_back_one_by_one(self):
        t = styles.validate({
            "colors": {"accent": "azul", "panel": "#ABCDEF", "text": 3},
            "radius": 999, "panel_opacity": "x", "speed": 0.1,
            "fonts": {"title": "comic-sans", "text": "poppins"},
            "lower_third": {"position": "middle"},
            "cta": {"position": "top-right", "steps": [{"icon": "?", "text": "  COMENTA  "}, {"text": ""}, "x"]},
            "thumbnail": {"accent_from": "whatever"},
        })
        assert t["colors"] == {"accent": "#00d6ff", "panel": "#abcdef", "text": "#ffffff"}
        assert t["radius"] == 60 and t["panel_opacity"] == 1.0 and t["speed"] == 0.5
        assert t["fonts"] == {"title": "anton", "text": "poppins"}
        assert t["lower_third"]["position"] == "bottom-left"
        assert t["cta"] == {"position": "top-right", "steps": [{"icon": "subscribe", "text": "COMENTA", "color": None}]}
        assert t["thumbnail"]["accent_from"] == "topic"

    def test_at_most_three_short_steps(self):
        steps = styles.validate({"cta": {"steps": [{"icon": "like", "text": "x" * 60}] * 5}})["cta"]["steps"]
        assert len(steps) == 3 and len(steps[0]["text"]) == 24

    def test_every_preset_is_valid_and_has_its_fonts(self):
        for sid, p in styles.PRESETS.items():
            assert styles.validate(p["tokens"]) == p["tokens"], sid
            assert styles.title_font(p["tokens"]) is not None, sid
            styles.overlay_fonts(p["tokens"])  # raises when a file is missing


class TestThumbnailAccent:
    def test_topic_keeps_the_template_color(self):
        assert styles.thumbnail_accent(styles.validate({}), [1, 2, 3]) == [1, 2, 3]

    def test_style_uses_its_own(self):
        t = styles.validate({"colors": {"accent": "#ff0000"}, "thumbnail": {"accent_from": "style"}})
        assert styles.thumbnail_accent(t, [1, 2, 3]) == [255, 0, 0]


class TestStorage:
    def test_presets_listed_and_padrao_active_by_default(self, home):
        ids = [s["id"] for s in styles.list_styles()]
        assert ids[:4] == ["padrao", "minimal", "neon", "impacto"]
        assert styles.active_id() == "padrao"

    def test_save_activate_and_delete(self, home):
        s = styles.save("Meu Estilo!", {"colors": {"accent": "#123456"}})
        assert s["id"] == "meu-estilo" and not s["builtin"]
        assert s["tokens"]["colors"]["accent"] == "#123456"
        styles.set_active(s["id"])
        assert styles.active()["id"] == "meu-estilo"
        styles.delete("meu-estilo")
        assert styles.active_id() == "padrao" and styles.get("meu-estilo") is None

    def test_saving_over_a_preset_makes_a_copy(self, home):
        s = styles.save("Neon", {}, "neon")
        assert s["id"] == "neon-2"
        assert styles.get("neon")["builtin"]

    def test_update_keeps_the_id(self, home):
        s = styles.save("A", {})
        assert styles.save("A renamed", {"radius": 5}, s["id"])["id"] == s["id"]

    def test_presets_cannot_be_deleted(self, home):
        with pytest.raises(styles.StyleError):
            styles.delete("padrao")

    def test_ids_are_not_paths(self, home):
        with pytest.raises(styles.StyleError):
            styles.delete("../settings")

    def test_a_deleted_active_style_falls_back(self, home):
        settings.save({"style": "sumiu"})
        assert styles.active_id() == "padrao"

    def test_broken_file_is_skipped(self, home):
        styles.user_dir().mkdir(parents=True)
        (styles.user_dir() / "quebrado.json").write_text("{nope")
        assert styles.get("quebrado") is None


@pytest.mark.skipif(sys.platform == "win32", reason="shell script renderer")
class TestPreview:
    @pytest.fixture
    def fake(self, tmp_path, home, monkeypatch):
        exe = tmp_path / "auto-edit-render"
        exe.write_text("#!/bin/sh\necho \"$@\" >> \"" + str(tmp_path / "calls") + "\"\ncp \"$2\" \"" + str(tmp_path / "spec.json") + "\"\nprintf PNG > \"$3\"\n")
        exe.chmod(0o755)
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
        monkeypatch.setattr(styles, "preview_frame", lambda: None)
        return tmp_path

    def test_overlay_preview_gets_tokens_brand_and_fonts(self, fake):
        assert styles.preview({"colors": {"accent": "#ff0000"}}, "cta") == b"PNG"
        spec = json.loads((fake / "spec.json").read_text())
        assert spec["kind"] == "cta" and spec["style"]["colors"]["accent"] == "#ff0000"
        assert set(spec["fonts"]) == {"Bold", "Regular"} and "brand" in spec

    def test_thumbnail_preview_uses_the_title_font(self, fake):
        styles.preview({"fonts": {"title": "bebas"}}, "thumbnail")
        spec = json.loads((fake / "spec.json").read_text())
        assert spec["kind"] == "thumbnail" and spec["font"].endswith("BebasNeue-Regular.ttf")

    def test_cached(self, fake):
        styles.preview({}, "lower_third")
        styles.preview({}, "lower_third")
        assert len((fake / "calls").read_text().splitlines()) == 1

    def test_unknown_kind(self, fake):
        with pytest.raises(styles.StyleError):
            styles.preview({}, "intro")


class TestApi:
    def _client(self):
        pytest.importorskip("flask")
        return api.create_app(engine.JobManager()).test_client()

    def test_list_save_activate_delete(self, home):
        c = self._client()
        data = c.get("/api/styles").get_json()
        assert data["active"] == "padrao" and {"id": "bebas", "label": "Bebas Neue"} in data["fonts"]
        saved = c.post("/api/styles", json={"name": "Teste", "tokens": {"radius": 3}, "activate": True}).get_json()
        assert saved["tokens"]["radius"] == 3
        assert c.get("/api/styles").get_json()["active"] == saved["id"]
        assert c.delete(f"/api/styles/{saved['id']}").get_json()["active"] == "padrao"

    def test_errors_are_400(self, home):
        c = self._client()
        assert c.post("/api/styles", json={"name": ""}).status_code == 400
        assert c.put("/api/styles/active", json={"id": "nope"}).status_code == 400
        assert c.delete("/api/styles/padrao").status_code == 400
        assert c.post("/api/styles/preview/intro", json={}).status_code == 400

    def test_logo(self, home):
        import base64
        c = self._client()
        data = "data:image/png;base64," + base64.b64encode(b"\x89PNGfake").decode()
        assert c.put("/api/brand/logo", json={"data": data}).get_json()["logo"].endswith("logo.png")
        assert c.get("/api/brand/logo").data == b"\x89PNGfake"
        assert c.delete("/api/brand/logo").get_json()["logo"] is None
        assert c.put("/api/brand/logo", json={"data": "oi"}).status_code == 400
