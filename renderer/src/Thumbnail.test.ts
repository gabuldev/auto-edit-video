import { expect, test } from "bun:test";
import fs from "node:fs";
import { HERO_FLOOR_FRAC, layout } from "./Thumbnail";
import { fitted, measurer } from "./text";

const anton = (() => {
  const b = fs.readFileSync(new URL("../../assets/thumbnails/fonts/Anton-Regular.ttf", import.meta.url));
  return measurer(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer);
})();
const spec = (main_text: string, kind: "long" | "short" = "long") => ({
  kind, main_text, width: kind === "long" ? 1280 : 1080, height: kind === "long" ? 720 : 1920, accent: [255, 220, 0] as [number, number, number],
});

test("a short hero text fits and never goes below the fixed floor", () => {
  const { info } = layout(spec("MEU CARRO NOVO"), anton);
  expect(info.fits).toBe(true);
  expect(info.size).toBeGreaterThanOrEqual(1280 * HERO_FLOOR_FRAC);
  expect(info.lines).toBeGreaterThanOrEqual(1);
});

test("a text too long for the floor is reported as not fitting (not shrunk)", () => {
  const { info } = layout(spec("ESSA IMPRESSORA TRANSFORMOU COMPLETAMENTE MINHA OFICINA INTEIRA HOJE"), anton);
  expect(info.fits).toBe(false);
  expect(info.size).toBe(Math.floor(1280 * HERO_FLOOR_FRAC)); // stays at the floor
});

test("text box sits in the left column of a long, inside the canvas", () => {
  const { info } = layout(spec("CODEI SEM IA"), anton);
  const [x0, y0, x1, y1] = info.text_box;
  expect(x0).toBe(Math.round(1280 * 0.06));
  expect(x1).toBeLessThanOrEqual(1280 * 0.62);
  expect(y0).toBeGreaterThan(0);
  expect(y1).toBeLessThan(720);
  expect(Math.abs(y1 - y0 - info.lines * info.size * 1.02)).toBeLessThanOrEqual(1);
});

test("short: centred box, floor scales with the width", () => {
  const { info } = layout(spec("PEGUEI COM R$5", "short"), anton);
  expect(info.fits).toBe(true);
  expect(info.size).toBeGreaterThanOrEqual(1080 * HERO_FLOOR_FRAC);
  const [x0, , x1] = info.text_box;
  expect(Math.abs((x0 + x1) / 2 - 540)).toBeLessThanOrEqual(1);
});

test("fitted accepts a text that only fits exactly at the floor", () => {
  const w = (t: string, s: number) => t.length * s; // 1 char = 1 em
  // "ABCD" at 50 = 200px; box 205*0.98 = 200.9 → fits only at min=50
  expect(fitted("ABCD", { box: 205, maxH: 1000, max: 80, min: 50, maxLines: 1 }, w)).toEqual({ size: 50, ok: true });
});
