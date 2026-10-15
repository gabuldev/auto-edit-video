// A style is a set of overlay components. Adding a style = a folder under
// styles/ that exports a Style, registered in styles/index.ts.
import type React from "react";

export type RGB = [number, number, number];
export const rgb = (c: RGB, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

export type OverlayKind = "lower_third" | "cta";

/** What every overlay component receives. Sizes are designed for a 1080p
 * frame and multiplied by `u` (video height / 1080). */
export type OverlayProps = {
  u: number;
  t: number; // seconds since the overlay appeared
  duration: number;
  accent: RGB;
  name?: string | null;
  handle?: string | null;
};

export type OverlayDef = {
  /** Box drawn, in 1080p units (only this region is rendered, not the frame). */
  size: { w: number; h: number };
  /** Seconds on screen, unless the spec overrides it. */
  duration: number;
  /** Top-left of the box on a vw × vh video. */
  place: (vw: number, vh: number, w: number, h: number, u: number) => { x: number; y: number };
  render: (p: OverlayProps) => React.ReactElement;
};

export type Style = {
  label: string;
  /** Font files the style uses, by family name, relative to the fonts dir. */
  fonts: Record<string, string>;
  overlays: Record<OverlayKind, OverlayDef>;
};
