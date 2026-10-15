import React from "react";
import { clamp, outBack, outCubic } from "../../anim";
import { clock, hex, type OverlayDef, type OverlayProps } from "../types";

function LowerThird({ style, brand, u, t, duration }: OverlayProps) {
  const { tin, tout } = clock(t, duration, style.speed);
  const out = outCubic(clamp(1 - tout / 0.45));
  const panelIn = outBack(clamp((tin - 0.12) / 0.5));
  const bar = outCubic(clamp(tin / 0.3));
  const nameIn = outCubic(clamp((tin - 0.3) / 0.4));
  const handleIn = outCubic(clamp((tin - 0.42) / 0.4));
  const avatarIn = outBack(clamp((tin - 0.25) / 0.45));

  const right = style.lower_third.position === "bottom-right";
  const dir = right ? 1 : -1; // where it slides in from
  const r = style.radius * u;
  const accent = style.colors.accent;
  const name = (brand.name || "").trim();

  const avatar = style.lower_third.avatar ? (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 106 * u,
        height: 106 * u,
        borderRadius: 999,
        overflow: "hidden",
        backgroundColor: hex(brand.logo && brand.logo_bg ? brand.logo_bg : accent),
        transform: `scale(${avatarIn}) rotate(${(1 - avatarIn) * -90}deg)`,
        fontFamily: "Bold",
        fontSize: 60 * u,
        color: hex(style.colors.panel),
      }}
    >
      {brand.logo ? <img src={brand.logo} width={106 * u} height={106 * u} style={{ width: 106 * u, height: 106 * u, objectFit: "cover" }} /> : name[0]?.toUpperCase()}
    </div>
  ) : null;

  const accentBar = <div style={{ display: "flex", width: 12 * u, height: 150 * u * bar, backgroundColor: hex(accent), borderRadius: 6 * u }} />;

  const panel = (
    <div style={{ display: "flex", overflow: "hidden", height: 150 * u, margin: right ? `0 ${10 * u}px 0 0` : `0 0 0 ${10 * u}px`, borderRadius: r }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          height: 150 * u,
          padding: avatar ? `0 ${44 * u}px 0 ${22 * u}px` : `0 ${44 * u}px`,
          gap: 26 * u,
          backgroundColor: hex(style.colors.panel, style.panel_opacity),
          borderRadius: r,
          transform: `translateX(${(1 - panelIn) * dir * 720 * u}px)`,
        }}
      >
        {avatar}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontFamily: "Bold", fontSize: 58 * u, lineHeight: 1.1, color: hex(style.colors.text), whiteSpace: "nowrap", opacity: nameIn, transform: `translateY(${(1 - nameIn) * 40 * u}px)` }}>
            {name}
          </div>
          {brand.handle ? (
            <div style={{ display: "flex", fontFamily: "Regular", fontSize: 32 * u, lineHeight: 1.25, color: hex(accent), whiteSpace: "nowrap", opacity: handleIn, transform: `translateY(${(1 - handleIn) * 30 * u}px)` }}>
              {brand.handle}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: right ? "flex-end" : "flex-start",
        opacity: 1 - out,
        transform: `translateX(${dir * out * 120 * u}px)`,
      }}
    >
      {right ? panel : accentBar}
      {right ? accentBar : panel}
    </div>
  );
}

const MARGIN = 60;

export const lowerThird: OverlayDef = {
  size: () => ({ w: 1100, h: 210 }),
  duration: () => 6,
  place: (style, vw, vh, w, h, u) => {
    const p = style.lower_third.position;
    return {
      x: p === "bottom-right" ? vw - w - MARGIN * u : MARGIN * u,
      y: p === "top-left" ? MARGIN * u : vh - h - MARGIN * u,
    };
  },
  render: (p) => <LowerThird {...p} />,
};
