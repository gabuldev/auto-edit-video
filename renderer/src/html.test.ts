import { expect, test } from "bun:test";
import { htmlTree } from "./html";

const m = (t: string, s: number) => t.length * s * 0.5; // fake measurer
const V = {
  titulo: "Titulo grande demais pra caber numa linha so", titulo_inicio: "Titulo", titulo_fim: "so", etiqueta: "",
  destaque: "#00d6ff", "cor.accent": "#00d6ff", "cor.panel": "#111111", "cor.text": "#ffffff",
};
const find = (n: any, pred: (n: any) => boolean): any => {
  if (!n || typeof n !== "object") return null;
  if (pred(n)) return n;
  const kids = Array.isArray(n.props?.children) ? n.props.children : [n.props?.children];
  for (const k of kids) {
    const r = find(k, pred);
    if (r) return r;
  }
  return null;
};

test("fills text and color placeholders", () => {
  const t = htmlTree('<div><span style="color:{{destaque}}">{{titulo}}</span><span>x</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  const span = find(t, (n) => n.type === "span" && n.props.style.color);
  expect(span.props.style.color).toBe("#00d6ff");
  expect(span.props.children).toBe(V.titulo);
});

test("img without a value and element left empty disappear", () => {
  const t = htmlTree('<div><img src="{{logo}}"/><span>{{etiqueta}}</span><span>fica</span></div>', V, { logo: null }, { Anton: m }, "Anton", 1280, 720);
  expect(find(t, (n) => n.type === "img")).toBeNull();
  expect(find(t, (n) => n.type === "span" && n.props.children !== "fica")).toBeNull();
});

test("img with a value gets the data URL", () => {
  const t = htmlTree('<div><img src="{{frame}}" style="width:10px"/></div>', V, { frame: "data:image/png;base64,AA" }, { Anton: m }, "Anton", 1280, 720);
  expect(find(t, (n) => n.type === "img").props.src).toBe("data:image/png;base64,AA");
});

test("data-fit shrinks a long title into its box", () => {
  const t = htmlTree('<div><span data-fit="linhas:1;min:20;max:200" style="width:400px;font-family:Anton">{{titulo}}</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  const span = find(t, (n) => n.type === "span");
  expect(span.props.style.fontSize).toBeLessThan(200);
  expect(span.props.style.fontSize).toBeGreaterThanOrEqual(20);
});

test("unknown font falls back; multi-child div gets display:flex; root sized", () => {
  const t = htmlTree('<div><span style="font-family:Comic Sans">a</span><span>b</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  expect(t.props.style.display).toBe("flex");
  expect(t.props.style.width).toBe(1280);
  expect(find(t, (n) => n.type === "span").props.style.fontFamily).toBe("Anton");
});

test("several top-level elements are wrapped", () => {
  const t = htmlTree("<span>a</span><span>b</span>", V, {}, { Anton: m }, "Anton", 1280, 720);
  expect(t.type).toBe("div");
  expect(t.props.children.length).toBe(2);
});

test("entities in text come out as characters", () => {
  const t = htmlTree("<div>A &amp; B</div>", V, {}, { Anton: m }, "Anton", 1280, 720);
  expect(t.props.children).toBe("A & B");
});

test("text-transform is applied before fitting (uppercase is wider)", () => {
  const wide = (t: string, s: number) => [...t].reduce((w, c) => w + (c === c.toUpperCase() && c !== " " ? 1 : 0.5), 0) * s * 0.5;
  const html = (tt: string) => `<div><span data-fit="linhas:1;min:10;max:300" style="width:600px;${tt}">{{titulo}}</span></div>`;
  const plain = find(htmlTree(html(""), V, {}, { Anton: wide }, "Anton", 1280, 720), (n) => n.type === "span");
  const upper = find(htmlTree(html("text-transform:uppercase"), V, {}, { Anton: wide }, "Anton", 1280, 720), (n) => n.type === "span");
  expect(upper.props.children).toBe(V.titulo.toUpperCase());
  expect(upper.props.style.fontSize).toBeLessThan(plain.props.style.fontSize);
});

test("nothing in a style can point the renderer at a URL", () => {
  const t = htmlTree('<div style="background-image:u{{x}}rl(https://evil/p.png);color:red"><img src="{{frame}}"/></div>', V, { frame: "https://evil/i.png" }, { Anton: m }, "Anton", 1280, 720);
  expect(JSON.stringify(t)).not.toContain("evil");
  expect(t.props.style.color).toBe("red");
});

test("data-fit never goes past its lines: shrinks below min, then clamps", () => {
  const long = { ...V, titulo: "uma frase bem comprida com onze palavras que nunca vai caber ali" };
  const box = (w: number) => `<div><span data-fit="linhas:2;min:60;max:160" style="width:${w}px;height:300px">{{titulo}}</span></div>`;
  const shrunk = find(htmlTree(box(600), long, {}, { Anton: m }, "Anton", 1280, 720), (n) => n.type === "span");
  expect(shrunk.props.style.fontSize).toBeLessThan(60);
  expect(shrunk.props.style.lineClamp).toBeUndefined();
  const hopeless = find(htmlTree(box(150), long, {}, { Anton: m }, "Anton", 1280, 720), (n) => n.type === "span");
  expect(hopeless.props.style.lineClamp).toBe(2);
  expect(hopeless.props.style.overflow).toBe("hidden");
});

test("a title that fits is never clipped (accents stick out of the line box)", () => {
  const t = htmlTree('<div><span data-fit="linhas:2;min:20;max:100" style="width:1200px;height:400px">{{titulo_fim}}</span></div>', V, {}, { Anton: m }, "Anton", 1280, 720);
  const span = find(t, (n) => n.type === "span");
  expect(span.props.style.overflow).toBeUndefined();
  expect(span.props.style.lineClamp).toBeUndefined();
});

test("stroke and shadow shrink with a fitted title (they were sized for max)", () => {
  const t = htmlTree(
    '<div><span data-fit="linhas:1;min:10;max:100" style="width:300px;-webkit-text-stroke:10px #000;text-shadow:8px 8px 0 #000">{{titulo}}</span></div>',
    V, {}, { Anton: m }, "Anton", 1280, 720);
  const s = find(t, (n) => n.type === "span").props.style;
  const k = s.fontSize / 100;
  expect(k).toBeLessThan(0.5);
  expect(s.WebkitTextStroke).toBe(`${+(10 * k).toFixed(1)}px #000`);
  expect(s.textShadow).toBe(`${+(8 * k).toFixed(1)}px ${+(8 * k).toFixed(1)}px 0 #000`);
});
