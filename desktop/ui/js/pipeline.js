// Pipeline ao vivo — one workspace: where it is, what it's printing, and the
// one action that unblocks it (retomar a partir de um stage).

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";
import { go } from "./router.js";

const STAGES = ["extract", "plan", "review", "execute", "overlay", "caption", "evaluate", "metadata", "thumbnail"];
const STAGE_HINT = {
  extract: "Whisper transcreve o áudio",
  plan: "o planner decide os cortes",
  review: "o reviewer confere o plano",
  execute: "FFmpeg corta o vídeo",
  overlay: "aplica overlays (só long)",
  caption: "legendas estilo CapCut (só short)",
  evaluate: "o evaluator aprova ou devolve pro plan",
  metadata: "título, descrição e tags",
  thumbnail: "escolhe o frame de capa",
};
const STATUS_LABEL = { complete: "ok", running: "rodando", failed: "falhou", skip: "pulado", pending: "aguardando" };
const MAX_LOG_LINES = 500;

const state = { id: null, data: null, stream: null, timer: null, lines: [], pinned: true };

function stageRow(name, info, current, overall) {
  let status = info?.status || "pending";
  // ralph only marks a stage when it gets that far: a run that died on the way
  // in leaves "pending" behind, which would contradict the header's "Falhou".
  if (name === current && (status === "pending" || status === "running")) {
    if (overall === "failed") status = "failed";
    else if (overall === "running") status = "running";
  }
  const active = name === current && status !== "complete";
  const when = info?.completed_at ? new Date(info.completed_at).toLocaleTimeString("pt-BR") : "";
  return `
  <div class="stage ${status}${active ? " active" : ""}">
    <span class="stage-dot"></span>
    <span class="stage-label">${name}</span>
    <span class="stage-hint">${STAGE_HINT[name] || ""}</span>
    <span class="stage-status mono">${STATUS_LABEL[status] || status}${when ? ` · ${when}` : ""}</span>
  </div>`;
}

function renderStages(d) {
  const detail = d.stage_detail || {};
  el("pipe-stages").innerHTML = STAGES
    .map((s) => stageRow(s, detail[s], d.current_stage, d.status))
    .join("");
}

function renderHead(d) {
  el("pipe-title").textContent = d.video_name || d.id;
  el("pipe-sub").innerHTML =
    `<span class="badge ${d.type === "short" ? "short" : "long"}">${d.type || "?"}</span>` +
    `<span class="chip ${d.status}"><span class="d"></span>${
      { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado" }[d.status] || d.status
    }</span>` +
    `<span class="mono dim">iteração ${d.iteration || 1}/${d.max_iterations || 3}</span>` +
    (d.estimated_tokens ? `<span class="mono dim">~${Number(d.estimated_tokens).toLocaleString("pt-BR")} tokens</span>` : "");

  const facts = [
    ["vídeo", d.video_path],
    ["contexto", d.context],
    ["idioma", d.language],
    ["cortes mantidos", d.plan?.kept_segments != null ? String(d.plan.kept_segments) : null],
    ["output", d.output],
  ].filter(([, v]) => v);
  el("pipe-facts").innerHTML = facts
    .map(([k, v]) => `<div class="fact"><span>${k}</span><span class="mono">${escapeHtml(v)}</span></div>`)
    .join("");
}

function renderResume(d) {
  const sel = el("resume-stage");
  if (!sel.dataset.filled) {
    sel.innerHTML = STAGES.map((s) => `<option value="${s}">${s}</option>`).join("");
    sel.dataset.filled = "1";
  }
  if (d.current_stage && STAGES.includes(d.current_stage)) sel.value = d.current_stage;
  const live = d.status === "running";
  sel.disabled = live;
  el("btn-resume").disabled = live;
  el("resume-note").textContent = live
    ? "rodando — espere terminar pra retomar"
    : "refaz esse stage e todos os seguintes";
}

function pushLog(line) {
  state.lines.push(line);
  if (state.lines.length > MAX_LOG_LINES) state.lines.splice(0, state.lines.length - MAX_LOG_LINES);
  const box = el("pipe-log");
  box.textContent = state.lines.join("\n");
  if (state.pinned) box.scrollTop = box.scrollHeight;
  el("log-empty").hidden = state.lines.length > 0;
}

function openStream(id) {
  closeStream();
  let es;
  try { es = api.videoEvents(id); } catch { return; }
  state.stream = es;
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === "log") pushLog(ev.line);
    else if (ev.type === "stage") { pushLog(`── stage: ${ev.stage} ──`); load(id); }
    else if (ev.type === "done") { pushLog("── terminou ──"); closeStream(); load(id); }
    else if (ev.type === "error") { pushLog(`── falhou${ev.stage ? ` no stage ${ev.stage}` : ""} ──`); closeStream(); load(id); }
  };
  // 404 = nenhum job vivo pra esse workspace (motor reiniciado, por exemplo).
  es.onerror = () => closeStream();
}

function closeStream() {
  state.stream?.close();
  state.stream = null;
}

async function load(id) {
  let d;
  try {
    d = await api.video(id);
  } catch (err) {
    setEngine(false);
    el("pipe-title").textContent = id;
    el("pipe-error").hidden = false;
    el("pipe-error").textContent = `não deu pra ler esse vídeo: ${err.message || err}`;
    return;
  }
  setEngine(true);
  el("pipe-error").hidden = true;
  state.data = d;
  renderHead(d);
  renderStages(d);
  renderResume(d);
}

async function doResume() {
  const stage = el("resume-stage").value;
  el("btn-resume").disabled = true;
  try {
    await api.resume(state.id, stage);
    state.lines = [];
    pushLog(`── retomando de ${stage} ──`);
    openStream(state.id);
    await load(state.id);
  } catch (err) {
    el("pipe-error").hidden = false;
    el("pipe-error").textContent = String(err.message || err);
    el("btn-resume").disabled = false;
  }
}

function wire() {
  el("btn-resume").addEventListener("click", doResume);
  el("pipe-log").addEventListener("scroll", (e) => {
    const box = e.currentTarget;
    state.pinned = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  });
  el("btn-pipe-back").addEventListener("click", () => go("/"));
}

export default {
  id: "pipeline",
  mount({ id }) {
    if (!state.wired) { wire(); state.wired = true; }
    state.id = id;
    state.lines = [];
    state.pinned = true;
    el("pipe-log").textContent = "";
    el("log-empty").hidden = false;
    load(id);
    openStream(id);
    state.timer = setInterval(() => load(id), 5000); // stages, caso o SSE não esteja vivo
  },
  unmount() {
    clearInterval(state.timer);
    state.timer = null;
    closeStream();
  },
};
