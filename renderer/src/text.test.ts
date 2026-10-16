import { expect, test } from "bun:test";
import fs from "node:fs";
import { measurer } from "./text";

const load = (f: string) => {
  const b = fs.readFileSync(new URL(`../../assets/fonts/${f}`, import.meta.url));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
};

// Bangers has a GSUB lookup opentype.js can't apply (type 6, format 2):
// measuring must not throw, and must still grow with the text.
test("measures every bundled display font", () => {
  for (const f of ["Bangers-Regular.ttf", "LilitaOne-Regular.ttf", "LuckiestGuy-Regular.ttf", "ArchivoBlack-Regular.ttf"]) {
    const m = measurer(load(f));
    const short = m("A IA", 100);
    const long = m("A IA EDITA PRA VOCÊ E É DE GRAÇA", 100);
    expect(short).toBeGreaterThan(0);
    expect(long).toBeGreaterThan(short * 3);
  }
});
