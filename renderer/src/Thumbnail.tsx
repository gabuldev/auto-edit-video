// The thumbnail as a React component. Satori supports flexbox and a subset
// of CSS: every element with several children needs display:flex, and blurs
// (text-shadow/box-shadow radius) cost seconds in resvg — keep shadows hard.
import React from "react";
import { fit, type Measurer } from "./text";

export type RGB = [number, number, number];

export type ThumbnailSpec = {
  kind: "short" | "long";
  width: number;
  height: number;
  main_text: string;
  sub_text?: string | null;
  accent: RGB;
  background?: string | null; // data: URL
  face?: string | null; // data: URL, transparent PNG
  logos?: string[]; // data: URLs
};

const rgb = (c: RGB, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

// The last word is the hook: it takes the accent color.
function Headline({ words, size, accent, align }: { words: string[]; size: number; accent: RGB; align: "center" | "flex-start" }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", justifyContent: align, columnGap: size * 0.22 }}>
      {words.map((w, i) => (
        <span
          key={i}
          style={{
            fontFamily: "Display",
            fontSize: size,
            lineHeight: 1.02,
            color: i === words.length - 1 && words.length > 1 ? rgb(accent) : "#fff",
            textShadow: `0 ${size * 0.06}px 0 rgba(0,0,0,.9)`,
          }}
        >
          {w}
        </span>
      ))}
    </div>
  );
}

function Chip({ text, size, accent }: { text: string; size: number; accent: RGB }) {
  return (
    <div
      style={{
        display: "flex",
        transform: "rotate(-2.5deg)",
        whiteSpace: "nowrap",
        backgroundColor: rgb(accent),
        color: "#0b0f0d",
        fontFamily: "Display",
        fontSize: size,
        lineHeight: 1,
        padding: `${size * 0.22}px ${size * 0.45}px ${size * 0.26}px`,
        borderRadius: size * 0.22,
        boxShadow: `0 ${size * 0.12}px 0 rgba(0,0,0,.55)`,
      }}
    >
      {text}
    </div>
  );
}

export function Thumbnail({ spec, measure }: { spec: ThumbnailSpec; measure: Measurer }) {
  const { width: W, height: H, accent } = spec;
  const short = spec.kind === "short";
  const main = spec.main_text.toUpperCase().trim();
  const sub = spec.sub_text?.toUpperCase().trim() || null;
  const hasFace = !short && !!spec.face;

  // Short: centered in the upper safe zone (Instagram's grid crops 9:16 to the
  // middle square; the face sits around 55–65%). Long: left column.
  const box = short ? W * 0.86 : W * 0.56;
  const mainSize = short
    ? fit(main, { box, maxH: H * 0.22, max: W * 0.2, min: W * 0.08, maxLines: 3 }, measure)
    : fit(main, { box, maxH: H * 0.6, max: H * 0.26, min: H * 0.1, maxLines: 3 }, measure);
  // The chip stays on one line: half the headline at most, never wider than the box.
  const subSize = sub
    ? Math.min(Math.round(mainSize * 0.5), fit(sub, { box: box * 0.9 - mainSize * 0.5, maxH: Infinity, max: mainSize, min: 10, maxLines: 1 }, measure))
    : 0;

  const fill = { position: "absolute" as const, left: 0, top: 0, width: W, height: H, display: "flex" };

  return (
    <div style={{ width: W, height: H, display: "flex", position: "relative", backgroundColor: "#0b0f14" }}>
      {spec.background ? (
        <img src={spec.background} width={W} height={H} style={{ ...fill, objectFit: "cover" }} />
      ) : (
        <div style={{ ...fill, backgroundImage: `linear-gradient(135deg, ${rgb(accent, 0.35)}, #0b0f14 60%)` }} />
      )}
      {/* darken where the text sits, keep the face bright */}
      <div
        style={{
          ...fill,
          backgroundImage: short
            ? "linear-gradient(180deg, rgba(0,0,0,.15) 0%, rgba(0,0,0,.72) 22%, rgba(0,0,0,.55) 48%, rgba(0,0,0,0) 62%, rgba(0,0,0,0) 85%, rgba(0,0,0,.45) 100%)"
            : "linear-gradient(90deg, rgba(0,0,0,.88) 0%, rgba(0,0,0,.7) 42%, rgba(0,0,0,.1) 70%, rgba(0,0,0,0) 100%)",
        }}
      />
      {/* accent glow in the corner */}
      <div
        style={{
          position: "absolute",
          display: "flex",
          left: short ? -W * 0.3 : -W * 0.15,
          top: short ? -H * 0.05 : -H * 0.3,
          width: short ? W * 1.1 : W * 0.7,
          height: short ? W * 1.1 : W * 0.7,
          backgroundImage: `radial-gradient(circle, ${rgb(accent, 0.28)} 0%, ${rgb(accent, 0)} 65%)`,
        }}
      />
      {hasFace ? (
        <img
          src={spec.face!}
          height={H * 0.78}
          style={{ position: "absolute", right: 0, bottom: 0, height: H * 0.78, objectFit: "contain" }}
        />
      ) : null}
      <div style={{ position: "absolute", display: "flex", left: 0, top: 0, width: short ? W : 14, height: short ? 14 : H, backgroundColor: rgb(accent) }} />

      {spec.logos?.length ? (
        <div
          style={{
            position: "absolute",
            display: "flex",
            gap: H * 0.025,
            top: short ? H * 0.06 : H * 0.07,
            ...(short || hasFace ? { left: short ? (W - box) / 2 : W * 0.06 } : { right: W * 0.04 }),
          }}
        >
          {spec.logos.map((src, i) => (
            <img key={i} src={src} height={short ? W * 0.11 : H * 0.12} style={{ height: short ? W * 0.11 : H * 0.12, objectFit: "contain" }} />
          ))}
        </div>
      ) : null}

      <div
        style={{
          position: "absolute",
          display: "flex",
          flexDirection: "column",
          alignItems: short ? "center" : "flex-start",
          justifyContent: "center",
          left: short ? (W - box) / 2 : W * 0.06,
          top: short ? H * 0.17 : 0,
          width: box,
          height: short ? H * 0.3 : H,
          gap: mainSize * 0.28,
        }}
      >
        <Headline words={main.split(/\s+/)} size={mainSize} accent={accent} align={short ? "center" : "flex-start"} />
        {sub ? <Chip text={sub} size={subSize} accent={accent} /> : null}
      </div>
    </div>
  );
}
