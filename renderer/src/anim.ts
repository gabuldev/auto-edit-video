// Easing for frame-by-frame animation: every overlay is a pure function of
// `t` (seconds since it appeared), so these map time to 0→1 progress.
export const clamp = (x: number) => Math.max(0, Math.min(1, x));
export const outCubic = (x: number) => 1 - Math.pow(1 - clamp(x), 3);
export const outBack = (x: number) => {
  const c = 1.70158, p = clamp(x) - 1;
  return 1 + (c + 1) * p * p * p + c * p * p;
};
/** 0→1 over [start, start + length] seconds. */
export const seg = (t: number, start: number, length: number) => clamp((t - start) / length);
