import React from "react";
import { outBack, outCubic, seg } from "../../anim";
import { rgb, type OverlayDef, type OverlayProps } from "../types";
import { PANEL } from "./theme";

function LowerThird({ name, handle, accent, u, t, duration }: OverlayProps) {
  const out = outCubic(seg(t, duration - 0.45, 0.45));
  const panelIn = outBack(seg(t, 0.12, 0.5));
  const bar = outCubic(seg(t, 0, 0.3));
  const nameIn = outCubic(seg(t, 0.3, 0.4));
  const handleIn = outCubic(seg(t, 0.42, 0.4));
  const avatar = outBack(seg(t, 0.25, 0.45));
  const label = (name || "").trim();

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", opacity: 1 - out, transform: `translateX(${-out * 120 * u}px)` }}>
      <div style={{ display: "flex", width: 12 * u, height: 150 * u * bar, backgroundColor: rgb(accent), borderRadius: 6 * u }} />
      <div style={{ display: "flex", overflow: "hidden", height: 150 * u, marginLeft: 10 * u, borderRadius: 22 * u }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            height: 150 * u,
            padding: `0 ${44 * u}px 0 ${22 * u}px`,
            gap: 26 * u,
            backgroundColor: PANEL,
            borderRadius: 22 * u,
            transform: `translateX(${(panelIn - 1) * 720 * u}px)`,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 106 * u,
              height: 106 * u,
              borderRadius: 999,
              backgroundColor: rgb(accent),
              transform: `scale(${avatar}) rotate(${(1 - avatar) * -90}deg)`,
              fontFamily: "Bold",
              fontSize: 60 * u,
              color: PANEL,
            }}
          >
            {label[0]?.toUpperCase()}
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", fontFamily: "Bold", fontSize: 58 * u, lineHeight: 1.1, color: "#fff", whiteSpace: "nowrap", opacity: nameIn, transform: `translateY(${(1 - nameIn) * 40 * u}px)` }}>
              {label}
            </div>
            {handle ? (
              <div style={{ display: "flex", fontFamily: "Semi", fontSize: 32 * u, lineHeight: 1.25, color: rgb(accent), whiteSpace: "nowrap", opacity: handleIn, transform: `translateY(${(1 - handleIn) * 30 * u}px)` }}>
                {handle}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export const lowerThird: OverlayDef = {
  size: { w: 1100, h: 210 },
  duration: 6,
  place: (_vw, vh, _w, h, u) => ({ x: 60 * u, y: vh - h - 60 * u }),
  render: (p) => <LowerThird {...p} />,
};
