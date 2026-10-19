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


def _png(color=(230, 30, 40), size=(64, 36)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class TestGenerate:
    """Estilos → Criar com IA: the agent draws the thumbnail layout (HTML) and
    the tokens, then corrects it comparing its render with the reference."""

    GOOD = {"name": "Choque", "description": "elétrico", "tokens": {
        "colors": {"accent": "#00d6ff", "panel": "#101820", "text": "#ffffff"},
        "fonts": {"title": "luckiest", "text": "poppins"},
        "thumbnail": {"accent_from": "style", "html": "<div><span>{{titulo}}</span></div>"},
    }}
    FIX = json.dumps({"html": '<div><span style="color:red">{{titulo}}</span></div>'})

    @staticmethod
    def fake(answers):
        calls = []

        def run(prompt, images):
            calls.append((prompt, [p.name for p in images]))
            return answers.pop(0)
        return run, calls

    def gen(self, answers, description="tech", image=b"", **kw):
        run, calls = self.fake(list(answers))
        kw.setdefault("render", lambda t: _png())
        kw.setdefault("vision", True)
        out = styles.generate(description, _png() if image == b"" else image, complete=run, **kw)
        return out, calls

    def test_first_answer_then_ok_stops(self, home):
        out, calls = self.gen([json.dumps(self.GOOD), '{"ok": true}'])
        assert out["name"] == "Choque" and "{{titulo}}" in out["tokens"]["thumbnail"]["html"]
        assert out["tokens"]["fonts"]["title"] == "luckiest" and out["tokens"] == styles.validate(out["tokens"])
        assert len(calls) == 2 and calls[0][1] == ["ref.png"] and calls[1][1] == ["ref.png", "render.png"]
        assert not [s for s in styles.list_styles() if not s["builtin"]]  # nothing saved

    def test_prompt_has_the_contract(self, home):
        _, calls = self.gen([json.dumps(self.GOOD), '{"ok": true}'], description="neon roxo")
        p = calls[0][0]
        assert "neon roxo" in p and "{{titulo}}" in p and "Luckiest Guy" in p and "data-fit" in p

    def test_corrected_html_replaces_and_max_rounds(self, home):
        out, calls = self.gen([json.dumps(self.GOOD), self.FIX, self.FIX], rounds=3)
        assert "color:red" in out["tokens"]["thumbnail"]["html"] and len(calls) == 3

    def test_bad_round_keeps_previous(self, home):
        out, _ = self.gen([json.dumps(self.GOOD), "não sei", '{"html": "<script>x</script>"}'])
        assert out["tokens"]["thumbnail"]["html"] == styles.validate(self.GOOD["tokens"])["thumbnail"]["html"]

    def test_json_inside_text_and_fences(self, home):
        out, _ = self.gen([f"Claro! Aqui:\n```json\n{json.dumps(self.GOOD)}\n```\nabraço", '{"ok": true}'])
        assert out["name"] == "Choque"

    def test_answer_without_layout_fails(self, home):
        with pytest.raises(styles.StyleError, match="layout"):
            self.gen(['{"tokens": {"colors": {"accent": "#ff0000"}}}'])
        with pytest.raises(styles.StyleError, match="layout"):
            self.gen(["desculpa, não posso"])
        with pytest.raises(styles.StyleError, match="layout"):
            self.gen(['{"type": "result", "result": "texto"}'])

    def test_render_failure_stops_rounds(self, home):
        def boom(t):
            raise styles.StyleError("x")

        msgs = []
        out, calls = self.gen([json.dumps(self.GOOD)], render=boom, on_progress=msgs.append)
        assert len(calls) == 1 and "html" in out["tokens"]["thumbnail"]
        assert msgs[-1] == "parei de conferir: x"  # the job log says why the rounds stopped

    def test_agent_failure_in_a_round_keeps_the_layout(self, home):
        from auto_edit import agents

        answers = [json.dumps(self.GOOD)]

        def run(prompt, images):
            if answers:
                return answers.pop(0)
            raise agents.AgentError("caiu")

        out = styles.generate("x", _png(), complete=run, render=lambda t: _png(), vision=True)
        assert "html" in out["tokens"]["thumbnail"]

    def test_agent_failure_first_is_a_style_error(self, home):
        from auto_edit import agents

        def boom(p, images):
            raise agents.AgentError("claude: não encontrado")

        with pytest.raises(styles.StyleError, match="a IA falhou"):
            styles.generate("x", None, complete=boom, render=lambda t: _png(), vision=True)

    def test_no_vision_with_image_refuses_and_without_image_skips_rounds(self, home):
        with pytest.raises(styles.StyleError, match="enxerga"):
            self.gen([json.dumps(self.GOOD)], vision=False)
        out, calls = self.gen([json.dumps(self.GOOD)], image=None, vision=False)
        assert len(calls) == 1 and "html" in out["tokens"]["thumbnail"]

    def test_without_image_rounds_see_only_the_render(self, home):
        _, calls = self.gen([json.dumps(self.GOOD), '{"ok": true}'], image=None)
        assert calls[0][1] == [] and calls[1][1] == ["render.png"]

    def test_progress_and_base(self, home):
        msgs = []
        base = styles.validate({"thumbnail": {"html": "<div><span>ANTIGO {{titulo}}</span></div>"}})
        _, calls = self.gen([json.dumps(self.GOOD), '{"ok": true}'], description="título maior", image=None,
                            base=base, on_progress=msgs.append)
        assert "ANTIGO" in calls[0][0] and "título maior" in calls[0][0]
        assert msgs == ["desenhando o layout", "conferindo (volta 2/3)"]

    def test_adjust_merges_partial_answers_into_the_base(self, home):
        base = styles.validate({"colors": {"accent": "#ff0000", "panel": "#111111", "text": "#eeeeee"},
                                "thumbnail": {"accent_from": "style", "html": "<div><span>BASE {{titulo}}</span></div>"}})
        partial = json.dumps({"tokens": {"colors": {"accent": "#00ff00"}, "thumbnail": {"accent_from": "style"}}})
        out, _ = self.gen([partial, '{"ok": true}'], description="verde", image=None, base=base)
        t = out["tokens"]
        assert t["colors"] == {"accent": "#00ff00", "panel": "#111111", "text": "#eeeeee"}
        assert "BASE" in t["thumbnail"]["html"] and t["thumbnail"]["accent_from"] == "style"

    def test_needs_description_or_image(self, home):
        with pytest.raises(styles.StyleError, match="descreva"):
            self.gen([json.dumps(self.GOOD)], description="   ", image=None)

    def test_unreadable_image_is_a_style_error(self, home):
        with pytest.raises(styles.StyleError, match="imagem"):
            self.gen([json.dumps(self.GOOD)], image=b"lixo")


class TestShare:
    """Export a style to a file and import it elsewhere — never the brand."""

    def test_round_trip(self, home):
        mine = styles.save("Meu Neon", {"colors": {"accent": "#ff00aa"}, "radius": 4}, description="rosa")
        data = styles.export(mine["id"])
        assert data == {"format": 1, "name": "Meu Neon", "description": "rosa", "tokens": mine["tokens"]}
        assert "brand" not in json.dumps(data) and "logo" not in json.dumps(data)
        styles.delete(mine["id"])
        back = styles.import_(json.loads(json.dumps(data)))
        assert back["name"] == "Meu Neon" and back["tokens"] == mine["tokens"] and not back["builtin"]

    def test_presets_export_too(self, home):
        assert styles.export("neon")["tokens"] == styles.get("neon")["tokens"]

    def test_unknown_style(self, home):
        with pytest.raises(styles.StyleError):
            styles.export("nao-existe")

    @pytest.mark.parametrize("data", [None, [], {"tokens": {}}, {"format": 2, "tokens": {}}, {"format": 1, "tokens": "x"}])
    def test_not_a_style_file(self, home, data):
        with pytest.raises(styles.StyleError, match="arquivo não é um estilo do Auto-Edit"):
            styles.import_(data)

    def test_import_never_overwrites(self, home):
        first = styles.save("Neon", {"colors": {"accent": "#111111"}})
        imported = styles.import_({"format": 1, "name": "Neon", "tokens": {"colors": {"accent": "#222222"}}})
        assert imported["id"] != first["id"] and imported["name"] == "Neon (2)"
        assert styles.get(first["id"])["tokens"]["colors"]["accent"] == "#111111"

    def test_import_junk_tokens_are_validated(self, home):
        s = styles.import_({"format": 1, "name": "", "tokens": {"radius": 9999}})
        assert s["name"] == "Estilo importado" and s["tokens"]["radius"] == 60

    def test_export_file_is_unique_in_the_folder(self, home, tmp_path):
        a = styles.export_file("neon", tmp_path)
        b = styles.export_file("neon", tmp_path)
        assert a.name == "neon.autoedit-style.json" and b.name == "neon-2.autoedit-style.json"
        assert json.loads(a.read_text(encoding="utf-8"))["format"] == 1


class TestStyleApi:
    @pytest.fixture
    def client(self, home):
        pytest.importorskip("flask")
        return api.create_app(engine.JobManager()).test_client()

    @staticmethod
    def _data_url(rgb=(230, 30, 40)) -> str:
        import base64
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (16, 16), rgb).save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _events(client, job_id) -> list[dict]:
        body = client.get(f"/api/jobs/{job_id}/events").get_data(as_text=True)
        return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

    def test_generate_is_a_job_with_progress(self, client, monkeypatch):
        seen = {}

        def gen(d, image=None, *, base=None, on_progress=None):
            seen.update(d=d, image=image, base=base)
            on_progress("desenhando o layout")
            return {"name": "X", "description": d, "tokens": styles.validate({})}

        monkeypatch.setattr(styles, "generate", gen)
        r = client.post("/api/styles/generate", json={"description": "neon", "image": self._data_url()})
        assert r.status_code == 202
        ev = self._events(client, r.get_json()["job_id"])
        assert ev[0] == {"type": "progress", "message": "desenhando o layout"}
        assert ev[-1]["type"] == "done" and ev[-1]["result"]["description"] == "neon"
        assert seen["image"][:4] == b"\x89PNG" and seen["base"] is None

    def test_generate_error_is_an_error_event(self, client, monkeypatch):
        def boom(d, image=None, **kw):
            raise styles.StyleError("a IA falhou: x")

        monkeypatch.setattr(styles, "generate", boom)
        r = client.post("/api/styles/generate", json={"description": "neon"})
        ev = self._events(client, r.get_json()["job_id"])
        assert ev[-1] == {"type": "error", "message": "a IA falhou: x"}

    def test_adjust_passes_the_style(self, client, monkeypatch):
        seen = {}
        monkeypatch.setattr(styles, "generate", lambda d, image=None, *, base=None, on_progress=None: seen.update(d=d, base=base) or {"name": "", "description": "", "tokens": base})
        tokens = styles.validate({"radius": 3})
        r = client.post("/api/styles/adjust", json={"tokens": tokens, "request": "título maior"})
        assert r.status_code == 202
        assert self._events(client, r.get_json()["job_id"])[-1]["type"] == "done"
        assert seen == {"d": "título maior", "base": tokens}

    @pytest.mark.parametrize("path,body", [
        ("generate", []), ("generate", {"description": 3}), ("adjust", {"tokens": [], "request": "x"}),
        ("adjust", {"tokens": {}, "request": None}), ("adjust", {"tokens": {}, "request": "   "}),
    ])
    def test_bad_bodies_are_400(self, client, path, body):
        assert client.post(f"/api/styles/{path}", json=body).status_code == 400

    def test_list_says_if_the_ai_sees_images(self, client, monkeypatch):
        from auto_edit import agents

        monkeypatch.setattr(agents, "vision_ready", lambda env=None: False)
        assert client.get("/api/styles").get_json()["ai_vision"] is False

    def test_style_jobs_are_not_video_jobs(self, monkeypatch):
        jobs = engine.JobManager()
        job = jobs.run_task("style", lambda emit: emit({"type": "done", "status": "done"}))
        for _ in range(100):
            if job.status != "running":
                break
            __import__("time").sleep(0.01)
        assert job.status == "done" and jobs.get(job.id) is job and not jobs.active_ids() and not jobs.failed_ids()

    def test_generate_bad_data_url_is_400(self, client):
        r = client.post("/api/styles/generate", json={"description": "x", "image": "data:text/plain;base64,aGk="})
        assert r.status_code == 400

    def test_palette_from_image(self, client):
        r = client.post("/api/styles/palette", json={"image": self._data_url()})
        body = r.get_json()
        assert r.status_code == 200 and body["colors"] and body["suggested"]["accent"] == body["colors"][0]

    def test_palette_from_saved_logo(self, client):
        from auto_edit import render

        render.save_logo(self._data_url((0, 200, 120)))
        body = client.post("/api/styles/palette", json={}).get_json()
        assert body["colors"]

    def test_palette_without_logo_or_image_is_400(self, client):
        assert client.post("/api/styles/palette", json={}).status_code == 400

    def test_palette_gray_has_no_suggestion(self, client):
        body = client.post("/api/styles/palette", json={"image": self._data_url((128, 128, 128))}).get_json()
        assert body == {"colors": [], "suggested": None}

    def test_palette_bad_image_is_400(self, client):
        import base64

        r = client.post("/api/styles/palette", json={"image": "data:image/png;base64," + base64.b64encode(b"nope").decode()})
        assert r.status_code == 400

    def test_export_writes_and_reveals(self, client, monkeypatch, tmp_path):
        opened = []
        monkeypatch.setattr(engine, "downloads_dir", lambda: tmp_path)
        monkeypatch.setattr(engine, "os_open", lambda path, reveal=False, run=None: opened.append((path, reveal)))
        r = client.post("/api/styles/neon/export")
        path = r.get_json()["path"]
        assert r.status_code == 200 and json.loads(open(path, encoding="utf-8").read())["format"] == 1
        assert opened and opened[0][1] is True

    def test_export_unknown_is_404(self, client):
        assert client.post("/api/styles/nada/export").status_code == 404

    def test_import(self, client):
        r = client.post("/api/styles/import", json={"file": styles.export("neon")})
        assert r.status_code == 200 and r.get_json()["builtin"] is False

    def test_import_bad_file_is_400(self, client):
        r = client.post("/api/styles/import", json={"file": {"nope": 1}})
        assert r.status_code == 400 and "não é um estilo" in r.get_json()["error"]


class TestStyleCli:
    @pytest.fixture
    def run(self, home):
        from typer.testing import CliRunner

        from auto_edit.cli import app

        return lambda *args: CliRunner().invoke(app, ["style", *args])

    def test_generate_prints_and_saves(self, run, monkeypatch):
        monkeypatch.setattr(styles, "generate", lambda d, image=None, **kw: {"name": "Roxo", "description": d, "tokens": styles.validate({})})
        r = run("generate", "tech roxo", "--save", "--activate")
        assert r.exit_code == 0, r.output
        saved = [s for s in styles.list_styles() if not s["builtin"]]
        assert saved and saved[0]["name"] == "Roxo" and styles.active_id() == saved[0]["id"]

    def test_generate_without_save_saves_nothing(self, run, monkeypatch):
        monkeypatch.setattr(styles, "generate", lambda d, image=None, **kw: {"name": "Roxo", "description": d, "tokens": styles.validate({})})
        r = run("generate", "tech roxo")
        assert r.exit_code == 0 and '"accent"' in r.output
        assert not [s for s in styles.list_styles() if not s["builtin"]]

    def test_generate_passes_rounds_and_shows_progress(self, run, monkeypatch):
        seen = {}

        def gen(d, image=None, *, rounds=3, on_progress=None, base=None):
            seen.update(rounds=rounds)
            on_progress("desenhando o layout")
            return {"name": "Roxo", "description": d, "tokens": styles.validate({})}

        monkeypatch.setattr(styles, "generate", gen)
        r = run("generate", "x", "--rounds", "1")
        assert r.exit_code == 0 and seen["rounds"] == 1 and "desenhando o layout" in r.output

    def test_adjust_saves_a_new_style_from_the_old_one(self, run, monkeypatch):
        old = styles.save("Meu", {"radius": 3})
        seen = {}

        def gen(d, image=None, *, base=None, rounds=3, on_progress=None):
            seen.update(d=d, base=base)
            return {"name": "Outro", "description": "", "tokens": {**base, "radius": 9}}

        monkeypatch.setattr(styles, "generate", gen)
        r = run("adjust", old["id"], "título maior", "--activate")
        assert r.exit_code == 0, r.output
        assert seen == {"d": "título maior", "base": old["tokens"]}
        new = next(s for s in styles.list_styles() if s["name"] == "Meu (ajustado)")
        assert new["tokens"]["radius"] == 9 and styles.active_id() == new["id"]
        assert styles.get(old["id"])["tokens"]["radius"] == 3

    def test_adjust_unknown_style_exits_1(self, run):
        assert run("adjust", "nao-existe", "x").exit_code == 1

    def test_generate_error_exits_1(self, run, monkeypatch):
        def boom(d, image=None, **kw):
            raise styles.StyleError("a IA falhou: x")

        monkeypatch.setattr(styles, "generate", boom)
        r = run("generate", "x")
        assert r.exit_code == 1 and "a IA falhou" in r.output

    def test_export_then_import(self, run, tmp_path):
        out = tmp_path / "neon.autoedit-style.json"
        assert run("export", "neon", "-o", str(out)).exit_code == 0
        r = run("import", str(out))
        assert r.exit_code == 0, r.output
        assert any(s["name"] == "Neon (2)" for s in styles.list_styles())

    def test_import_bad_file_exits_1(self, run, tmp_path):
        bad = tmp_path / "x.json"
        bad.write_text("{nope", encoding="utf-8")
        r = run("import", str(bad))
        assert r.exit_code == 1 and "não é um estilo" in r.output


class TestDisplayFonts:
    @pytest.mark.parametrize("fid", ["luckiest", "lilita", "bangers", "archivo"])
    def test_new_display_fonts_ship_with_the_app(self, fid):
        assert styles.font_file(styles.FONTS[fid]["bold"]) is not None


class TestThumbnailHtml:
    def test_html_survives_validate(self):
        t = styles.validate({"thumbnail": {"html": "<div><span>{{titulo}}</span></div>"}})
        assert "{{titulo}}" in t["thumbnail"]["html"]

    def test_bad_html_is_dropped(self):
        assert "html" not in styles.validate({"thumbnail": {"html": "<script>x</script>"}})["thumbnail"]

    def test_import_sanitizes(self, home):
        s = styles.import_({"format": 1, "name": "X", "tokens": {"thumbnail": {
            "html": '<div><img src="http://a/b.png"/><span>{{titulo}}</span></div>'}}})
        assert "http" not in s["tokens"]["thumbnail"]["html"]


class TestHtmlSpec:
    def test_values_images_and_fonts(self):
        t = styles.validate({"fonts": {"title": "bangers"}, "thumbnail": {"html": "<div><span>{{titulo}}</span></div>"}})
        spec = styles.html_spec(t, title="Montei uma impressora", sub="DIY", accent=[255, 0, 0], images={"frame": "/f.jpg"})
        assert spec["html"] == t["thumbnail"]["html"]
        assert spec["values"]["titulo_fim"] == "impressora" and spec["values"]["titulo_inicio"] == "Montei uma"
        assert spec["values"]["etiqueta"] == "DIY"
        assert spec["values"]["destaque"] == "#ff0000" and spec["values"]["cor.panel"] == t["colors"]["panel"]
        assert spec["fonts"][0]["name"] == "Bangers"
        assert {f["name"] for f in spec["fonts"]} >= {"Anton", "Luckiest Guy", "Montserrat"}
        assert spec["images"] == {"frame": "/f.jpg", "frame2": None, "rosto": None, "rosto_contorno": None, "logo": None}

    def test_preview_reports_invalid_layout(self, home):
        with pytest.raises(styles.StyleError, match="layout"):
            styles.preview({"thumbnail": {"html": "<script>x</script>"}}, "thumbnail")

    def test_sample_texts_without_videos(self, home, monkeypatch):
        monkeypatch.setattr(engine, "library_root", lambda: home / "nada")
        assert styles.sample_texts() == ("SEU TÍTULO AQUI", None)

    def test_sample_texts_from_the_newest_video(self, home, monkeypatch, tmp_path):
        ws = tmp_path / "lib" / "v1"
        ws.mkdir(parents=True)
        (ws / "metadata.json").write_text(json.dumps({"thumbnail": {"main_text": "Meu título", "sub_text": "Novo"}}))
        monkeypatch.setattr(engine, "library_root", lambda: tmp_path / "lib")
        assert styles.sample_texts() == ("Meu título", "Novo")

    @pytest.mark.skipif(__import__("auto_edit.render", fromlist=["x"]).command() is None, reason="renderer not available")
    def test_renders_html_png(self, home):
        t = styles.validate({"thumbnail": {"html": '<div style="background:{{cor.panel}}"><span data-fit="linhas:2;min:40;max:150" style="width:1000px;color:#fff">{{titulo}}</span></div>'}})
        assert styles.render_thumbnail(t)[:4] == b"\x89PNG"


class TestPreviewFace:
    """The Estilos preview cuts the person out of the newest video's frames;
    while the model downloads, it shows the layout without the face."""

    def test_model_missing_starts_the_download_and_skips(self, home, monkeypatch):
        from auto_edit import face_cutout

        started = []
        monkeypatch.setattr(face_cutout, "model_ready", lambda: False)
        monkeypatch.setattr(face_cutout, "download_in_background", lambda: started.append(1))
        monkeypatch.setattr(face_cutout, "cutout_files", lambda *a: pytest.fail("cut without the model"))
        assert styles.preview_face() is None and started == [1]

    def test_cuts_from_several_frames(self, home, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        frames = {a: tmp_path / f"{a}.jpg" for a in (0.2, 0.4, 0.6, 0.8)}
        monkeypatch.setattr(styles, "preview_frame", lambda at=0.3: frames.get(at))
        monkeypatch.setattr(face_cutout, "model_ready", lambda: True)
        seen = {}
        monkeypatch.setattr(face_cutout, "cutout_files", lambda fs, folder: seen.update(fs=fs) or {"rosto": "r", "rosto_contorno": "c"})
        assert styles.preview_face() == {"rosto": "r", "rosto_contorno": "c"}
        assert seen["fs"] == list(frames.values())

    def test_cutout_error_is_no_face(self, home, monkeypatch, tmp_path):
        from auto_edit import face_cutout

        monkeypatch.setattr(styles, "preview_frame", lambda at=0.3: tmp_path / "f.jpg")
        monkeypatch.setattr(face_cutout, "model_ready", lambda: True)

        def boom(*a):
            raise face_cutout.CutoutError("x")

        monkeypatch.setattr(face_cutout, "cutout_files", boom)
        assert styles.preview_face() is None


class TestPreviewCache:
    @pytest.mark.skipif(sys.platform == "win32", reason="shebang fake")
    def test_new_renderer_means_new_previews(self, home, monkeypatch, tmp_path):
        """A cached preview from an older renderer is never shown after an update."""
        from auto_edit import render

        exe = tmp_path / "auto-edit-render"
        exe.write_text(f"#!{sys.executable}\nimport sys\nopen(sys.argv[3], 'wb').write(b'PNG-1')\n")
        exe.chmod(0o755)
        monkeypatch.setenv("AUTO_EDIT_RENDER_BIN", str(exe))
        monkeypatch.setattr(styles, "preview_frame", lambda at=0.3: None)
        first = styles.preview({}, "thumbnail")
        exe.write_text(f"#!{sys.executable}\nimport sys\nopen(sys.argv[3], 'wb').write(b'PNG-2')\n")
        import os
        st = exe.stat()
        os.utime(exe, (st.st_atime, st.st_mtime + 10))
        assert first == b"PNG-1" and styles.preview({}, "thumbnail") == b"PNG-2"
        assert render.stamp()  # something that changes with the renderer


class TestGalleryPresets:
    """The ready-made thumbnail layouts (auto_edit/style_presets.py)."""

    def test_every_layout_is_a_preset(self):
        from auto_edit import style_presets

        for sid in style_presets.LAYOUTS:
            assert styles.PRESETS[sid]["tokens"]["thumbnail"]["html"] == style_presets.LAYOUTS[sid]
        assert {"padrao", "minimal", "neon", "impacto"} <= set(styles.PRESETS)

    def test_sanitizing_keeps_every_placeholder_and_declaration(self):
        import re

        from auto_edit import style_presets, thumb_html

        def decls(h):
            return sorted(d.strip() for s in re.findall(r'style="([^"]*)"', h) for d in s.split(";") if d.strip())

        for sid, html in style_presets.LAYOUTS.items():
            clean = thumb_html.sanitize(html)
            assert thumb_html.placeholders(clean) == thumb_html.placeholders(html), sid
            assert decls(clean) == decls(html.replace("&", "&amp;")), sid

    def test_title_follows_the_style_font(self):
        import re

        from auto_edit import style_presets

        for sid, html in style_presets.LAYOUTS.items():
            fits = re.findall(r'data-fit="[^"]*" style="([^"]*)"', html)
            assert fits, sid
            assert not any("font-family" in s for s in fits), sid
            assert styles.PRESETS[sid]["tokens"]["fonts"]["title"] in styles.FONTS

    @pytest.mark.skipif(__import__("auto_edit.render", fromlist=["x"]).command() is None, reason="renderer not available")
    @pytest.mark.parametrize("title,sub", [("IA", None), ("Criei a IA da minha startup em sete dias sem programar", "Sem esforço")])
    def test_renders_short_and_long_titles_without_a_person(self, home, monkeypatch, title, sub):
        from auto_edit import style_presets

        monkeypatch.setattr(styles, "preview_frame", lambda at=0.3: None)
        monkeypatch.setattr(styles, "preview_face", lambda: None)
        for sid in style_presets.LAYOUTS:
            assert styles.render_thumbnail(styles.PRESETS[sid]["tokens"], title=title, sub=sub)[:4] == b"\x89PNG", sid
