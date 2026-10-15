import fs from "node:fs";
import path from "node:path";

const MIME: Record<string, string> = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

/** Satori only takes images inline. */
export function dataUrl(file: string): string {
  const mime = MIME[path.extname(file).toLowerCase()];
  if (!mime) throw new Error(`unsupported image: ${file}`);
  return `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;
}

export type FontFiles = Record<string, string>; // family name → TTF/OTF path

export function loadFonts(files: FontFiles) {
  return Object.entries(files).map(([name, file]) => ({
    name,
    data: fs.readFileSync(file),
    weight: 400 as const,
    style: "normal" as const,
  }));
}
