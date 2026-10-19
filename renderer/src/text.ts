// Satori lays text out but can't auto-fit it: measure with the real font and
// pick the biggest size whose greedy word wrap fits the box.
import * as opentype from "opentype.js";

export type Measurer = (text: string, size: number) => number;

export function measurer(font: ArrayBuffer): Measurer {
  const f = opentype.parse(font);
  let shaping = true;
  // Some fonts (Bangers) have GSUB lookups opentype.js can't apply: then sum
  // the glyph advances without shaping (ligatures barely change a width).
  const plain = (text: string, size: number) =>
    [...text].reduce((w, ch) => w + (f.charToGlyph(ch).advanceWidth || 0), 0) * (size / f.unitsPerEm);
  return (text, size) => {
    if (shaping) {
      try {
        return f.getAdvanceWidth(text, size);
      } catch {
        shaping = false;
      }
    }
    return plain(text, size);
  };
}

export function wrap(text: string, size: number, box: number, width: Measurer): string[] {
  const out: string[] = [];
  let cur = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = cur ? `${cur} ${word}` : word;
    if (cur && width(next, size) > box) {
      out.push(cur);
      cur = word;
    } else {
      cur = next;
    }
  }
  if (cur) out.push(cur);
  return out;
}

type FitBox = { box: number; maxH: number; max: number; min: number; maxLines: number; lineHeight?: number };

/** Biggest size in [min, max] where `text` wraps into ≤ maxLines lines no
 * wider than `box` and no taller than `maxH`; `ok` is false when even `min`
 * doesn't fit (the size is then `min`). */
export function fitted(text: string, o: FitBox, width: Measurer): { size: number; ok: boolean } {
  const lh = o.lineHeight ?? 1.02;
  const box = o.box * 0.98;
  for (let size = Math.floor(o.max); size > o.min; size -= 2) {
    const lines = wrap(text, size, box, width);
    if (lines.length <= o.maxLines && lines.every((l) => width(l, size) <= box) && lines.length * size * lh <= o.maxH) {
      return { size, ok: true };
    }
  }
  return { size: Math.floor(o.min), ok: false };
}

export function fit(text: string, o: FitBox, width: Measurer): number {
  return fitted(text, o, width).size;
}
