// Edições — the list of workspaces (the edits), with live per-row progress over SSE.

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";
import { go } from "./router.js";
import { checkSetup } from "./welcome.js";
import { openWithVideo } from "./new-edit.js";
import { chooseVideo, onVideoDrop } from "./video-pick.js";

const STAGES = ["extract", "plan", "review", "evaluate", "execute", "overlay", "caption", "metadata", "thumbnail"];

const streams = new Map(); // video id -> EventSource
const noStream = new Set(); // ids whose SSE 404'd (status says running, engine has no live job)
let timer = null;
let offline = false; // engine dropped after boot: rows stay, actions wait

// Statuses for "now at `cur`". Stages `prev` marks as skipped stay skipped.
function stageMap(cur, prev = {}) {
  const i = STAGES.indexOf(cur);
  const m = {};
  STAGES.forEach((s, idx) => {
    m[s] = prev[s] === "skip" ? "skip"
      : cur === "done" || idx < i ? "complete" : idx === i ? "running" : "pending";
  });
  return m;
}

function typeBadge(t) { return `<span class="badge ${t === "short" ? "short" : "long"}">${t || "?"}</span>`; }

function dots(v) {
  const stages = v.stages || {};
  // Only the stages this video runs: a short never overlays, a long never captions.
  return STAGES.filter((s) => stages[s] !== "skip").map((s) => {
    const st = stages[s];
    let cls = "";
    if (st === "complete") cls = "done";
    else if (s === v.current_stage && v.status === "running") cls = "cur";
    else if (s === v.current_stage && v.status === "failed") cls = "cur err";
    return `<span class="${cls}"></span>`;
  }).join("");
}

function chip(status) {
  const label = { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado", queued: "Na fila", interrupted: "Interrompido" }[status] || status;
  return `<span class="chip ${status}"><span class="d"></span>${label}</span>`;
}

// The video's real name: the one given on Novo edit, else its title once
// metadata ran, the context typed before that, and only then the file name
// (which stays below). Edits from before names existed have none: unchanged.
function name(v) {
  return v.name || v.title || v.context || v.video_name || v.id;
}

// Which step it's on; nothing once it's done (the full bar already says so).
function stageText(stage) {
  return stage === "done" ? "" : stage || "—";
}

function rowHTML(v) {
  const stageColor = v.status === "failed" ? "var(--err)" : v.status === "running" ? "var(--run)" : "var(--faint)";
  const stageLabel = stageText(v.current_stage);
  return `
  <div class="row ${v.status}" data-id="${v.id}">
    <div class="vid">
      ${v.has_thumbnail
        ? `<img class="thumb" loading="lazy" alt="" src="${api.API}/api/videos/${encodeURIComponent(v.id)}/file/thumbnail" />`
        : `<div class="thumb"></div>`}
      <div style="min-width:0">
        <div class="vid-name" title="${escapeHtml(name(v))}">${escapeHtml(name(v))}</div>
        <div class="vid-meta mono">${escapeHtml(v.video_name || v.id)}${v.language ? ` · ${v.language}` : ""}${v.derived_from ? ` · short de ${escapeHtml(v.derived_from)}` : ""}</div>
        <div class="vid-live mono" data-live></div>
      </div>
    </div>
    <div>${typeBadge(v.type)}</div>
    <div class="progress">
      <div class="dots" data-dots>${dots(v)}</div>
      <span class="stage-name mono" data-stage style="color:${stageColor}">${stageLabel}</span>
    </div>
    <div data-chip>${chip(v.status)}</div>
    <div class="row-acts">${actsHTML(v)}</div>
  </div>`;
}

const TRASH = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>`;

// Cancel and delete ask first, in the row itself (a confirm() would block the
// Tauri window). The question survives the 5s re-render.
let armed = null; // { id, act }

function actsHTML(v) {
  if (armed?.id === v.id) {
    const [no, yes] = armed.act === "stop" ? ["Voltar", "Cancelar edição"] : ["Cancelar", "Excluir"];
    return `<button class="btn btn-sm" type="button" data-act="disarm">${no}</button>` +
      `<button class="btn btn-sm btn-danger confirm" type="button" data-act="${armed.act}">${yes}</button>`;
  }
  const stoppable = v.status === "running" || v.status === "queued";
  return [
    v.status === "done" ? `<button class="btn btn-sm" type="button" data-act="result">Ver resultado</button>` : "",
    stoppable ? `<button class="btn btn-sm btn-danger" type="button" data-act="stop">Cancelar</button>` : "",
    `<button class="btn btn-sm btn-icon" type="button" data-act="delete" title="Excluir vídeo" aria-label="Excluir vídeo">${TRASH}</button>`,
  ].join("");
}

function redrawActs(id) {
  const row = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
  const v = lastVideos.find((x) => x.id === id);
  if (row && v) row.querySelector(".row-acts").innerHTML = actsHTML(v);
}

function disarm() {
  const id = armed?.id;
  armed = null;
  if (id) redrawActs(id);
}

async function act(id, what) {
  if (what === "result") { go(`/video/${encodeURIComponent(id)}/resultado`); return; }
  if (what === "disarm") { disarm(); return; }
  if (armed?.id !== id || armed.act !== what) {
    disarm();
    armed = { id, act: what };
    redrawActs(id);
    return;
  }
  armed = null;
  const row = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
  row?.querySelectorAll(".row-acts .btn").forEach((b) => { b.disabled = true; });
  showError("");
  try {
    if (what === "stop") await api.stop(id);
    else { close(id); await api.deleteVideo(id); }
  } catch (err) {
    showError(`Não deu pra ${what === "stop" ? "cancelar" : "excluir"}: ${err.message || err}`);
  }
  refresh();
}

// Empty library: picking or dropping a video goes straight to Novo edit with it.
async function pickFirst() {
  showError("");
  try {
    const path = await chooseVideo();
    if (path) openWithVideo(path);
  } catch (err) {
    showError(String(err.message || err));
  }
}

function showError(msg) {
  el("lib-error").hidden = !msg;
  el("lib-error").textContent = msg;
}

let lastVideos = [];

// Search: case- and accent-insensitive, every word must match somewhere in
// the names a person would look for a video by.
const fold = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const fileOf = (path) => (path ? path.split(/[\\/]/).pop() : "");

function haystack(v) {
  return fold([
    v.name, // the edit's own name
    v.title, // the title metadata wrote (short or YouTube)
    v.context, // what was typed on Novo edit
    v.video_name, fileOf(v.video_path), // the original file, with and without extension
    fileOf(v.output), // the final video, e.g. IMG_3724_final.mp4
    v.derived_from, // a short's long
    v.type,
  ].filter(Boolean).join(" "));
}

function matching(videos) {
  const words = fold(el("lib-search").value).split(/\s+/).filter(Boolean);
  if (!words.length) return videos;
  return videos.filter((v) => { const h = haystack(v); return words.every((w) => h.includes(w)); });
}

function render(videos) {
  lastVideos = videos;
  const shown = matching(videos);
  const query = el("lib-search").value.trim();
  el("rows").innerHTML = shown.map(rowHTML).join("");
  el("empty").hidden = videos.length > 0;
  el("lib-head").hidden = shown.length === 0;
  el("lib-search-box").hidden = videos.length === 0;
  el("lib-noresults").hidden = !(videos.length && !shown.length);
  el("lib-noresults").textContent = `Nada encontrado pra “${query}”.`;
  el("lib-sub").textContent =
    (query ? `${shown.length} de ${videos.length} edições · ` : `${videos.length} ${videos.length === 1 ? "edição" : "edições"} · `) +
    `${videos.filter((v) => v.status === "running").length} em andamento`;
  videos.filter((v) => v.status === "running").forEach(subscribe);
}

// Live progress for a running video via SSE.
function subscribe(v) {
  if (streams.has(v.id) || noStream.has(v.id)) return;
  let es;
  try { es = api.videoEvents(v.id); }
  catch { return; }
  streams.set(v.id, es);
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    const row = document.querySelector(`.row[data-id="${v.id}"]`);
    if (!row) return;
    if (ev.type === "stage") {
      v.current_stage = ev.stage;
      v.stages = stageMap(ev.stage, v.stages);
      row.querySelector("[data-dots]").innerHTML = dots(v);
      row.querySelector("[data-stage]").textContent = stageText(ev.stage);
    } else if (ev.type === "log") {
      const live = row.querySelector("[data-live]");
      live.textContent = ev.line.slice(0, 90);
    } else if (ev.type === "done" || ev.type === "error") {
      close(v.id);
      refresh();
    }
  };
  // A workspace can read as "running" with no live job (the engine was restarted
  // mid-edit). Remember that, or every poll reopens a stream that 404s.
  es.onerror = () => { close(v.id); noStream.add(v.id); };
}

function close(id) {
  streams.get(id)?.close();
  streams.delete(id);
}

export async function refresh() {
  let videos = null;
  if (await api.health()) {
    try { videos = await api.library(); } catch { /* treated as offline below */ }
  }
  offline = videos === null;
  setEngine(!offline);
  if (offline) {
    // The banner says so. Keep what's on screen; an empty library would be a lie.
    if (!lastVideos.length) { el("empty").hidden = true; el("lib-head").hidden = true; }
    return;
  }
  render(videos);
}

let wired = false;

export default {
  id: "library",
  mount() {
    if (!wired) {
      el("rows").addEventListener("click", (e) => {
        const button = e.target.closest("[data-act]");
        if (button) {
          if (!offline) act(button.closest(".row").dataset.id, button.dataset.act);
          return;
        }
        const row = e.target.closest(".row");
        if (row && !offline) go(`/video/${encodeURIComponent(row.dataset.id)}`);
      });
      el("lib-pick").addEventListener("click", pickFirst);
      el("lib-search").addEventListener("input", () => render(lastVideos));
      el("lib-search").addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.currentTarget.value = ""; render(lastVideos); }
      });
      onVideoDrop(el("lib-drop").closest("[data-screen]"), {
        active: () => !el("lib-drop").closest("[data-screen]").hidden && !el("empty").hidden,
        over: (on) => el("lib-drop").classList.toggle("over", on),
        path: openWithVideo,
        fail: showError,
      });
      wired = true;
    }
    clearInterval(timer); // defensive: never two pollers
    checkSetup();
    refresh();
    timer = setInterval(refresh, 5000); // fallback poll: SSE only covers live jobs
  },
  unmount() {
    disarm();
    clearInterval(timer);
    timer = null;
    [...streams.keys()].forEach(close);
    noStream.clear();
  },
};
