"""The React renderer's report on the hero text (item 4): it says whether the
text fit without shrinking, so the QA runs fits_without_shrinking on the
React path too instead of leaving it "parcial"."""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import thumbnailer  # noqa: E402

from auto_edit import thumb_qa  # noqa: E402


class TestReportParsing:
    def test_last_json_line_wins(self):
        out = 'warming up\n{"text_fits": false, "text_lines": 2}\n'
        assert thumbnailer._renderer_report(out) == {"text_fits": False, "text_lines": 2}

    def test_older_renderer_prints_nothing(self):
        assert thumbnailer._renderer_report("") == {}
        assert thumbnailer._renderer_report("not json") == {}
        assert thumbnailer._renderer_report("[1, 2]") == {}

    def test_html_layout_reports_only_the_fit(self):
        hints = thumbnailer._react_qa_hints({"text_fits": True, "fit": []}, {"kind": "long", "width": 1280, "height": 720})
        assert hints == {"text_fits": True}

    def test_default_layout_reports_where_the_text_is(self, tmp_path):
        face = tmp_path / "face.png"
        Image.new("RGBA", (400, 500)).save(face)
        spec = {"kind": "long", "width": 1280, "height": 720, "face": str(face)}
        hints = thumbnailer._react_qa_hints(
            {"text_fits": True, "text_lines": 2, "text_box": [77, 230, 600, 490]}, spec)
        assert hints["text_box"] == (77, 230, 600, 490) and hints["text_lines"] == 2
        assert hints["full_height"] == 720
        # Thumbnail.tsx: face bottom-right at 78% of the height, its own aspect
        fh = 720 * 0.78
        assert hints["face_box"] == (int(1280 - fh * 0.8), int(720 - fh), 1280, 720)

    def test_bad_values_are_dropped(self):
        hints = thumbnailer._react_qa_hints({"text_fits": "yes", "text_box": [1, 2]}, {"kind": "long", "width": 1, "height": 1})
        assert hints == {}


def _fake_renderer(tmp_path: Path, report: dict | None) -> list[str]:
    """A stand-in for auto-edit-render: writes the PNG and prints the report."""
    script = tmp_path / "render.py"
    line = f"print({json.dumps(json.dumps(report))})" if report is not None else ""
    script.write_text(
        "import sys\nfrom PIL import Image\n"
        "Image.new('RGB', (1280, 720)).save(sys.argv[3])\n" + line + "\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


class TestRenderReact:
    def _setup(self, monkeypatch, tmp_path, report):
        monkeypatch.setattr(thumbnailer, "_renderer_cmd", lambda: _fake_renderer(tmp_path, report))
        font = tmp_path / "Anton.ttf"
        font.write_bytes(b"x")
        monkeypatch.setattr(thumbnailer, "_render_font", lambda: font)
        monkeypatch.setattr(thumbnailer.styles, "active", lambda: (_ for _ in ()).throw(ValueError("no style")))

    def test_fit_reaches_the_qa_hints(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, {"text_fits": False, "text_lines": 2, "text_box": [70, 200, 700, 460]})
        qa: dict = {}
        spec = {"kind": "long", "width": 1280, "height": 720, "main_text": "X", "accent": [1, 2, 3]}
        assert thumbnailer._render_react(spec, tmp_path / "t.png", qa_out=qa)
        assert qa["text_fits"] is False and qa["text_lines"] == 2
        rep = thumb_qa.evaluate("CODEI SEM IA", **qa)
        assert rep["approved"] is False
        assert rep["checks"]["fits_without_shrinking"]["ok"] is False
        assert rep["checks"]["mobile_text_height"] is not None  # no longer skipped on React

    def test_old_renderer_keeps_it_parcial(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, None)
        qa: dict = {}
        spec = {"kind": "long", "width": 1280, "height": 720, "main_text": "X", "accent": [1, 2, 3]}
        assert thumbnailer._render_react(spec, tmp_path / "t.png", qa_out=qa)
        assert qa == {}
        assert thumb_qa.evaluate("CODEI SEM IA", **qa)["checks"]["fits_without_shrinking"] is None

    def test_variation_layout_never_falls_back_to_the_default(self, monkeypatch, tmp_path):
        # no style → the B/C layout can't be drawn by the renderer: Pillow, not A again
        self._setup(monkeypatch, tmp_path, {"text_fits": True})
        spec = {"kind": "long", "width": 1280, "height": 720, "main_text": "X", "accent": [1, 2, 3]}
        assert thumbnailer._render_react(spec, tmp_path / "t.png", html="<div>{{titulo}}</div>") is False
