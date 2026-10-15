import React from "react";
import { clamp, outBack, outCubic, seg } from "../../anim";
import type { OverlayDef, OverlayProps } from "../types";
import { PANEL } from "./theme";

const ICONS = {
  like: (s: number, c: string) => (
    <svg width={s} height={s} viewBox="0 0 24 24">
      <path fill={c} d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.3c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" />
    </svg>
  ),
  subscribe: (s: number, c: string) => (
    <svg width={s} height={s} viewBox="0 0 24 24">
      <rect x="1" y="4" width="22" height="16" rx="5" fill={c} />
      <path fill="#fff" d="M10 8.5v7l6-3.5z" />
    </svg>
  ),
  bell: (s: number, c: string) => (
    <svg width={s} height={s} viewBox="0 0 24 24">
      <path fill={c} d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
    </svg>
  ),
};

const STEPS: { icon: keyof typeof ICONS; text: string; color: string }[] = [
  { icon: "like", text: "DEIXE O LIKE!", color: "#22d3ee" },
  { icon: "subscribe", text: "SE INSCREVA!", color: "#ff3b3b" },
  { icon: "bell", text: "ATIVE O SINO!", color: "#facc15" },
];

function Cta({ u, t, duration }: OverlayProps) {
  const enter = outBack(seg(t, 0, 0.4));
  const out = outCubic(seg(t, duration - 0.35, 0.35));
  const per = duration / STEPS.length;
  const i = Math.min(STEPS.length - 1, Math.floor(t / per));
  const local = t - i * per;
  const step = STEPS[i];
  const pop = outBack(seg(local, i === 0 ? 0.2 : 0, 0.35)); // the icon pops on every step
  const textIn = outCubic(seg(local, i === 0 ? 0.3 : 0.08, 0.3));
  const wiggle = step.icon === "bell" ? Math.sin(local * 22) * 14 * (1 - clamp(local / 1.2)) : 0; // the bell rings

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 22 * u,
          height: 104 * u,
          padding: `0 ${40 * u}px 0 ${30 * u}px`,
          backgroundColor: PANEL,
          borderRadius: 22 * u,
          border: `${3 * u}px solid ${step.color}`,
          boxShadow: `0 ${8 * u}px 0 rgba(0,0,0,.35)`, // hard shadow: a blur costs seconds in resvg
          opacity: 1 - out,
          transform: `scale(${(0.5 + 0.5 * enter) * (1 - 0.3 * out)})`,
        }}
      >
        <div style={{ display: "flex", transform: `scale(${pop}) rotate(${wiggle}deg)` }}>{ICONS[step.icon](58 * u, step.color)}</div>
        <div style={{ display: "flex", fontFamily: "Bold", fontSize: 40 * u, color: "#fff", whiteSpace: "nowrap", opacity: textIn, transform: `translateX(${(1 - textIn) * 24 * u}px)` }}>
          {step.text}
        </div>
      </div>
    </div>
  );
}

export const cta: OverlayDef = {
  size: { w: 620, h: 190 },
  duration: 8,
  place: (vw, vh, w, h) => ({ x: (vw - w) / 2, y: vh - h - vh * 0.03 }),
  render: (p) => <Cta {...p} />,
};
