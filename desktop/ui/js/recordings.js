// Biblioteca — the videos in the inbox (Configurações → Pastas), subfolders
// included: what each one is, where it sits, whether it was edited, and
// "Editar", which opens Novo edit with it chosen.

import * as api from "./api.js";
import { el, escapeHtml, humanSize, setEngine } from "./shell.js";
import { openWithVideo } from "./new-edit.js";

const state = { data: null, wired: false };

const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// A short is vertical, a long horizontal: "Editar" ticks the matching type.
function shape(r) {
  if (!r.width || !r.height) return null;
  const ratio = r.width / r.height;
  return ratio < 0.9 ? "vertical" : ratio > 1.1 ? "horizontal" : "square";
}
const SHAPE = { vertical: ["Vertical", "short"], horizontal: ["Horizontal", "long"], square: ["Quadrado", null] };

// The edit made from a recording, by its status (the newest first).
const EDIT = { done: "Editado", running: "Editando", queued: "Na fila", failed: "Falhou", idle: "Parado", interrupted: "Parado" };

function duration(seconds) {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
}

function rowHTML(r, i) {
  const kind = shape(r);
  const [label] = SHAPE[kind] || ["—"];
  const dims = r.width ? `${r.width}×${r.height} · ` : "";
  const edit = r.edits[0];
  const editChip = edit
    ? `<a class="chip ${edit.status}" href="#/video/${encodeURIComponent(edit.id)}" title="${escapeHtml(edit.name || edit.id)}${r.edits.length > 1 ? ` (+${r.edits.length - 1})` : ""}"><span class="d"></span>${EDIT[edit.status] || edit.status}${r.edits.length > 1 ? ` ×${r.edits.length}` : ""}</a>`
    : "";
  return `
  <div class="rec-row rec-grid" data-i="${i}">
    <div class="vid">
      <img class="thumb" loading="lazy" alt="" src="${api.recordingThumbUrl(r.path)}" />
      <div style="min-width:0">
        <div class="vid-name" title="${escapeHtml(r.path)}">${escapeHtml(r.name)}</div>
        <div class="vid-meta mono" title="${escapeHtml(r.folder || "")}">${r.folder ? `Pasta: ${escapeHtml(r.folder)}` : "Pasta principal"}</div>
      </div>
    </div>
    <div class="mono">${duration(r.duration)}</div>
    <div class="rec-shape">${kind ? `<span class="badge ${SHAPE[kind][1] || ""}">${label}</span>` : ""}<span class="mono dim">${dims}${r.ext.toUpperCase()}</span></div>
    <div class="mono">${humanSize(r.size)}</div>
    <div class="mono rec-date">${when(r.modified)}</div>
    <div class="row-acts">${editChip}<button class="btn btn-sm btn-primary" type="button" data-edit="${i}">Editar</button></div>
  </div>`;
}

const SKELETON = `
  <div class="rec-row rec-grid skel" aria-hidden="true">
    <div class="vid"><span class="thumb"></span><span class="who" style="display:flex;flex-direction:column;gap:8px;flex:1"><span class="skel-bar" style="width:45%"></span><span class="skel-bar sm" style="width:25%"></span></span></div>
    <span class="skel-bar sm"></span><span class="skel-bar sm"></span><span class="skel-bar sm"></span><span class="skel-bar sm rec-date"></span><span></span>
  </div>`.repeat(5);

function matching(list) {
  const words = fold(el("rec-search").value).split(/\s+/).filter(Boolean);
  if (!words.length) return list;
  return list.filter((r) => {
    const h = fold([r.name, r.folder, r.ext, SHAPE[shape(r)]?.[0], ...r.edits.map((e) => e.name)].filter(Boolean).join(" "));
    return words.every((w) => h.includes(w));
  });
}

function render() {
  const d = state.data;
  const all = d.recordings;
  const shown = matching(all);
  const query = el("rec-search").value.trim();
  el("rec-search-box").hidden = all.length === 0;
  el("rec-head").hidden = shown.length === 0;
  el("rec-rows").innerHTML = shown.map((r) => rowHTML(r, all.indexOf(r))).join("");
  const count = query ? `${shown.length} de ${all.length} vídeos` : `${all.length} vídeo${all.length === 1 ? "" : "s"}`;
  // Just the folder's name here (full path on hover; Configurações shows it whole).
  const folderName = d.folder.split(/[\\/]/).filter(Boolean).pop() || d.folder;
  el("rec-sub").innerHTML = `${count} em <b title="${escapeHtml(d.folder)}">${escapeHtml(folderName)}</b> · <a href="#/config">trocar pasta</a>`;
  let empty = "";
  const pickOther = (label) => `<a class="empty-link" href="#/config">${label}</a>`; // on its own line
  if (!d.exists) empty = `A pasta de entrada não existe mais: ${escapeHtml(d.folder)}.${pickOther("Escolher outra em Configurações")}`;
  else if (!all.length) empty = `Nenhum vídeo nesta pasta (nem nas subpastas). Grave ou copie seus vídeos pra cá.${pickOther("Escolher outra pasta")}`;
  else if (!shown.length) empty = `Nada encontrado pra “${escapeHtml(query)}”.`;
  if (d.truncated) empty = `Mostrando os ${all.length} vídeos mais recentes.`;
  el("rec-empty").hidden = !empty;
  el("rec-empty").innerHTML = empty;
}

async function load() {
  el("rec-error").hidden = true;
  if (!state.data) {
    el("rec-head").hidden = false;
    el("rec-rows").innerHTML = SKELETON;
    el("rec-sub").textContent = "Lendo a pasta de entrada…";
  }
  try {
    state.data = await api.recordings();
    setEngine(true);
  } catch (err) {
    el("rec-error").hidden = false;
    el("rec-error").textContent = `Não deu pra ler a pasta de entrada: ${err.message || err}`;
    if (!state.data) { el("rec-rows").innerHTML = ""; el("rec-head").hidden = true; }
    return;
  }
  render();
}

function wire() {
  el("rec-search").addEventListener("input", () => state.data && render());
  el("rec-search").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.currentTarget.value = ""; if (state.data) render(); }
  });
  el("rec-rows").addEventListener("click", (e) => {
    const button = e.target.closest("[data-edit]");
    if (!button) return;
    const r = state.data.recordings[Number(button.dataset.edit)];
    openWithVideo(r.path, { type: SHAPE[shape(r)]?.[1] || null });
  });
  el("btn-rec-folder").addEventListener("click", () =>
    api.openFolder("inbox").catch((err) => {
      el("rec-error").hidden = false;
      el("rec-error").textContent = String(err.message || err);
    }));
  el("btn-rec-reload").addEventListener("click", load);
}

export default {
  id: "recordings",
  mount() {
    if (!state.wired) { wire(); state.wired = true; }
    load();
  },
};
