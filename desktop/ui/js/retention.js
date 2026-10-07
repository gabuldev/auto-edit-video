// Retenção no YouTube — o card da tela Resultado. Mostra a curva de retenção
// do vídeo publicado, os números aos 30s/60s/metade e as quedas acima do
// normal com o que era dito. Clicar numa queda leva o player até ela.

import * as api from "./api.js";
import { el, escapeHtml } from "./shell.js";

const state = { id: null, data: null, wired: false, busy: false };

const W = 600, H = 170, PAD = { l: 34, r: 8, t: 10, b: 22 };

function mmss(s) {
  const t = Math.max(0, Math.round(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}
const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);

function setError(msg) {
  el("ret-error").hidden = !msg;
  el("ret-error").textContent = msg || "";
}

function chartSVG(d) {
  const curve = d.curve || [];
  if (curve.length < 2) return "";
  const dur = d.duration || curve[curve.length - 1][0];
  // The first points are often above 100% (rewatches): scale to the max seen.
  const top = Math.max(1, ...curve.map((p) => p[1]));
  const x = (t) => PAD.l + (t / dur) * (W - PAD.l - PAD.r);
  const y = (w) => PAD.t + (1 - w / top) * (H - PAD.t - PAD.b);

  const grid = [0, 0.25, 0.5, 0.75, 1].filter((g) => g <= top).map((g) =>
    `<line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(g)}" y2="${y(g)}"/>` +
    `<text class="axis" x="${PAD.l - 6}" y="${y(g) + 3}" text-anchor="end">${Math.round(g * 100)}%</text>`
  ).join("");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) =>
    `<text class="axis" x="${x(f * dur)}" y="${H - 6}" text-anchor="middle">${mmss(f * dur)}</text>`
  ).join("");
  // Close drops would print their numbers on top of each other: stack them.
  let lastX = -Infinity, row = 0;
  const bands = (d.drops || []).map((dr, i) => {
    const cx = (x(dr.start) + x(dr.end)) / 2;
    row = cx - lastX < 14 ? row + 1 : 0;
    lastX = cx;
    return `<rect class="band" x="${x(dr.start)}" y="${PAD.t}" width="${Math.max(2, x(dr.end) - x(dr.start))}" height="${H - PAD.t - PAD.b}" rx="2"/>` +
      `<text class="band-n" x="${cx}" y="${PAD.t + 10 + row * 11}">${i + 1}</text>`;
  }).join("");
  const line = curve.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const area = `${line}L${x(curve[curve.length - 1][0]).toFixed(1)},${y(0)}L${x(curve[0][0]).toFixed(1)},${y(0)}Z`;

  return `
  <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Curva de retenção: ${pct(d.at_30s)} aos 30s, ${pct(d.at_60s)} aos 60s">
    ${grid}${bands}
    <path class="area" d="${area}"/>
    <path class="line" d="${line}"/>
    ${ticks}
    <line class="cross" id="ret-cross" y1="${PAD.t}" y2="${H - PAD.b}" visibility="hidden"/>
    <circle class="dot" id="ret-dot" r="4" visibility="hidden"/>
    <rect id="ret-hit" x="${PAD.l}" y="0" width="${W - PAD.l - PAD.r}" height="${H}" fill="transparent"/>
  </svg>
  <div class="ret-tip" id="ret-tip" hidden></div>`;
}

function wireHover(d) {
  const svg = el("ret-chart").querySelector("svg");
  const hit = el("ret-hit");
  if (!svg || !hit) return;
  const curve = d.curve;
  const dur = d.duration || curve[curve.length - 1][0];
  const top = Math.max(1, ...curve.map((p) => p[1]));
  const move = (ev) => {
    const box = svg.getBoundingClientRect();
    const vx = ((ev.clientX - box.left) / box.width) * W;
    const t = Math.min(dur, Math.max(0, ((vx - PAD.l) / (W - PAD.l - PAD.r)) * dur));
    let near = curve[0];
    for (const p of curve) if (Math.abs(p[0] - t) < Math.abs(near[0] - t)) near = p;
    const px = PAD.l + (near[0] / dur) * (W - PAD.l - PAD.r);
    const py = PAD.t + (1 - near[1] / top) * (H - PAD.t - PAD.b);
    el("ret-cross").setAttribute("x1", px); el("ret-cross").setAttribute("x2", px);
    el("ret-cross").setAttribute("visibility", "visible");
    el("ret-dot").setAttribute("cx", px); el("ret-dot").setAttribute("cy", py);
    el("ret-dot").setAttribute("visibility", "visible");
    const tip = el("ret-tip");
    tip.hidden = false;
    tip.style.left = `${(px / W) * box.width}px`;
    tip.style.top = `${(py / H) * box.height}px`;
    tip.innerHTML = `<b>${pct(near[1])}</b> ainda assistindo · ${mmss(near[0])}`;
  };
  const leave = () => {
    el("ret-cross").setAttribute("visibility", "hidden");
    el("ret-dot").setAttribute("visibility", "hidden");
    el("ret-tip").hidden = true;
  };
  hit.addEventListener("mousemove", move);
  hit.addEventListener("mouseleave", leave);
}

function render(s) {
  state.data = s;
  el("ret-card").hidden = !s.youtube_id;
  if (!s.youtube_id) return;
  const d = s.data;
  const reconnect = s.account && !s.account.connected;
  el("btn-ret-refresh").disabled = state.busy || reconnect;
  el("btn-ret-refresh").textContent = state.busy ? "Buscando…" : d ? "Atualizar" : "Buscar curva";
  if (!d) {
    el("ret-body").hidden = true;
    el("ret-empty").hidden = false;
    el("ret-empty").textContent = reconnect
      ? "Conecte (ou reconecte) o YouTube no card de publicar pra ler a retenção."
      : "Ainda sem curva. O YouTube costuma liberar 24–48h depois de publicar.";
    return;
  }
  el("ret-empty").hidden = true;
  el("ret-body").hidden = false;
  const when = d.fetched_at ? new Date(d.fetched_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
  el("ret-sub").textContent = `onde o público saiu, com o que era dito · atualizado ${when}`;
  el("ret-stats").innerHTML = [
    ["aos 30s", d.at_30s], ["aos 60s", d.at_60s], ["na metade", d.at_half],
  ].map(([k, v]) => `<div class="ret-stat"><b>${pct(v)}</b><span>${k}</span></div>`).join("");
  el("ret-chart").innerHTML = chartSVG(d);
  wireHover(d);
  const drops = d.drops || [];
  el("ret-drops").innerHTML = drops.length
    ? drops.map((dr, i) => `
      <li class="ret-drop" data-t="${dr.start}">
        <span class="n mono">${i + 1}</span>
        <span class="t mono">${mmss(dr.start)}–${mmss(dr.end)}</span>
        <span class="loss mono">-${Math.round(dr.loss * 100)}%</span>
        <span class="said">${dr.preamble ? `<span class="kind">${escapeHtml(dr.preamble)}</span>` : ""}${escapeHtml(dr.text || "(sem fala nesse trecho)")}</span>
      </li>`).join("")
    : `<li class="empty small">Nenhuma queda acima do normal — a curva cai de forma regular.</li>`;
}

async function load() {
  try {
    render(await api.retention(state.id));
  } catch {
    el("ret-card").hidden = true;
  }
}

async function refresh() {
  state.busy = true;
  setError("");
  render(state.data);
  try {
    const s = await api.refreshRetention(state.id);
    state.busy = false;
    render(s);
  } catch (err) {
    state.busy = false;
    render(state.data);
    setError(String(err.message || err));
  }
}

function wire() {
  el("btn-ret-refresh").addEventListener("click", refresh);
  el("ret-drops").addEventListener("click", (e) => {
    const li = e.target.closest(".ret-drop");
    if (!li) return;
    const v = el("res-video");
    // A few seconds before: hear what was said as people left.
    v.currentTime = Math.max(0, Number(li.dataset.t) - 3);
    v.play().catch(() => {});
    v.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

export function mountRetention(id) {
  if (!state.wired) { wire(); state.wired = true; }
  state.id = id;
  state.busy = false;
  el("ret-card").hidden = true;
  setError("");
  load();
}
