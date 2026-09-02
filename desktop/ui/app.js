// Auto-Edit desktop — Biblioteca (thin client over the headless API).
// Works both inside Tauri and opened directly in a browser (against `auto-edit serve`).

const API = (window.AUTO_EDIT_API || "http://127.0.0.1:8760").replace(/\/$/, "");
const STAGES = ["extract", "plan", "review", "execute", "overlay", "caption", "evaluate", "metadata", "thumbnail"];

const el = (id) => document.getElementById(id);
const streams = new Map(); // video id -> EventSource

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

async function health() {
  try {
    const r = await fetch(`${API}/api/health`, { cache: "no-store" });
    return r.ok;
  } catch { return false; }
}

async function fetchLibrary() {
  const r = await fetch(`${API}/api/library`, { cache: "no-store" });
  if (!r.ok) throw new Error("library " + r.status);
  return (await r.json()).videos || [];
}

function setEngine(ok) {
  const box = el("engine-status");
  box.className = "engine-status " + (ok ? "ok" : "off");
  el("engine-label").textContent = ok ? "engine ok" : "offline";
  el("offline").hidden = ok;
}

function typeBadge(t) { return `<span class="badge ${t === "short" ? "short" : "long"}">${t || "?"}</span>`; }

function dots(v) {
  const cur = v.current_stage;
  const stages = v.stages || {};
  return STAGES.map((s) => {
    const st = stages[s];
    let cls = "";
    if (st === "complete") cls = "done";
    else if (s === cur && v.status === "running") cls = "cur";
    else if (s === cur && v.status === "failed") cls = "cur err";
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
  if (streams.has(v.id)) return;
  let es;
  try { es = new EventSource(`${API}/api/videos/${v.id}/events`); }
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
      es.close(); streams.delete(v.id);
      refresh();
    }
  };
  es.onerror = () => { es.close(); streams.delete(v.id); };
}

async function refresh() {
  const ok = await health();
  setEngine(ok);
  if (!ok) { render(SAMPLE); return; }
  try { render(await fetchLibrary()); }
  catch { setEngine(false); render(SAMPLE); }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

el("btn-new").addEventListener("click", () => alert("Tela 'Novo edit' — próximo passo do protótipo."));
el("nav-new").addEventListener("click", () => alert("Tela 'Novo edit' — próximo passo do protótipo."));
el("retry").addEventListener("click", (e) => { e.preventDefault(); refresh(); });

refresh();
setInterval(refresh, 5000); // fallback poll (CI success / new pushes aren't pushed via SSE)
