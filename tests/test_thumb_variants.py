"""A/B/C thumbnails for YouTube's Testar e comparar (tools/thumbnailer.py +
auto_edit/thumb_variants.py), the object-aware second frame of a maker video,
and the delivery of the variations."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import thumbnailer  # noqa: E402

from auto_edit import engine, thumb_html, thumb_qa  # noqa: E402
from auto_edit import pipeline as pl  # noqa: E402
from auto_edit import thumb_variants as tv  # noqa: E402


def _frame(path: Path, colour=(90, 90, 90)) -> Path:
    Image.new("RGB", (1280, 720), colour).save(path)
    return path


def _face(path: Path) -> Path:
    im = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((50, 50, 350, 450), fill=(200, 150, 120, 255))
    im.save(path)
    return path


# ── thumb_variants: layouts and records ─────────────────────────────────────

class TestLayouts:
    @pytest.mark.parametrize("vid", ["B", "C"])
    def test_layout_passes_the_html_sanitizer(self, vid):
        # the same format the styles use: thumb_html.clean must keep it intact
        html = tv.LAYOUTS[vid]
        assert thumb_html.sanitize(html) == html

    def test_b_has_the_face_and_the_title(self):
        slots = thumb_html.placeholders(tv.LAYOUT_B)
        assert {"rosto_contorno", "titulo", "frame"} <= slots

    def test_c_puts_the_second_frame_big_and_the_face(self):
        slots = thumb_html.placeholders(tv.LAYOUT_C)
        assert {"frame2", "rosto_contorno", "titulo"} <= slots

    @pytest.mark.parametrize("vid", ["B", "C"])
    def test_title_never_fits_below_the_fixed_hero_size(self, vid):
        # data-fit min = the Pillow layout's fixed size: below it = shrunk → QA fails
        assert f"min:{tv.HERO_MIN};" in tv.LAYOUTS[vid]
        assert tv.HERO_MIN == int(thumbnailer.LONG_SIZE[0] * thumbnailer.HERO_SIZE_FRAC)


class TestRecords:
    def test_file_names_keep_a_unchanged(self):
        assert tv.file_name("A") == "thumbnail.png"
        assert tv.file_name("B") == "thumbnail_b.png"
        assert tv.qa_stem("A") == "thumbnail" and tv.qa_stem("C") == "thumbnail_c"
        assert tv.delivered_name("meu", "B") == "meu_thumbnail_b.png"

    def test_entry(self):
        assert tv.entry("B", {"approved": False, "reasons": ["x"]}) == {
            "id": "B", "layout": tv.LABELS["B"], "file": "thumbnail_b.png", "qa": "reprovada", "qa_reasons": ["x"]}
        assert tv.entry("C", {"approved": None})["qa"] == "parcial"
        assert tv.entry("C", skipped="sem frame") == {"id": "C", "layout": tv.LABELS["C"], "skipped": "sem frame"}

    def test_txt_lists_only_when_there_is_something_to_compare(self):
        meta = {"thumbnail_variants": [tv.entry("A", {"approved": True}), tv.entry("B", skipped="x")]}
        assert tv.txt_lines(meta, "v") == []
        meta["thumbnail_variants"].append(tv.entry("C", {"approved": None}))
        lines = tv.txt_lines(meta, "v")
        assert any("v_thumbnail.png" in ln for ln in lines)
        assert any("v_thumbnail_c.png" in ln and "parcial" in ln for ln in lines)
        assert not any("thumbnail_b" in ln for ln in lines)


# ── on/off ──────────────────────────────────────────────────────────────────

class TestVariantsEnabled:
    def test_long_makes_them_by_default(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_THUMB_VARIANTS", raising=False)
        assert thumbnailer.variants_enabled({"type": "long"})

    @pytest.mark.parametrize("value", ["0", "off", "a", "false"])
    def test_env_makes_only_a(self, monkeypatch, value):
        monkeypatch.setenv("AUTO_EDIT_THUMB_VARIANTS", value)
        assert not thumbnailer.variants_enabled({"type": "long"})

    def test_cli_flag_is_kept_in_pipeline(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AUTO_EDIT_THUMB_VARIANTS", raising=False)
        video = tmp_path / "v.mp4"
        video.write_text("")
        ws = tmp_path / "ws"
        ws.mkdir()
        pl.init(ws, video, "long", "c")
        pl.set_thumb_variants(ws, False)
        assert not thumbnailer.variants_enabled(pl.load(ws))

    def test_short_never(self, monkeypatch):
        monkeypatch.delenv("AUTO_EDIT_THUMB_VARIANTS", raising=False)
        assert not thumbnailer.variants_enabled({"type": "short"})


# ── drawing B and C ─────────────────────────────────────────────────────────

class TestRenderVariants:
    def _args(self, tmp_path, face=True, frame2=True):
        return {
            "main_text": "AMS CASEIRO", "sub_text": None, "template": {"accent": [255, 159, 46]},
            "frame": _frame(tmp_path / "main.jpg"),
            "frame2": _frame(tmp_path / "obj.jpg", (30, 120, 200)) if frame2 else None,
            "face": {"rosto": _face(tmp_path / "f.png"), "rosto_contorno": _face(tmp_path / "fo.png")} if face else None,
        }

    def test_pillow_draws_both_mirrored_b_and_smaller_face_c(self, monkeypatch, tmp_path):
        monkeypatch.setattr(thumbnailer, "_render_react", lambda *a, **kw: False)
        out = thumbnailer._render_variants(tmp_path, **self._args(tmp_path))
        b, c = out["B"], out["C"]
        assert b["path"].exists() and c["path"].exists()
        with Image.open(b["path"]) as im:
            assert im.size == thumbnailer.LONG_SIZE
        # B: face on the LEFT (the mirror of A), text on the right, clear of it
        fb = b["qa_hints"]["face_box"]
        assert fb[0] == 0
        assert b["qa_hints"]["text_box"][0] > fb[2] - 200
        # C: the face is smaller than B's
        fc = c["qa_hints"]["face_box"]
        assert (fc[3] - fc[1]) < (fb[3] - fb[1])
        # the hints are enough for every QA check (Pillow knows where it drew)
        rep = thumb_qa.evaluate("AMS CASEIRO", **c["qa_hints"])
        assert all(v is not None for v in rep["checks"].values())

    def test_react_gets_each_layout_and_c_gets_the_object_frame(self, monkeypatch, tmp_path):
        calls = []

        def react(spec, output, qa_out=None, html=None):
            calls.append((html, spec))
            output.write_bytes(b"PNG")
            qa_out.update(text_fits=True)
            return True

        monkeypatch.setattr(thumbnailer, "_render_react", react)
        args = self._args(tmp_path)
        out = thumbnailer._render_variants(tmp_path, **args)
        assert [c[0] for c in calls] == [tv.LAYOUT_B, tv.LAYOUT_C]
        assert calls[1][1]["frame2"] == str(args["frame2"])
        assert calls[0][1]["face_outline"] == str(args["face"]["rosto_contorno"])
        assert out["B"]["qa_hints"] == {"text_fits": True}

    def test_b_is_skipped_without_a_face_c_without_a_second_frame(self, monkeypatch, tmp_path):
        monkeypatch.setattr(thumbnailer, "_render_react", lambda *a, **kw: False)
        (tmp_path / "thumbnail_b.png").write_bytes(b"old")  # from an earlier run
        out = thumbnailer._render_variants(tmp_path, **self._args(tmp_path, face=False, frame2=False))
        assert "rosto" in out["B"]["skipped"] and "segundo frame" in out["C"]["skipped"]
        assert not (tmp_path / "thumbnail_b.png").exists()  # never deliver a stale one


class TestLongWithVariants:
    """A stays exactly as before; B/C get the frames and the face."""

    def _setup(self, monkeypatch, tmp_path, html=None):
        main = _frame(tmp_path / "_main.jpg")
        second = _frame(tmp_path / "_second.jpg", (10, 200, 10))
        monkeypatch.setattr(thumbnailer, "_generate_imagen_bg", lambda *a: None)
        monkeypatch.setattr(thumbnailer, "_find_face_asset", lambda: None)
        monkeypatch.setattr(thumbnailer, "_frame_source", lambda ws, p: ("v.mp4", {"duration": 100.0}))
        monkeypatch.setattr(thumbnailer, "_pick_best_frame", lambda *a, **kw: (main, 30.0) if kw.get("with_ts") else main)
        seen = {"maker": []}
        monkeypatch.setattr(thumbnailer, "_pick_second_frame",
                            lambda v, d, ws, ts, maker=False: seen["maker"].append(maker) or second)
        monkeypatch.setattr(thumbnailer, "_style_html", lambda: html)
        cut_calls = []

        def cutout(frame, ws, video, dur, force=False):
            cut_calls.append(force)
            return {"rosto": _face(tmp_path / "c.png"), "rosto_contorno": _face(tmp_path / "co.png")} if force else None

        monkeypatch.setattr(thumbnailer, "_face_cutout", cutout)
        specs = []

        def react(spec, output, qa_out=None, html=None):
            specs.append((html, spec))
            output.write_bytes(b"PNG")
            return True

        monkeypatch.setattr(thumbnailer, "_render_react", react)
        return seen, cut_calls, specs, second

    def test_a_spec_is_unchanged_and_bc_are_made(self, monkeypatch, tmp_path):
        seen, cut_calls, specs, second = self._setup(monkeypatch, tmp_path)
        variants: dict = {}
        meta = {"thumbnail": {"main_text": "AMS CASEIRO", "template": "maker"}}
        thumbnailer._thumbnail_long(tmp_path, meta, {"context": "impressora 3D"}, variants=variants)
        a = specs[0]
        assert a[0] is None  # A: the style's / default layout, as always
        assert a[1]["frame2"] is None and a[1]["face"] is None  # style uses neither
        assert [s[0] for s in specs[1:]] == [tv.LAYOUT_B, tv.LAYOUT_C]
        assert seen["maker"] == [True]  # maker video → the object-aware pick
        assert cut_calls == [False, True]  # A asks as before (style decides); forced only for B/C
        assert set(variants) == {"B", "C"} and not second.exists()

    def test_without_variants_only_a_and_no_second_frame(self, monkeypatch, tmp_path):
        seen, cut_calls, specs, _ = self._setup(monkeypatch, tmp_path)
        thumbnailer._thumbnail_long(tmp_path, {"thumbnail": {"main_text": "T"}}, {})
        assert len(specs) == 1 and seen["maker"] == [] and cut_calls == [False]


# ── the stage entry: QA of each, metadata, strict ───────────────────────────

class TestEntryPoint:
    def _ws(self, monkeypatch, tmp_path, b_fails=False):
        (tmp_path / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c"}))
        (tmp_path / "metadata.json").write_text(json.dumps(
            {"youtube_title": "t", "thumbnail": {"main_text": "AMS CASEIRO"}}), encoding="utf-8")

        def fake_long(workspace, metadata, pipeline, qa_out=None, variants=None):
            out = workspace / "thumbnail.png"
            Image.new("RGB", thumbnailer.LONG_SIZE).save(out)
            qa_out.update(text_fits=True)
            if variants is not None:
                for vid in ("B", "C"):
                    p = workspace / tv.file_name(vid)
                    Image.new("RGB", thumbnailer.LONG_SIZE).save(p)
                    fits = not (b_fails and vid == "B")
                    variants[vid] = {"path": p, "qa_hints": {"text_fits": fits}}
            return out

        monkeypatch.setattr(thumbnailer, "_thumbnail_long", fake_long)
        monkeypatch.setattr(thumbnailer, "_embed_cover_frame", lambda ws, thumb: None)
        monkeypatch.setattr(thumbnailer, "_shorten_main_text", lambda *a, **k: None)
        monkeypatch.delenv("AUTO_EDIT_THUMB_QA_STRICT", raising=False)
        monkeypatch.delenv("AUTO_EDIT_THUMB_VARIANTS", raising=False)

    def test_three_variations_qa_and_metadata(self, monkeypatch, tmp_path):
        self._ws(monkeypatch, tmp_path, b_fails=True)
        thumbnailer.thumbnail(tmp_path)
        meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        items = {v["id"]: v for v in meta["thumbnail_variants"]}
        assert [v["id"] for v in meta["thumbnail_variants"]] == ["A", "B", "C"]
        assert items["A"]["file"] == "thumbnail.png"
        assert items["B"]["qa"] == "reprovada"  # didn't fit → failed, never shrunk
        for stem in ("thumbnail", "thumbnail_b", "thumbnail_c"):
            assert (tmp_path / f"{stem}_qa.json").exists()
            assert (tmp_path / f"{stem}_168.png").exists()

    def test_strict_drops_a_failed_variation_without_failing_the_stage(self, monkeypatch, tmp_path):
        self._ws(monkeypatch, tmp_path, b_fails=True)
        monkeypatch.setenv("AUTO_EDIT_THUMB_QA_STRICT", "1")
        thumbnailer.thumbnail(tmp_path)  # no SystemExit: A passed nothing that failed
        meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        items = {v["id"]: v for v in meta["thumbnail_variants"]}
        assert "reprovada no QA" in items["B"]["skipped"]
        assert not (tmp_path / "thumbnail_b.png").exists()
        assert items["C"]["file"] == "thumbnail_c.png"

    def test_only_a_removes_stale_variations(self, monkeypatch, tmp_path):
        self._ws(monkeypatch, tmp_path)
        thumbnailer.thumbnail(tmp_path)
        assert (tmp_path / "thumbnail_b.png").exists()
        monkeypatch.setenv("AUTO_EDIT_THUMB_VARIANTS", "0")
        thumbnailer.thumbnail(tmp_path)
        meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        assert "thumbnail_variants" not in meta
        assert not (tmp_path / "thumbnail_b.png").exists() and not (tmp_path / "thumbnail_c.png").exists()


# ── delivery ────────────────────────────────────────────────────────────────

class TestDelivery:
    def test_finalize_copies_b_c_and_lists_them_in_the_txt(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setenv("AUTO_EDIT_OUTPUT", str(out))
        video = tmp_path / "meu.mp4"
        video.write_text("")
        ws = tmp_path / "meu"
        ws.mkdir()
        pl.init(ws, video, "long", "c")
        (ws / "overlaid_video.mp4").write_text("v")
        (ws / "edited_video.mp4").write_text("v")
        for vid in ("A", "B", "C"):
            (ws / tv.file_name(vid)).write_bytes(b"PNG")
        meta = {"youtube_title": "t", "thumbnail_variants": [
            tv.entry("A", {"approved": True}), tv.entry("B", {"approved": None}), tv.entry("C", skipped="x")]}
        (ws / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        pl.finalize(ws)
        assert (out / "meu_thumbnail.png").exists() and (out / "meu_thumbnail_b.png").exists()
        assert not (out / "meu_thumbnail_c.png").exists()  # skipped: nothing to deliver
        txt = (out / "meu.txt").read_text(encoding="utf-8")
        assert "Testar e comparar" in txt and "meu_thumbnail_b.png" in txt

    def test_api_serves_the_variations(self):
        assert engine.ARTIFACT_SUFFIXES["thumbnail_b"] == "_thumbnail_b.png"
        assert engine.ARTIFACT_MIME["thumbnail_c"] == "image/png"


# ── item 2: the object frame of a maker video ───────────────────────────────

def _object_img(size=(320, 180), lines: int = 150) -> Image.Image:
    """A printer-like thing: coloured spools + a detailed frame, no skin."""
    im = Image.new("RGB", size, (60, 60, 66))
    d = ImageDraw.Draw(im)
    w, h = size
    d.rectangle((w * 0.25, h * 0.2, w * 0.75, h * 0.85), fill=(25, 25, 25), outline=(220, 220, 220), width=2)
    for i, c in enumerate([(230, 60, 40), (40, 160, 230), (250, 200, 40), (60, 200, 90)]):
        d.rectangle((w * 0.28 + i * w * 0.11, h * 0.25, w * 0.36 + i * w * 0.11, h * 0.45), fill=c)
    rng = np.random.default_rng(0)
    for _ in range(lines):
        x, y = rng.integers(int(w * 0.3), int(w * 0.7)), rng.integers(int(h * 0.5), int(h * 0.8))
        d.line((x, y, x + rng.integers(-8, 8), y + rng.integers(-8, 8)), fill=(200, 200, 200), width=1)
    return im


def _person_img(size=(320, 180)) -> Image.Image:
    im = Image.new("RGB", size, (70, 70, 80))
    w, h = size
    ImageDraw.Draw(im).ellipse((w * 0.3, h * 0.1, w * 0.7, h * 0.95), fill=(205, 150, 120))
    return im


class TestMakerSecondFrame:
    @pytest.mark.parametrize("meta,pipe", [
        ({"thumbnail": {"template": "maker"}}, {}),
        ({"thumbnail": {"style_hint": "fun-colorful"}}, {}),
        ({}, {"context": "montei um AMS caseiro (BMCU) na Bambu"}),
        ({"youtube_title": "Minha IMPRESSORA 3D nova"}, {}),
        ({}, {"context": "peça impressa em PETG"}),
    ])
    def test_maker_video_is_detected(self, meta, pipe):
        assert thumbnailer._is_maker_video(meta, pipe)

    @pytest.mark.parametrize("meta,pipe", [
        ({"thumbnail": {"template": "dev"}}, {"context": "tutorial de Python"}),
        ({}, {"context": "review do fone novo"}),
        ({"youtube_title": "Minha rotina"}, {}),
    ])
    def test_other_videos_are_not(self, meta, pipe):
        assert not thumbnailer._is_maker_video(meta, pipe)

    def test_object_scores_above_a_person_and_a_plain_wall(self):
        obj = thumbnailer._score_object(np.array(_object_img()))
        person = thumbnailer._score_object(np.array(_person_img()))
        wall = thumbnailer._score_object(np.array(Image.new("RGB", (320, 180), (128, 128, 128))))
        assert obj > 0.5 and obj > person + 0.3 and obj > wall + 0.3

    def test_maker_flips_the_choice_to_the_object(self):
        # a sharp, bright but plain frame (tiles) that the generic score
        # prefers over the object frame — a maker video takes the object
        y, x = np.mgrid[0:180, 0:320]
        tiles = Image.fromarray(np.stack([np.where(((x // 16) + (y // 16)) % 2 == 0, 70, 190).astype(np.uint8)] * 3, axis=2))
        obj = _object_img(lines=60)
        assert thumbnailer._second_frame_score(tiles, False) > thumbnailer._second_frame_score(obj, False)
        assert thumbnailer._second_frame_score(obj, True) > thumbnailer._second_frame_score(tiles, True)

    def test_pick_passes_the_maker_flag_to_the_score(self, monkeypatch, tmp_path):
        def extract(video, ts, out):
            Image.new("RGB", (320, 180), (int(ts), 0, 0)).save(out, "PNG")
            return out

        seen = []
        monkeypatch.setattr(thumbnailer, "_extract_frame", extract)
        # the frame at ~90s wins only when scored as a maker video
        monkeypatch.setattr(thumbnailer, "_second_frame_score",
                            lambda img, maker: seen.append(maker) or (img.getpixel((0, 0))[0] if maker else -img.getpixel((0, 0))[0]))
        best = thumbnailer._pick_second_frame("v.mp4", 100.0, tmp_path, 10.0, maker=True)
        with Image.open(best) as im:
            assert im.getpixel((0, 0))[0] > 80
        assert seen and all(seen)
