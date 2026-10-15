// A style is data (StyleTokens: colors, fonts, positions, texts) applied to
// a layout — a set of React components. Presets, the person's own styles and
// the ones an AI writes are all just tokens; a new look that tokens can't
// express is a new layout folder, registered in layouts/index.ts.
import type React from "react";

export type RGB = [number, number, number];

export function hex(h: string, a = 1): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(h || "");
  const n = m ? parseInt(m[1], 16) : 0xffffff;
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function rgbOf(h: string): RGB {
  const n = parseInt((/^#?([0-9a-f]{6})$/i.exec(h || "") || ["", "00d6ff"])[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export type OverlayKind = "lower_third" | "cta";
export type CtaIcon = "like" | "subscribe" | "bell" | "comment";

/** Validated and filled in by auto_edit/styles.py — every field is present. */
export type StyleTokens = {
  layout: string;
  colors: { accent: string; panel: string; text: string };
  panel_opacity: number;
  radius: number; // px on a 1080p frame
  speed: number; // animation speed multiplier
  lower_third: { position: "bottom-left" | "bottom-right" | "top-left"; avatar: boolean };
  cta: { position: "bottom-center" | "bottom-right" | "top-right"; steps: { icon: CtaIcon; text: string; color: string | null }[] };
};

export type Brand = {
  name?: string | null;
  handle?: string | null;
  logo?: string | null; // data: URL
  logo_bg?: string | null; // behind the logo; null → the style's accent
};

/** What every overlay component receives. Sizes are designed for a 1080p
 * frame and multiplied by `u` (video height / 1080). Fonts are registered as
 * "Bold" and "Regular" (the style's text font). */
export type OverlayProps = {
  u: number;
  t: number; // seconds since the overlay appeared
  duration: number;
  style: StyleTokens;
  brand: Brand;
};

export type OverlayDef = {
  /** Box drawn, in 1080p units (only this region is rendered, not the frame). */
  size: (style: StyleTokens) => { w: number; h: number };
  /** Seconds on screen, unless the spec overrides it. */
  duration: (style: StyleTokens) => number;
  /** Top-left of the box on a vw × vh video. */
  place: (style: StyleTokens, vw: number, vh: number, w: number, h: number, u: number) => { x: number; y: number };
  render: (p: OverlayProps) => React.ReactElement;
};

export type Layout = Record<OverlayKind, OverlayDef>;

/** Entrance/exit progress with the style's speed: `tin` grows from the
 * start, `tout` shrinks to 0 at the end. */
export function clock(t: number, duration: number, speed: number) {
  return { tin: t * speed, tout: (duration - t) * speed };
}
