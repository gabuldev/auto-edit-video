"""Palette: the colors of a logo or a reference image, and a style's colors from them."""
import io

import pytest
from PIL import Image

from auto_edit import palette


def _png(pixels: dict[tuple[int, int, int, int], int], size=64) -> bytes:
    """An image made of horizontal bands: color → number of rows."""
    img = Image.new("RGBA", (size, sum(pixels.values())))
    y = 0
    for color, rows in pixels.items():
        for yy in range(y, y + rows):
            for x in range(size):
                img.putpixel((x, yy), color)
        y += rows
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _close(hex_a: str, hex_b: str, tol=24) -> bool:
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class TestExtract:
    def test_most_present_vivid_color_first(self):
        colors = palette.extract(_png({(230, 30, 40, 255): 40, (20, 90, 220, 255): 10}))
        assert _close(colors[0], "#e61e28") and any(_close(c, "#145adc") for c in colors)

    def test_transparent_pixels_are_ignored(self):
        colors = palette.extract(_png({(0, 0, 0, 0): 60, (250, 200, 0, 255): 4}))
        assert len(colors) == 1 and _close(colors[0], "#fac800")

    def test_gray_only_is_empty(self):
        assert palette.extract(_png({(255, 255, 255, 255): 20, (0, 0, 0, 255): 20, (128, 128, 128, 255): 20})) == []

    def test_similar_colors_merge(self):
        colors = palette.extract(_png({(200, 20, 20, 255): 20, (205, 25, 22, 255): 20}))
        assert len(colors) == 1

    def test_at_most_n(self):
        bands = {(r, 255 - r, 60, 255): 4 for r in range(0, 250, 40)}
        assert len(palette.extract(_png(bands), n=3)) <= 3

    def test_reads_a_path(self, tmp_path):
        p = tmp_path / "logo.png"
        p.write_bytes(_png({(0, 200, 120, 255): 10}))
        assert _close(palette.extract(p)[0], "#00c878")

    def test_unreadable_image_raises(self):
        with pytest.raises(palette.PaletteError):
            palette.extract(b"isso nao e uma imagem")


class TestSuggest:
    def test_none_without_colors(self):
        assert palette.suggest([]) is None

    def test_accent_is_the_most_saturated(self):
        s = palette.suggest(["#c08080", "#ff0044"])
        assert s["accent"] == "#ff0044"

    def test_panel_is_a_dark_shade_of_the_accent_and_text_readable(self):
        s = palette.suggest(["#00d6ff"])
        r, g, b = (int(s["panel"][i:i + 2], 16) for i in (1, 3, 5))
        assert max(r, g, b) <= 40 and b >= r  # dark, same blue-ish hue
        assert s["text"] == "#ffffff"
