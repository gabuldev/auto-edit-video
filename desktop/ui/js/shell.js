// Bits every screen shares: DOM helpers and the engine-status indicator.

import * as api from "./api.js";

export const el = (id) => document.getElementById(id);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export function humanSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes, i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

// The engine indicator at the foot of the sidebar. Any screen reports what its
// last request saw; once one fails, this keeps asking /api/health until the
// engine answers. Still silent after RESTART_AFTER, the app offers to restart
// it (only the installed app can: it's the one that started the engine).
const RESTART_AFTER = 10_000;
const engine = { ok: null, since: 0, poll: null, restarting: false, error: "" };
const canRestart = () => !!window.__TAURI__?.core;

export function setEngine(ok) {
  if (!ok && engine.ok !== false) engine.since = Date.now();
  engine.ok = ok;
  if (ok) {
    engine.error = "";
    clearInterval(engine.poll);
    engine.poll = null;
  } else if (!engine.poll) {
    engine.poll = setInterval(async () => {
      if (await api.health()) setEngine(true);
      else renderEngine(); // the restart offer appears with time
    }, 3000);
  }
  document.querySelectorAll("[data-offline-banner]").forEach((b) => { b.hidden = ok; });
  renderEngine();
}

function renderEngine() {
  const off = engine.ok === false && !engine.restarting;
  const stuck = off && Date.now() - engine.since >= RESTART_AFTER;
  const tone = engine.restarting ? "wait" : engine.ok ? "ok" : off ? "off" : "";
  el("engine-status").className = `engine-status ${tone}`;
  el("engine-label").textContent = engine.restarting ? "Reiniciando o motor…"
    : engine.ok ? "Motor conectado" : off ? "Motor sem resposta" : "Verificando o motor…";
  const sub = engine.error
    || (engine.restarting ? "Leva alguns segundos."
      : !off ? ""
      : !canRestart() ? "Rode auto-edit serve no terminal."
      : stuck ? "Não voltou sozinho." : "Tentando reconectar…");
  el("engine-sub").hidden = !sub;
  el("engine-sub").textContent = sub;
  el("btn-engine-restart").hidden = !(stuck && canRestart());
}

async function restartEngine() {
  engine.restarting = true;
  engine.error = "";
  renderEngine();
  try {
    await window.__TAURI__.core.invoke("restart_engine");
  } catch (err) {
    engine.restarting = false;
    engine.error = String(err?.message || err);
    renderEngine();
    return;
  }
  for (let i = 0; i < 60; i++) { // the engine takes a few seconds to load
    if (await api.health()) {
      location.reload(); // every screen starts clean, without the errors from before
      return;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  engine.restarting = false;
  engine.since = Date.now();
  engine.error = "Subiu, mas não respondeu. Veja o engine.log do app.";
  renderEngine();
}

el("btn-engine-restart").addEventListener("click", restartEngine);

// Leaving a screen with a player: pausing keeps the decoder and the buffered
// 4K file alive in the webview. Dropping the source and calling load() is the
// standard way to make the engine release them.
export function releaseMedia(video) {
  if (!video) return;
  video.pause?.();
  if (video.hasAttribute("src")) {
    video.removeAttribute("src");
    video.load?.();
  }
}
