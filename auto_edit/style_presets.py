"""The gallery's ready-made thumbnail layouts (HTML + inline CSS, the same
format the renderer draws for any style: see auto_edit/thumb_html.py).

Each layout must hold up with a 2-word and an 8-word title, with and without
{{etiqueta}}, and with no {{rosto}} (a video without a person): every element
with an empty placeholder disappears, so nothing may depend on it.

The title elements name no font: they use the style's title font (the
renderer's default), so picking another one in the editor changes them.
"""
from __future__ import annotations

_FRAME = '<img src="{{frame}}" style="position:absolute;left:0;top:0;width:1280px;height:720px;object-fit:cover"/>'


def _shade(css: str) -> str:
    return f'<div style="position:absolute;left:0;top:0;width:1280px;height:720px;{css}"></div>'


LAYOUTS: dict[str, str] = {
    # Person cut out with a white outline on the right, huge title on the left,
    # the last word in a yellow gradient (the classic YouTube look).
    "rosto_gigante": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(90deg,rgba(0,0,0,0.92) 0%,rgba(0,0,0,0.75) 45%,rgba(0,0,0,0.1) 75%)")
        + '<img src="{{rosto_contorno}}" style="position:absolute;right:10px;bottom:0;width:560px;height:690px;object-fit:contain;object-position:bottom"/>'
        + '<div style="position:absolute;left:56px;top:40px;width:700px;height:640px;display:flex;flex-direction:column;justify-content:center">'
        + '<div data-fit="linhas:3;min:56;max:118" style="width:700px;max-height:330px;font-size:118px;line-height:1.05;color:#fff;text-transform:uppercase;-webkit-text-stroke:7px #000;text-shadow:7px 7px 0 #000">{{titulo_inicio}}</div>'
        + '<div data-fit="linhas:1;min:70;max:200" style="width:700px;max-height:210px;font-size:200px;line-height:1.05;text-transform:uppercase;background-image:linear-gradient(180deg,#fff7a0 0%,{{cor.accent}} 55%,#ff8a00 100%);background-clip:text;color:transparent;-webkit-text-stroke:9px #000">{{titulo_fim}}</div>'
        + "</div></div>"
    ),
    # The last word on a slanted red bar.
    "tarja": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(0deg,rgba(0,0,0,0.9) 0%,rgba(0,0,0,0.55) 45%,rgba(0,0,0,0) 75%)")
        + '<div style="position:absolute;left:60px;bottom:56px;width:1160px;display:flex;flex-direction:column;align-items:flex-start">'
        + '<div data-fit="linhas:2;min:50;max:120" style="width:1160px;max-height:250px;font-size:120px;line-height:1.04;color:#fff;text-transform:uppercase;text-shadow:5px 5px 0 #000">{{titulo_inicio}}</div>'
        + '<div style="display:flex;margin-top:10px;padding:4px 34px 10px 34px;background-color:{{cor.accent}};transform:skewX(-10deg) rotate(-2deg);box-shadow:10px 10px 0 #000">'
        + '<div data-fit="linhas:1;min:60;max:150" style="max-width:1000px;max-height:165px;font-size:150px;line-height:1.08;color:#fff;text-transform:uppercase">{{titulo_fim}}</div>'
        + "</div></div></div>"
    ),
    # Dark, purple/cyan offset layers behind the title.
    "neon_tech": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#05010f">'
        + _FRAME
        + _shade("background-color:rgba(8,0,30,0.62)")
        + _shade("background-image:linear-gradient(90deg,rgba(255,0,230,0.35) 0%,rgba(0,0,0,0) 40%,rgba(0,0,0,0) 60%,rgba(0,229,255,0.35) 100%)")
        + '<div style="position:absolute;left:0;top:0;width:1280px;height:720px;display:flex;flex-direction:column;align-items:center;justify-content:center">'
        + '<div data-fit="linhas:3;min:60;max:200" style="width:1120px;max-height:480px;display:flex;justify-content:center;text-align:center;font-size:200px;line-height:1;color:#fff;text-transform:uppercase;text-shadow:-6px -6px 0 {{cor.panel}},6px 6px 0 {{cor.accent}},12px 12px 0 #000">{{titulo}}</div>'
        + '<div style="display:flex;margin-top:18px;padding:8px 30px;border:4px solid {{cor.accent}};border-radius:999px;font-family:Montserrat;font-weight:700;font-size:38px;color:{{cor.accent}};text-transform:uppercase">{{etiqueta}}</div>'
        + "</div></div>"
    ),
    # Sentence case, lots of room, one thin accent line.
    "limpo": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(90deg,rgba(0,0,0,0.8) 0%,rgba(0,0,0,0.55) 40%,rgba(0,0,0,0) 70%)")
        + '<div style="position:absolute;left:80px;top:0;width:640px;height:720px;display:flex;flex-direction:column;justify-content:center">'
        + '<div style="display:flex;width:90px;height:10px;border-radius:5px;background-color:{{cor.accent}};margin-bottom:28px"></div>'
        + '<div data-fit="linhas:4;min:44;max:92" style="width:640px;max-height:420px;font-weight:700;font-size:92px;line-height:1.08;color:#fff">{{titulo}}</div>'
        + '<div style="display:flex;margin-top:22px;font-family:Poppins;font-weight:400;font-size:36px;color:{{cor.accent}}">{{etiqueta}}</div>'
        + "</div></div>"
    ),
    # TV news: red tag over a black band with the title.
    "jornal": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(0deg,rgba(0,0,0,0.6) 0%,rgba(0,0,0,0) 50%)")
        + '<div style="position:absolute;left:0;bottom:60px;width:1280px;display:flex;flex-direction:column;align-items:flex-start">'
        + '<div style="display:flex;margin-left:60px;padding:6px 26px;background-color:{{cor.accent}};font-family:Archivo Black;font-size:40px;color:#fff;text-transform:uppercase">{{etiqueta}}</div>'
        + '<div style="display:flex;width:1280px;padding:16px 60px 20px 60px;background-color:rgba(0,0,0,0.88);border-top:8px solid {{cor.accent}}">'
        + '<div data-fit="linhas:2;min:46;max:96" style="width:1160px;max-height:210px;display:flex;align-items:center;font-size:96px;line-height:1.08;color:#fff;text-transform:uppercase">{{titulo}}</div>'
        + "</div></div></div>"
    ),
    # Two moments side by side with a VS badge.
    "versus": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + '<img src="{{frame}}" style="position:absolute;left:0;top:0;width:636px;height:720px;object-fit:cover"/>'
        + '<img src="{{frame2}}" style="position:absolute;left:644px;top:0;width:636px;height:720px;object-fit:cover"/>'
        + '<div style="position:absolute;left:636px;top:0;width:8px;height:720px;background-color:#fff"></div>'
        + _shade("background-image:linear-gradient(180deg,rgba(0,0,0,0.85) 0%,rgba(0,0,0,0) 38%)")
        + '<div style="position:absolute;left:540px;top:290px;width:200px;height:200px;border-radius:100px;background-color:{{cor.accent}};border:8px solid #fff;display:flex;align-items:center;justify-content:center;font-family:Luckiest Guy;font-size:96px;color:#fff;-webkit-text-stroke:5px #000">VS</div>'
        + '<div style="position:absolute;left:40px;top:24px;width:1200px;display:flex;justify-content:center">'
        + '<div data-fit="linhas:2;min:48;max:104" style="width:1200px;max-height:220px;display:flex;justify-content:center;text-align:center;font-size:104px;line-height:1.05;color:#fff;text-transform:uppercase;-webkit-text-stroke:6px #000;text-shadow:6px 6px 0 #000">{{titulo}}</div>'
        + "</div></div>"
    ),
    # A colored panel on the left with a slanted edge; the footage on the right.
    "painel": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + '<img src="{{frame}}" style="position:absolute;left:380px;top:0;width:900px;height:720px;object-fit:cover"/>'
        + '<div style="position:absolute;left:-140px;top:-40px;width:900px;height:800px;background-color:{{cor.panel}};transform:skewX(-9deg);border-right:14px solid {{cor.accent}}"></div>'
        + '<div style="position:absolute;left:56px;top:0;width:620px;height:720px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start">'
        + '<div style="display:flex;padding:6px 20px;margin-bottom:22px;border-radius:10px;background-color:{{cor.accent}};font-family:Montserrat;font-weight:700;font-size:34px;color:{{cor.panel}};text-transform:uppercase">{{etiqueta}}</div>'
        + '<div data-fit="linhas:4;min:50;max:112" style="width:600px;max-height:470px;font-weight:700;font-size:112px;line-height:1.02;color:#fff;text-transform:uppercase">{{titulo}}</div>'
        + "</div></div>"
    ),
    # The second moment inside a tilted phone over a gradient.
    "celular": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-image:linear-gradient(135deg,{{cor.panel}} 0%,#000 100%)">'
        + '<div style="position:absolute;left:-200px;top:-260px;width:760px;height:760px;border-radius:380px;background-color:{{cor.accent}};opacity:0.18"></div>'
        + '<div style="position:absolute;right:110px;top:46px;width:340px;height:660px;display:flex;padding:14px;border-radius:52px;background-color:#0b0b0b;border:4px solid #3a3a3a;transform:rotate(7deg);box-shadow:24px 24px 0 rgba(0,0,0,0.45)">'
        + '<img src="{{frame}}" style="width:304px;height:624px;border-radius:40px;object-fit:cover"/>'
        + "</div>"
        + '<div style="position:absolute;left:64px;top:0;width:700px;height:720px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start">'
        + '<div data-fit="linhas:4;min:52;max:120" style="width:700px;max-height:450px;font-size:120px;line-height:1.02;color:#fff;text-transform:uppercase;text-shadow:6px 6px 0 #000">{{titulo}}</div>'
        + '<div style="display:flex;margin-top:20px;padding:8px 24px;border-radius:14px;background-color:{{cor.accent}};font-family:Lilita One;font-size:44px;color:#000;text-transform:uppercase">{{etiqueta}}</div>'
        + "</div></div>"
    ),
    # Big outlined person on the left, the other moment in a ringed circle.
    "reacao": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(270deg,rgba(0,0,0,0.85) 0%,rgba(0,0,0,0.6) 50%,rgba(0,0,0,0.25) 100%)")
        + '<img src="{{rosto_contorno}}" style="position:absolute;left:10px;bottom:0;width:560px;height:690px;object-fit:contain;object-position:bottom"/>'
        + '<div style="position:absolute;right:40px;top:0;width:640px;height:720px;display:flex;flex-direction:column;align-items:center;justify-content:center">'
        + '<div style="width:340px;height:340px;display:flex;border-radius:170px;border:12px solid {{cor.accent}};overflow:hidden;box-shadow:10px 10px 0 #000">'
        + '<img src="{{frame2}}" style="width:316px;height:316px;object-fit:cover"/>'
        + "</div>"
        + '<div data-fit="linhas:3;min:46;max:96" style="width:640px;max-height:280px;margin-top:22px;display:flex;justify-content:center;text-align:center;font-size:96px;line-height:1.05;color:{{cor.accent}};text-transform:uppercase;-webkit-text-stroke:6px #000;text-shadow:6px 6px 0 #000">{{titulo}}</div>'
        + "</div></div>"
    ),
    # Comic book: the title in a white balloon, the tag on a red sticker.
    "quadrinho": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-color:rgba(0,0,0,0.15)")
        + '<div style="position:absolute;left:50px;top:44px;width:760px;display:flex;flex-direction:column;align-items:flex-start;transform:rotate(-3deg)">'
        + '<div style="display:flex;padding:22px 40px 26px 40px;border-radius:48px;background-color:#fff;border:8px solid #000;box-shadow:12px 12px 0 #000">'
        + '<div data-fit="linhas:3;min:52;max:120" style="max-width:670px;max-height:380px;display:flex;align-items:center;font-size:120px;line-height:1.02;color:#111;text-transform:uppercase">{{titulo}}</div>'
        + "</div>"
        + '<div style="display:flex;margin-top:26px;margin-left:30px;padding:8px 26px;background-color:{{cor.accent}};border:6px solid #000;transform:rotate(4deg);font-family:Bangers;font-size:56px;color:#fff;text-transform:uppercase;-webkit-text-stroke:2px #000">{{etiqueta}}</div>'
        + "</div></div>"
    ),
    # Sober: gold gradient title over a dark band, thin gold rules.
    "ouro": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(0deg,rgba(0,0,0,0.95) 0%,rgba(0,0,0,0.8) 40%,rgba(0,0,0,0.1) 75%)")
        + '<div style="position:absolute;left:0;bottom:50px;width:1280px;display:flex;flex-direction:column;align-items:center">'
        + '<div style="display:flex;width:220px;height:4px;background-color:{{cor.accent}};margin-bottom:22px"></div>'
        + '<div data-fit="linhas:2;min:46;max:104" style="width:1120px;max-height:230px;display:flex;justify-content:center;text-align:center;font-size:104px;line-height:1.08;text-transform:uppercase;background-image:linear-gradient(180deg,#fff3c4 0%,{{cor.accent}} 50%,#9a6a12 100%);background-clip:text;color:transparent">{{titulo}}</div>'
        + '<div style="display:flex;margin-top:16px;font-family:Montserrat;font-weight:400;font-size:32px;letter-spacing:8px;color:{{cor.accent}};text-transform:uppercase">{{etiqueta}}</div>'
        + "</div></div>"
    ),
    # The title on a rounded white card with a hard shadow.
    "card": (
        '<div style="display:flex;position:relative;width:1280px;height:720px;background-color:#000">'
        + _FRAME
        + _shade("background-image:linear-gradient(0deg,rgba(0,0,0,0.5) 0%,rgba(0,0,0,0) 60%)")
        + '<div style="position:absolute;left:56px;bottom:56px;display:flex;flex-direction:column;align-items:flex-start;padding:30px 40px 34px 40px;border-radius:32px;background-color:#fff;box-shadow:14px 14px 0 {{cor.accent}}">'
        + '<div style="display:flex;margin-bottom:10px;font-family:Poppins;font-weight:700;font-size:34px;color:{{cor.accent}};text-transform:uppercase">{{etiqueta}}</div>'
        + '<div data-fit="linhas:3;min:44;max:84" style="max-width:760px;max-height:280px;display:flex;align-items:flex-end;font-weight:700;font-size:84px;line-height:1.06;color:#111">{{titulo}}</div>'
        + "</div></div>"
    ),
}
