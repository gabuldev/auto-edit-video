// Renders one overlay animation to transparent PNG frames plus an ffmpeg
// concat list. Only the overlay's box is drawn (not the whole frame), and
// identical consecutive frames — the hold between the entrance and the exit —
// collapse into one entry with a longer duration, so only the moving parts
// cost a render.
import fs from "node:fs";
import path from "node:path";
import satori from "satori";
import { Resvg } from "@resvg/resvg-wasm";
import { STYLES } from "./styles";
import type { OverlayKind, RGB } from "./styles/types";

export type OverlaySpec = {
  kind: OverlayKind;
  style?: string;
  video_width: number;
  video_height: number;
  fps: number;
  duration?: number;
  accent: RGB;
  name?: string | null;
  handle?: string | null;
  fonts_dir: string;
};

export type OverlayResult = { x: number; y: number; width: number; height: number; duration: number; frames: number; unique: number };

export async function renderOverlay(spec: OverlaySpec, outDir: string): Promise<OverlayResult> {
  const style = STYLES[spec.style || "default"];
  if (!style) throw new Error(`unknown style: ${spec.style}`);
  const def = style.overlays[spec.kind];
  if (!def) throw new Error(`style ${spec.style || "default"} has no ${spec.kind}`);
  if (!(spec.fps > 0)) throw new Error(`bad fps: ${spec.fps}`);

  const u = spec.video_height / 1080;
  const width = Math.round(def.size.w * u);
  const height = Math.round(def.size.h * u);
  const duration = spec.duration || def.duration;
  const fonts = Object.entries(style.fonts).map(([name, file]) => ({
    name,
    data: fs.readFileSync(path.join(spec.fonts_dir, file)),
    weight: 400 as const,
    style: "normal" as const,
  }));

  fs.mkdirSync(outDir, { recursive: true });
  const total = Math.max(1, Math.round(duration * spec.fps));
  const list: { file: string; n: number }[] = [];
  let prev = "";
  for (let f = 0; f < total; f++) {
    const props = { u, t: f / spec.fps, duration, accent: spec.accent, name: spec.name, handle: spec.handle };
    const svg = await satori(def.render(props), { width, height, fonts });
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

  const { x, y } = def.place(spec.video_width, spec.video_height, width, height, u);
  const result = { x: Math.round(x), y: Math.round(y), width, height, duration, frames: total, unique: list.length };
  fs.writeFileSync(path.join(outDir, "overlay.json"), JSON.stringify(result));
  return result;
}
