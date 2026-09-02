// Revisar cortes — o que sobrou do vídeo, com o que é dito em cada trecho.
// Desmarcar um trecho e salvar reescreve o reviewed_plan.json; "salvar e
// recortar" ainda retoma o pipeline a partir do execute.

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";
import { go } from "./router.js";

const state = { id: null, plan: null, keep: new Set(), busy: false };

function tc(seconds) {
  if (seconds == null) return "—";
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rest = (s - m * 60).toFixed(1).padStart(4, "0");
  return `${String(m).padStart(2, "0")}:${rest}`;
}

function dur(seconds) {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m${String(s).padStart(2, "0")}s` : `${s}s`;
}

function segmentHTML(seg) {
  const on = state.keep.has(seg.index);
  return `
  <label class="seg${on ? "" : " off"}">
    <input type="checkbox" data-index="${seg.index}" ${on ? "checked" : ""} />
    <span class="seg-body">
      <span class="seg-head">
        <span class="mono seg-time">${tc(seg.start)} → ${tc(seg.end)}</span>
        <span class="mono seg-dur">${dur(seg.duration)}</span>
        ${seg.summary ? `<span class="seg-summary">${escapeHtml(seg.summary)}</span>` : ""}
      </span>
      ${seg.text ? `<span class="seg-text">${escapeHtml(seg.text)}</span>` : `<span class="seg-text dimmed">(sem transcrição para este trecho)</span>`}
    </span>
  </label>`;
}

function cutHTML(cut) {
  return `
  <div class="cut">
    <span class="mono seg-time">${tc(cut.start)} → ${tc(cut.end)}</span>
    <span class="mono seg-dur">${dur(cut.duration)}</span>
    <span class="cut-reason">${escapeHtml(cut.reason || "—")}</span>
    ${cut.type ? `<span class="cut-type mono">${escapeHtml(cut.type)}</span>` : ""}
  </div>`;
}

function renderTotals() {
  const p = state.plan;
  const kept = p.kept_segments.filter((s) => state.keep.has(s.index));
  const total = kept.reduce((acc, s) => acc + s.duration, 0);
  el("cuts-sub").innerHTML =
    `<span>${kept.length} de ${p.kept_segments.length} trechos</span>` +
    `<span class="mono dim">${dur(total)} de corte final</span>` +
    (p.duration ? `<span class="mono dim">bruto ${dur(p.duration)}</span>` : "") +
    (p.editable ? "" : `<span class="mono dim">rascunho do planner (${escapeHtml(p.source)}) — salvar cria o reviewed_plan</span>`);
  el("btn-save").disabled = state.busy || kept.length === 0;
  el("btn-save-cut").disabled = state.busy || kept.length === 0;
}

function render(p) {
  state.plan = p;
  el("cuts-title").textContent = p.id;
  el("cuts-list").innerHTML = p.kept_segments.map(segmentHTML).join("");
  el("cuts-empty").hidden = p.kept_segments.length > 0;

  const cuts = p.cuts || [];
  el("cuts-removed").innerHTML = cuts.map(cutHTML).join("");
  el("removed-box").hidden = cuts.length === 0;
  el("removed-count").textContent = `${cuts.length}`;

  const blocks = p.dropped_blocks;
  const list = Array.isArray(blocks) ? blocks : blocks ? [blocks] : [];
  el("blocks-box").hidden = list.length === 0;
  el("cuts-blocks").innerHTML = list
    .map((b) => `<li>${escapeHtml(typeof b === "string" ? b : b.reason || JSON.stringify(b))}</li>`)
    .join("");

  renderTotals();
}

function setError(msg) {
  el("cuts-error").hidden = !msg;
  el("cuts-error").textContent = msg || "";
}

function keptPayload() {
  return state.plan.kept_segments
    .filter((s) => state.keep.has(s.index))
    .map((s) => ({ start: s.start, end: s.end, summary: s.summary || undefined }));
}

async function save(thenCut) {
  state.busy = true;
  setError("");
  renderTotals();
  try {
    const updated = await api.savePlan(state.id, keptPayload());
    state.keep = new Set(updated.kept_segments.map((s) => s.index));
    render(updated);
    if (thenCut) {
      await api.resume(state.id, "execute");
      go(`/video/${encodeURIComponent(state.id)}`);
    }
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    state.busy = false;
    renderTotals();
  }
}

async function load(id) {
  try {
    const p = await api.plan(id);
    setEngine(true);
    el("cuts-body").hidden = false;
    el("cuts-none").hidden = true;
    state.keep = new Set(p.kept_segments.map((s) => s.index));
    render(p);
  } catch (err) {
    const missing = String(err.message || err).includes("no_plan");
    el("cuts-body").hidden = true;
    el("cuts-none").hidden = false;
    el("cuts-title").textContent = id;
    el("cuts-sub").textContent = "";
    if (!missing) { setEngine(false); setError(String(err.message || err)); }
  }
}

function wire() {
  el("cuts-list").addEventListener("change", (e) => {
    const box = e.target.closest("input[type=checkbox]");
    if (!box) return;
    const i = Number(box.dataset.index);
    if (box.checked) state.keep.add(i); else state.keep.delete(i);
    box.closest(".seg").classList.toggle("off", !box.checked);
    renderTotals();
  });
  el("btn-save").addEventListener("click", () => save(false));
  el("btn-save-cut").addEventListener("click", () => save(true));
  el("btn-cuts-back").addEventListener("click", () => go(`/video/${encodeURIComponent(state.id)}`));
}

export default {
  id: "cuts",
  mount({ id }) {
    if (!state.wired) { wire(); state.wired = true; }
    state.id = id;
    setError("");
    load(id);
  },
};
