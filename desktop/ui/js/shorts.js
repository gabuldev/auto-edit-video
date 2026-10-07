// Shorts — trechos de um long pronto que viram short. O clipper propõe,
// você assiste o trecho no player, marca e corta. Cada marcado vira um
// workspace `<nome>_shortN` que roda o pipeline short (legenda + metadata) em
// fila. É o `auto-edit shorts <video> [--pick]` com tela.

import * as api from "./api.js";
import { el, escapeHtml, releaseMedia, setEngine } from "./shell.js";
import { go } from "./router.js";

const state = { id: null, data: null, picked: new Set(), stream: null, lines: [], playing: null, busy: false };

function tc(seconds) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

function maxDur() {
  const v = Number(el("sh-maxdur").value);
  return v > 0 ? v : 90;
}

function show(part) {
  for (const p of ["ineligible", "start", "running", "body"]) el(`sh-${p}`).hidden = p !== part;
  el("btn-sh-find").hidden = part !== "body";
  el("btn-sh-cut").hidden = part !== "body";
}

function clipHTML(c) {
  const on = state.picked.has(c.number);
  const score = c.score == null || c.score === "" ? "–" : c.score;
  const short = c.short;
  const flags = [
    c.overlaps ? `<span class="sh-flag">sobrepõe outro candidato</span>` : "",
    short
      ? `<span class="sh-flag info">já cortado · <a href="#/video/${encodeURIComponent(short.id)}">${escapeHtml(short.id)}</a></span>`
      : "",
  ].join("");
  return `
  <label class="sh-item${on ? " on" : ""}${state.playing === c.number ? " playing" : ""}" data-number="${c.number}">
    <input type="checkbox" data-number="${c.number}" ${on ? "checked" : ""} />
    <span class="sh-body">
      <span class="sh-head">
        <span class="sh-num mono">#${c.number}</span>
        <span class="mono seg-time">${tc(c.start)} → ${tc(c.end)}</span>
        <span class="mono seg-dur">${Math.round(c.duration)}s</span>
        <span class="sh-score mono${Number(score) >= 8 ? " hi" : ""}" title="nota do clipper">${escapeHtml(String(score))}</span>
        <button class="btn btn-sm sh-play" type="button" data-play="${c.number}">▶ assistir</button>
      </span>
      ${c.hook ? `<span class="sh-hook">${escapeHtml(c.hook)}</span>` : ""}
      ${c.text ? `<span class="seg-text">${escapeHtml(c.text)}</span>` : ""}
      ${flags ? `<span class="sh-tags">${flags}</span>` : ""}
      ${short?.overwrite_warning ? `<span class="sh-warn">Cortar de novo sobrescreve: ${escapeHtml(short.overwrite_warning)}</span>` : ""}
    </span>
  </label>`;
}

function renderSelection() {
  const n = state.picked.size;
  const btn = el("btn-sh-cut");
  btn.disabled = state.busy || n === 0;
  btn.textContent = n ? `Cortar ${n} selecionado${n === 1 ? "" : "s"}` : "Cortar selecionados";
}

function renderBody(d) {
  const clips = d.clips || [];
  el("sh-list").innerHTML = clips.map(clipHTML).join("");
  el("sh-none").hidden = clips.length > 0;
  el("sh-none").innerHTML = clips.length
    ? ""
    : `Nenhum candidato passou na validação.${d.notes ? `<br><br><span class="dim">O clipper explicou: ${escapeHtml(d.notes)}</span>` : ""}`;

  const rej = d.rejected || [];
  el("sh-rejected").hidden = rej.length === 0;
  el("sh-rej-count").textContent = rej.length;
  el("sh-rej-list").innerHTML = rej.map((r) => `<li>${escapeHtml(r)}</li>`).join("");

  el("sh-sub").innerHTML =
    `<span class="mono dim">${clips.length} candidato${clips.length === 1 ? "" : "s"}</span>` +
    (clips.filter((c) => c.short).length ? `<span class="mono dim">${clips.filter((c) => c.short).length} já cortado(s)</span>` : "");

  const src = `${api.API}/api/videos/${encodeURIComponent(state.id)}/file/video`;
  if (el("sh-video").getAttribute("src") !== src) el("sh-video").setAttribute("src", src);
  renderSelection();
}

function render(d) {
  state.data = d;
  el("sh-title").textContent = `Shorts — ${d.id}`;
  if (d.job?.status === "running") { show("running"); openStream(); return; }
  if (!d.eligible) {
    show("ineligible");
    el("sh-ineligible").textContent = d.reason || "Este vídeo não pode gerar shorts.";
    el("sh-sub").innerHTML = "";
    return;
  }
  if (!d.has_plan) {
    show("start");
    el("sh-sub").innerHTML = `<span class="mono dim">ainda sem candidatos</span>`;
    return;
  }
  show("body");
  // Seleção sobrevive a um reload, mas só com números que ainda existem.
  const valid = new Set((d.clips || []).map((c) => c.number));
  state.picked = new Set([...state.picked].filter((n) => valid.has(n)));
  renderBody(d);
}

function setError(msg) {
  el("sh-error").hidden = !msg;
  el("sh-error").textContent = msg || "";
}

async function load() {
  try {
    const d = await api.shorts(state.id, maxDur());
    setEngine(true);
    render(d);
  } catch (err) {
    setError(`não deu pra ler os shorts: ${err.message || err}`);
  }
}

function pushLog(line) {
  state.lines.push(line);
  if (state.lines.length > 300) state.lines.splice(0, state.lines.length - 300);
  const box = el("sh-log");
  box.textContent = state.lines.join("\n");
  box.scrollTop = box.scrollHeight;
}

function openStream() {
  if (state.stream) return;
  let es;
  try { es = api.videoEvents(state.id); } catch { return; }
  state.stream = es;
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === "log") pushLog(ev.line);
    else if (ev.type === "done") { closeStream(); load(); }
    else if (ev.type === "error") {
      closeStream();
      setError(ev.message || "o clipper falhou — veja o log");
      load();
    }
  };
  es.onerror = () => { closeStream(); load(); };
}

function closeStream() {
  state.stream?.close();
  state.stream = null;
}

async function find() {
  setError("");
  state.lines = [];
  el("sh-log").textContent = "";
  try {
    await api.findShorts(state.id, maxDur());
    show("running");
    openStream();
  } catch (err) {
    setError(String(err.message || err));
  }
}

async function cut() {
  const pick = [...state.picked].sort((a, b) => a - b);
  if (!pick.length) return;
  state.busy = true;
  setError("");
  renderSelection();
  try {
    await api.cutShorts(state.id, pick, maxDur());
    state.picked.clear();
    go("/"); // os shorts aparecem na biblioteca, em fila
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    state.busy = false;
    renderSelection();
  }
}

// Toca só a janela do candidato: pula pro início e pausa no fim.
function play(number) {
  const c = state.data?.clips?.find((x) => x.number === number);
  if (!c) return;
  const v = el("sh-video");
  state.playing = number;
  v.dataset.end = String(c.end);
  v.currentTime = c.start;
  v.play().catch(() => {});
  el("sh-now").textContent = `#${c.number} · ${tc(c.start)} → ${tc(c.end)}`;
  document.querySelectorAll(".sh-item").forEach((i) => i.classList.toggle("playing", Number(i.dataset.number) === number));
}

function wire() {
  el("sh-list").addEventListener("click", (e) => {
    const p = e.target.closest("[data-play]");
    if (p) { e.preventDefault(); play(Number(p.dataset.play)); }
  });
  el("sh-list").addEventListener("change", (e) => {
    const box = e.target.closest("input[type=checkbox]");
    if (!box) return;
    const n = Number(box.dataset.number);
    if (box.checked) state.picked.add(n); else state.picked.delete(n);
    box.closest(".sh-item").classList.toggle("on", box.checked);
    renderSelection();
  });
  el("sh-video").addEventListener("timeupdate", (e) => {
    const v = e.currentTarget;
    const end = Number(v.dataset.end);
    if (end && v.currentTime >= end) { v.pause(); delete v.dataset.end; }
  });
  el("sh-maxdur").addEventListener("change", () => load());
  el("btn-sh-start").addEventListener("click", find);
  el("btn-sh-find").addEventListener("click", find);
  el("btn-sh-cut").addEventListener("click", cut);
  el("btn-sh-back").addEventListener("click", () => go(`/video/${encodeURIComponent(state.id)}/resultado`));
}

export default {
  id: "shorts",
  mount({ id }) {
    if (!state.wired) { wire(); state.wired = true; }
    if (state.id !== id) { state.picked.clear(); state.lines = []; el("sh-video").removeAttribute("src"); }
    state.id = id;
    state.playing = null;
    setError("");
    load();
  },
  unmount() {
    closeStream();
    releaseMedia(el("sh-video"));
  },
};
