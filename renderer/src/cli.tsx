// auto-edit-render — React → PNG without a browser.
//
//   auto-edit-render thumbnail <spec.json> <out.png>
//   auto-edit-render overlay <spec.json> <out_dir>
//   auto-edit-render preview <spec.json> <out.png>
//
// spec.json: the ThumbnailSpec fields, with image *paths* (background, face,
// logos) instead of data URLs, plus `font`: the display TTF/OTF (Satori
// can't read variable fonts or WOFF2). Exit 0 and the PNG, or exit 1 and the
// reason on stderr — tools/thumbnailer.py then falls back to Pillow.
//
// overlay: see OverlaySpec in overlay.tsx. Writes the frames, frames.txt
// (ffmpeg concat list) and overlay.json (where to place the box), and prints
// overlay.json on stdout. tools/overlayer.py composites it.
//
// preview: one frame of a style (the thumbnail, or an overlay over a video
// frame) for the Estilos screen — see auto_edit/styles.py.
import fs from "node:fs";
import React from "react";
import satori from "satori";
import { Resvg, initWasm } from "@resvg/resvg-wasm";
// Embedded in the compiled executable (no native addon to extract or sign).
import wasmFile from "@resvg/resvg-wasm/index_bg.wasm" with { type: "file" };
import { Thumbnail, type ThumbnailSpec } from "./Thumbnail";
import { measurer } from "./text";
import { dataUrl } from "./images";
import { previewOverlay, renderOverlay } from "./overlay";

async function thumbnailSvg(raw: any): Promise<string> {
  const font = fs.readFileSync(raw.font);
  const spec: ThumbnailSpec = {
    ...raw,
    background: raw.background ? dataUrl(raw.background) : null,
    face: raw.face ? dataUrl(raw.face) : null,
    logos: (raw.logos || []).map(dataUrl),
  };
  const fontData = font.buffer.slice(font.byteOffset, font.byteOffset + font.byteLength);
  return satori(<Thumbnail spec={spec} measure={measurer(fontData)} />, {
    width: spec.width,
    height: spec.height,
    fonts: [{ name: "Display", data: fontData, weight: 400, style: "normal" }],
  });
}

function writePng(svg: string, width: number, out: string) {
  fs.writeFileSync(out, new Resvg(svg, { fitTo: { mode: "width", value: width } }).render().asPng());
}

const readSpec = (file: string) => JSON.parse(fs.readFileSync(file, "utf8"));

const [cmd, ...args] = process.argv.slice(2);
try {
  if (cmd === "thumbnail" && args.length === 2) {
    await initWasm(fs.readFileSync(wasmFile));
    const spec = readSpec(args[0]);
    writePng(await thumbnailSvg(spec), spec.width, args[1]);
  } else if (cmd === "overlay" && args.length === 2) {
    await initWasm(fs.readFileSync(wasmFile));
    console.log(JSON.stringify(await renderOverlay(readSpec(args[0]), args[1])));
  } else if (cmd === "preview" && args.length === 2) {
    // {kind: "thumbnail", ...thumbnail spec} or {kind: "lower_third"|"cta", ...OverlayPreviewSpec}
    await initWasm(fs.readFileSync(wasmFile));
    const spec = readSpec(args[0]);
    const svg = spec.kind === "thumbnail" ? await thumbnailSvg({ ...spec, kind: spec.thumbnail_kind || "long" }) : await previewOverlay(spec);
    writePng(svg, spec.width, args[1]);
  } else if (cmd === "--version") {
    console.log("auto-edit-render 3");
  } else {
    console.error("usage: auto-edit-render thumbnail|preview <spec.json> <out.png> | overlay <spec.json> <out_dir>");
    process.exit(2);
  }
} catch (err) {
  console.error(`auto-edit-render: ${err instanceof Error ? err.message : err}`);
  process.exit(1);
}
