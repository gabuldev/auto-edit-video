// A style's thumbnail layout (HTML + inline CSS, sanitized by
// auto_edit/thumb_html.py) → a Satori tree: placeholders filled, elements
// without a value removed, the title fitted with the real font. Values are
// put into text nodes after parsing, so they are never read as HTML.
import { parse, ELEMENT_NODE, TEXT_NODE } from "ultrahtml";
import { fitted, type Measurer } from "./text";

type Values = Record<string, string>;
const FIT_FLOOR = 24;
const SLOTS = /\{\{\s*([a-z0-9_.]+)\s*\}\}/g;
const HAS_SLOT = /\{\{\s*[a-z0-9_.]+\s*\}\}/;
const ENT: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&#x27;": "'", "&nbsp;": " " };
const unescape = (s: string) => s.replace(/&(amp|lt|gt|quot|#39|#x27|nbsp);/g, (e) => ENT[e]);
const px = (v: unknown) =>
  typeof v === "number" ? v : typeof v === "string" && /^-?[\d.]+(px)?$/.test(v.trim()) ? parseFloat(v) : undefined;

function css(s: string): Record<string, any> {
  const out: Record<string, any> = {};
  for (const d of s.split(";")) {
    const i = d.indexOf(":");
    if (i < 1) continue;
    const key = d
      .slice(0, i)
      .trim()
      .toLowerCase()
      .replace(/^-webkit-/, "Webkit-")
      .replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const value = unescape(d.slice(i + 1).trim());
    // Defense in depth (thumb_html.py already strips them): nothing that loads.
    if (/url\s*\(|image-set|@import/i.test(value) || key === "src") continue;
    out[key] = value;
  }
  return out;
}

function parseFit(s: string) {
  const o: Record<string, number> = {};
  for (const part of s.split(";")) {
    const [k, v] = part.split(":").map((x) => x.trim());
    if (k && v && !isNaN(+v)) o[k] = +v;
  }
  return { lines: Math.max(1, o.linhas ?? 2), min: o.min ?? 40, max: o.max ?? 160 };
}

export function htmlTree(
  html: string,
  values: Values,
  images: Record<string, string | null>,
  measure: Record<string, Measurer>,
  defaultFont: string,
  w: number,
  h: number,
): any {
  const fill = (s: string) => s.replace(SLOTS, (_, k) => values[k] ?? "");
  const fonts = new Set(Object.keys(measure));
  const fontOf = (style: Record<string, any>) => {
    const fam = String(style.fontFamily || "").split(",")[0].trim().replace(/^['"]|['"]$/g, "");
    return fonts.has(fam) ? fam : defaultFont;
  };

  const transform = (t: string, how: string) =>
    how === "uppercase" ? t.toUpperCase() : how === "lowercase" ? t.toLowerCase()
      : how === "capitalize" ? t.replace(/(^|\s)(\S)/g, (_, a, b) => a + b.toUpperCase()) : t;

  // `inherited` / `tt`: the font and text-transform from the parents — the
  // text is measured as it will be drawn.
  function conv(n: any, inherited: string, tt = ""): any {
    if (n.type === TEXT_NODE) {
      const raw = unescape(String(n.value));
      const t = fill(raw).replace(/\s+/g, " ").trim();
      return t ? t : HAS_SLOT.test(raw) ? { empty: true } : null;
    }
    if (n.type !== ELEMENT_NODE) return null;
    const a = n.attributes || {};
    const style = a.style ? css(fill(unescape(a.style))) : {};
    if (style.fontFamily) style.fontFamily = fontOf(style);
    const font = style.fontFamily || inherited;
    const how = String(style.textTransform || tt);
    if (n.name === "img") {
      const m = String(a.src || "").match(/\{\{\s*([a-z0-9]+)\s*\}\}/);
      const src = m ? images[m[1]] : null;
      // Only inline images (cli.tsx turns the slots' files into data: URLs).
      return src && src.startsWith("data:") ? { type: "img", props: { src, style } } : null;
    }
    const raw = (n.children || [])
      .map((c: any) => conv(c, font, how))
      .filter((c: any) => c !== null)
      .map((c: any) => (typeof c === "string" ? transform(c, how) : c));
    const kids = raw.filter((c: any) => !(c && c.empty));
    if (!kids.length && raw.length) return null; // only empty placeholders: the element goes away
    if (a["data-fit"] && kids.length === 1 && typeof kids[0] === "string") {
      const f = parseFit(a["data-fit"]);
      const box = px(style.width) ?? px(style.maxWidth) ?? w * 0.9;
      const maxH = px(style.height) ?? px(style.maxHeight) ?? h;
      const lh = parseFloat(style.lineHeight) || 1.02;
      // Below `min` down to a floor before giving up on the line count; only
      // then clamp (clipping always would cut the accents off: Á, Ã stick out
      // of the line box).
      const r = fitted(kids[0], { box, maxH, max: f.max, min: Math.min(f.min, FIT_FLOOR), maxLines: f.lines, lineHeight: lh },
        measure[font] || measure[defaultFont]);
      style.fontSize = r.size;
      style.lineHeight ??= lh;
      if (!r.ok) {
        style.overflow = "hidden";
        style.lineClamp = f.lines;
      }
    }
    // Satori needs display:flex on any element with several children.
    if (kids.length > 1 && !style.display) style.display = "flex";
    return { type: n.name === "p" ? "div" : n.name, props: { style, children: kids.length === 1 ? kids[0] : kids } };
  }

  const top = parse(html)
    .children.map((c: any) => conv(c, defaultFont))
    .filter((c: any) => c && !c.empty);
  const root =
    top.length === 1 && typeof top[0] === "object" && top[0].type === "div"
      ? top[0]
      : { type: "div", props: { style: {}, children: top.length === 1 ? top[0] : top } };
  root.props.style = { display: "flex", position: "relative", overflow: "hidden", fontFamily: defaultFont, ...root.props.style, width: w, height: h };
  return root;
}
