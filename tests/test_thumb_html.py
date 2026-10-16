"""A style's thumbnail layout (HTML from the AI) is made safe before saving."""
import pytest

from auto_edit import thumb_html as th

OK = ('<div style="display:flex;width:1280px;height:720px"><img src="{{frame}}" style="width:1280px"/>'
      '<span data-fit="linhas:2;min:60;max:160" style="color:{{destaque}}">{{titulo}}</span></div>')


def test_keeps_a_good_layout():
    out = th.sanitize(OK)
    assert "{{frame}}" in out and "{{titulo}}" in out and 'data-fit="linhas:2;min:60;max:160"' in out


def test_strips_scripts_styles_links_and_handlers():
    out = th.sanitize('<div onclick="x()"><script>alert(1)</script><style>*{}</style><link href="a"><span>oi</span></div>')
    assert "script" not in out and "style>" not in out and "link" not in out and "onclick" not in out and "oi" in out


def test_img_with_a_foreign_src_is_dropped():
    out = th.sanitize('<div><img src="https://evil/x.png"/><img src="{{logo}}"/></div>')
    assert "evil" not in out and "{{logo}}" in out


def test_css_url_is_removed():
    out = th.sanitize('<div style="background:url(https://x/y.png);color:red">a</div>')
    assert "url(" not in out and "color:red" in out


def test_unknown_tags_are_unwrapped_keeping_text():
    out = th.sanitize("<div><b>forte</b></div>")
    assert "<b" not in out and "forte" in out


def test_text_is_escaped():
    assert "&lt;i&gt;" in th.sanitize("<div>&lt;i&gt;</div>")


def test_empty_or_huge_raises():
    with pytest.raises(th.ThumbHtmlError):
        th.sanitize("<script>x</script>")
    with pytest.raises(th.ThumbHtmlError):
        th.sanitize("<div>" + "a" * 20001 + "</div>")


def test_placeholders():
    assert th.placeholders(OK) == {"frame", "titulo", "destaque"}


def test_placeholder_hidden_inside_url_is_removed():
    out = th.sanitize('<div style="background-image:u{{x}}rl(https://evil/p.png);color:{{destaque}}">a</div>')
    assert "evil" not in out and "color:{{destaque}}" in out


def test_only_color_placeholders_in_css():
    out = th.sanitize('<div style="width:{{titulo}}px;color:{{cor.accent}}">a</div>')
    assert "titulo" not in out and "{{cor.accent}}" in out


def test_outlined_face_slot_is_an_image():
    assert "{{rosto_contorno}}" in th.sanitize('<div><img src="{{rosto_contorno}}"/></div>')
