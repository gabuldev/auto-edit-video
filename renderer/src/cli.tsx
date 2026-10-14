// auto-edit-render — React → PNG without a browser.
//
//   auto-edit-render thumbnail <spec.json> <out.png>
//
// spec.json: the ThumbnailSpec fields, with image *paths* (background, face,
// logos) instead of data URLs, plus `font`: the display TTF/OTF (Satori
// can't read variable fonts or WOFF2). Exit 0 and the PNG, or exit 1 and the
// reason on stderr — tools/thumbnailer.py then falls back to Pillow.
import fs from "node:fs";
import path from "node:path";
import React from "react";
import satori from "satori";
import { Resvg, initWasm } from "@resvg/resvg-wasm";
// Embedded in the compiled executable (no native addon to extract or sign).
import wasmFile from "@resvg/resvg-wasm/index_bg.wasm" with { type: "file" };
import { Thumbnail, type ThumbnailSpec } from "./Thumbnail";
import { measurer } from "./text";

const MIME: Record<string, string> = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

function dataUrl(file: string): string {
  const mime = MIME[path.extname(file).toLowerCase()];
  if (!mime) throw new Error(`unsupported image: ${file}`);
  return `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;
}

async function thumbnail(specFile: string, out: string) {
  const raw = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const font = fs.readFileSync(raw.font);
  const spec: ThumbnailSpec = {
    ...raw,
    background: raw.background ? dataUrl(raw.background) : null,
    face: raw.face ? dataUrl(raw.face) : null,
    logos: (raw.logos || []).map(dataUrl),
  };
  const fontData = font.buffer.slice(font.byteOffset, font.byteOffset + font.byteLength);
  const svg = await satori(<Thumbnail spec={spec} measure={measurer(fontData)} />, {
    width: spec.width,
    height: spec.height,
    fonts: [{ name: "Display", data: fontData, weight: 400, style: "normal" }],
  });
  await initWasm(fs.readFileSync(wasmFile));
  const png = new Resvg(svg, { fitTo: { mode: "width", value: spec.width } }).render().asPng();
  fs.writeFileSync(out, png);
}

const [cmd, ...args] = process.argv.slice(2);
try {
  if (cmd === "thumbnail" && args.length === 2) {
    await thumbnail(args[0], args[1]);
  } else if (cmd === "--version") {
    console.log("auto-edit-render 1");
  } else {
    console.error("usage: auto-edit-render thumbnail <spec.json> <out.png>");
    process.exit(2);
  }
} catch (err) {
  console.error(`auto-edit-render: ${err instanceof Error ? err.message : err}`);
  process.exit(1);
}
