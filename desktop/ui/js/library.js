// Biblioteca — the list of workspaces, with live per-row progress over SSE.

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";
import { go } from "./router.js";

const STAGES = ["extract", "plan", "review", "execute", "overlay", "caption", "evaluate", "metadata", "thumbnail"];

const streams = new Map(); // video id -> EventSource
const noStream = new Set(); // ids whose SSE 404'd (status says running, engine has no live job)
let timer = null;
let offline = false; // sample rows are on screen: they have no workspace to open

// Shown only when the engine is unreachable, so you still see the design.
const SAMPLE = [
  { id: "merged", video_name: "merged.mp4 — setup 4K no carro", type: "long", status: "running", current_stage: "execute", stages: stageMap("execute") },
  { id: "flutter", video_name: "flutter-state-management.mov", type: "long", status: "idle", current_stage: "review", stages: stageMap("review") },
  { id: "macbook", video_name: "review-macbook-m4-dev.mp4", type: "long", status: "done", current_stage: "done", stages: stageMap("done") },
];

function stageMap(cur) {
  const i = STAGES.indexOf(cur);
  const m = {};
  STAGES.forEach((s, idx) => { m[s] = cur === "done" ? "complete" : idx < i ? "complete" : idx === i ? "running" : "pending"; });
  return m;
}

function typeBadge(t) { return `<span class="badge ${t === "short" ? "short" : "long"}">${t || "?"}</span>`; }

function dots(v) {
  const stages = v.stages || {};
  return STAGES.map((s) => {
    const st = stages[s];
    let cls = "";
    if (st === "complete") cls = "done";
    else if (s === v.current_stage && v.status === "running") cls = "cur";
    else if (s === v.current_stage && v.status === "failed") cls = "cur err";
    return `<span class="${cls}"></span>`;
  }).join("");
}

function chip(status) {
  const label = { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado" }[status] || status;
  return `<span class="chip ${status}"><span class="d"></span>${label}</span>`;
}

function rowHTML(v) {
  const stageColor = v.status === "failed" ? "var(--err)" : v.status === "running" ? "var(--run)" : "var(--faint)";
  const stageLabel = v.current_stage === "done" ? "done" : v.current_stage || "—";
  return `
  <div class="row ${v.status}" data-id="${v.id}">
    <div class="vid">
      <div class="thumb"></div>
      <div style="min-width:0">
        <div class="vid-name">${escapeHtml(v.video_name || v.id)}</div>
        <div class="vid-meta mono" data-meta>${v.language || ""}${v.output ? " · output pronto" : ""}</div>
      </div>
    </div>
    <div>${typeBadge(v.type)}</div>
    <div class="progress">
      <div class="dots" data-dots>${dots(v)}</div>
      <span class="stage-name mono" data-stage style="color:${stageColor}">${stageLabel}</span>
    </div>
    <div data-chip>${chip(v.status)}</div>
  </div>`;
}

function render(videos) {
  el("rows").innerHTML = videos.map(rowHTML).join("");
  el("empty").hidden = videos.length > 0;
  el("lib-sub").textContent =
    `${videos.length} vídeo${videos.length === 1 ? "" : "s"} · ` +
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
      v.stages = stageMap(ev.stage);
      row.querySelector("[data-dots]").innerHTML = dots(v);
      row.querySelector("[data-stage]").textContent = ev.stage;
    } else if (ev.type === "log") {
      row.querySelector("[data-meta]").textContent = ev.line.slice(0, 60);
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
  const ok = await api.health();
  setEngine(ok);
  offline = !ok;
  if (!ok) { render(SAMPLE); return; }
  try { render(await api.library()); }
  catch { setEngine(false); offline = true; render(SAMPLE); }
}

let wired = false;

export default {
  id: "library",
  mount() {
    if (!wired) {
      el("rows").addEventListener("click", (e) => {
        const row = e.target.closest(".row");
        if (row && !offline) go(`/video/${encodeURIComponent(row.dataset.id)}`);
      });
      wired = true;
    }
    refresh();
    timer = setInterval(refresh, 5000); // fallback poll: SSE only covers live jobs
  },
  unmount() {
    clearInterval(timer);
    timer = null;
    [...streams.keys()].forEach(close);
    noStream.clear();
  },
};
