// Overlays: one animation rendered to transparent PNG frames plus an ffmpeg
// concat list, or one frame of it over a video frame (the style preview).
// Only the overlay's box is drawn, and identical consecutive frames — the
// hold between the entrance and the exit — collapse into one entry with a
// longer duration, so only the moving parts cost a render.
import fs from "node:fs";
import path from "node:path";
import React from "react";
import satori from "satori";
import { Resvg } from "@resvg/resvg-wasm";
import { dataUrl, loadFonts, type FontFiles } from "./images";
import { LAYOUTS } from "./layouts";
import type { Brand, OverlayDef, OverlayKind, StyleTokens } from "./layouts/types";

export type OverlaySpec = {
  kind: OverlayKind;
  video_width: number;
  video_height: number;
  fps: number;
  duration?: number;
  style: StyleTokens;
  brand: Brand; // logo: a file path here
  fonts: FontFiles; // Bold, Regular
};

export type OverlayResult = { x: number; y: number; width: number; height: number; duration: number; frames: number; unique: number };

function resolve(spec: { kind: OverlayKind; style: StyleTokens; video_height: number; duration?: number; brand: Brand }) {
  const layout = LAYOUTS[spec.style.layout] || LAYOUTS.default;
  const def: OverlayDef = layout[spec.kind];
  if (!def) throw new Error(`layout ${spec.style.layout} has no ${spec.kind}`);
  const u = spec.video_height / 1080;
  const size = def.size(spec.style);
  const brand = { ...spec.brand, logo: spec.brand.logo ? dataUrl(spec.brand.logo) : null };
  return { def, u, width: Math.round(size.w * u), height: Math.round(size.h * u), duration: spec.duration || def.duration(spec.style), brand };
}

export async function renderOverlay(spec: OverlaySpec, outDir: string): Promise<OverlayResult> {
  if (!(spec.fps > 0)) throw new Error(`bad fps: ${spec.fps}`);
  const { def, u, width, height, duration, brand } = resolve(spec);
  const fonts = loadFonts(spec.fonts);

  fs.mkdirSync(outDir, { recursive: true });
  const total = Math.max(1, Math.round(duration * spec.fps));
  const list: { file: string; n: number }[] = [];
  let prev = "";
  for (let f = 0; f < total; f++) {
    const el = def.render({ u, t: f / spec.fps, duration, style: spec.style, brand });
    const svg = await satori(el, { width, height, fonts });
    if (svg === prev) {
      list[list.length - 1].n++;
      continue;
    }
    prev = svg;
    const file = `f${String(list.length).padStart(5, "0")}.png`;
    fs.writeFileSync(path.join(outDir, file), new Resvg(svg, { fitTo: { mode: "width", value: width } }).render().asPng());
    list.push({ file, n: 1 });
  }

  // The concat demuxer drops the last entry's duration unless it is repeated.
  const lines = ["ffconcat version 1.0"];
  for (const { file, n } of list) lines.push(`file ${file}`, `duration ${(n / spec.fps).toFixed(6)}`);
  lines.push(`file ${list[list.length - 1].file}`);
  fs.writeFileSync(path.join(outDir, "frames.txt"), lines.join("\n") + "\n");

  const { x, y } = def.place(spec.style, spec.video_width, spec.video_height, width, height, u);
  const result = { x: Math.round(x), y: Math.round(y), width, height, duration, frames: total, unique: list.length };
  fs.writeFileSync(path.join(outDir, "overlay.json"), JSON.stringify(result));
  return result;
}

export type OverlayPreviewSpec = {
  kind: OverlayKind;
  width: number; // the preview frame
  height: number;
  t?: number; // seconds into the animation (default: fully on screen)
  background?: string | null; // a video frame
  style: StyleTokens;
  brand: Brand;
  fonts: FontFiles;
};

/** One moment of the overlay, over a video frame: the style preview. */
export async function previewOverlay(spec: OverlayPreviewSpec): Promise<string> {
  const { def, u, width, height, duration, brand } = resolve({ ...spec, video_height: spec.height });
  const t = spec.t ?? Math.min(1.6, duration / 2);
  const { x, y } = def.place(spec.style, spec.width, spec.height, width, height, u);
  const W = spec.width, H = spec.height;
  const el = (
    <div style={{ width: W, height: H, display: "flex", position: "relative", backgroundColor: "#0b0f14" }}>
      {spec.background ? (
        <img src={dataUrl(spec.background)} width={W} height={H} style={{ position: "absolute", left: 0, top: 0, width: W, height: H, objectFit: "cover" }} />
      ) : (
        <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, display: "flex", backgroundImage: "linear-gradient(135deg, #2a3442, #0b0f14)" }} />
      )}
      <div style={{ position: "absolute", left: x, top: y, width, height, display: "flex" }}>
        {def.render({ u, t, duration, style: spec.style, brand })}
      </div>
    </div>
  );
  return satori(el, { width: W, height: H, fonts: loadFonts(spec.fonts) });
}
