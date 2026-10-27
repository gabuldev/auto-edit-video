// Pipeline ao vivo — one workspace: where it is, what it's printing, and the
// one action that unblocks it (retomar a partir de um stage).

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";
import { go } from "./router.js";

const STAGES = ["extract", "plan", "review", "evaluate", "execute", "overlay", "caption", "metadata", "thumbnail"];
const STAGE_HINT = {
  extract: "Whisper transcreve o áudio",
  plan: "O planner decide os cortes",
  review: "O reviewer confere o plano",
  execute: "FFmpeg corta o vídeo",
  overlay: "Lower third e CTA na tela",
  caption: "Legenda animada estilo CapCut",
  evaluate: "Julga o corte planejado (antes de renderizar) e aprova ou devolve pro plan",
  metadata: "Título, descrição e tags",
  thumbnail: "Escolhe o frame de capa",
};
// The dot says the state (a spinner while running); read aloud, not printed.
const STATUS_LABEL = { complete: "concluído", running: "rodando", failed: "falhou", pending: "aguardando" };
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
  // Only when it finished; a failure is the one state worth spelling out.
  const when = info?.completed_at ? new Date(info.completed_at).toLocaleTimeString("pt-BR") : "";
  const right = status === "complete" ? when : status === "failed" ? "falhou" : "";
  return `
  <div class="stage ${status}${active ? " active" : ""}">
    <span class="stage-dot" role="img" aria-label="${STATUS_LABEL[status] || status}"></span>
    <span class="stage-label">${name}</span>
    <span class="stage-hint">${STAGE_HINT[name] || ""}</span>
    <span class="stage-status mono">${right}</span>
  </div>`;
}

// The stages this video runs: a short never overlays, a long never captions.
function stagesOf(d) {
  const detail = d.stage_detail || {};
  return STAGES.filter((s) => detail[s]?.status !== "skip");
}

function renderStages(d) {
  const detail = d.stage_detail || {};
  el("pipe-stages").innerHTML = stagesOf(d)
    .map((s) => stageRow(s, detail[s], d.current_stage, d.status))
    .join("");
}

function renderHead(d) {
  el("pipe-title").textContent = d.name || d.video_name || d.id;
  el("pipe-sub").innerHTML =
    `<span class="badge ${d.type === "short" ? "short" : "long"}">${d.type || "?"}</span>` +
    `<span class="chip ${d.status}"><span class="d"></span>${
      { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado", queued: "Na fila", interrupted: "Interrompido" }[d.status] || d.status
    }</span>` +
    `<span class="mono dim">iteração ${d.iteration || 1}/${d.max_iterations || 3}</span>` +
    (d.estimated_tokens ? `<span class="mono dim">~${Number(d.estimated_tokens).toLocaleString("pt-BR")} tokens</span>` : "");

  // [label, value, kind to show in its folder (the engine's open/<kind>)]
  const facts = [
    ["vídeo original", d.video_path, "source"],
    ["output", d.output, "video"],
    ["contexto", d.context],
    ["idioma", d.language],
    ["cortes mantidos", d.plan?.kept_segments != null ? String(d.plan.kept_segments) : null],
  ].filter(([, v]) => v);
  el("pipe-facts").innerHTML = facts
    .map(([k, v, kind]) => `<div class="fact"><span>${k}</span>${kind
      ? `<button class="fact-link mono" type="button" data-reveal="${kind}" title="Mostrar na pasta">${escapeHtml(v)}</button>`
      : `<span class="mono">${escapeHtml(v)}</span>`}</div>`)
    .join("");
}

function renderResume(d) {
  const sel = el("resume-stage");
  const stages = stagesOf(d);
  if (sel.dataset.filled !== stages.join()) { // a short and a long list different stages
    sel.innerHTML = stages.map((s) => `<option value="${s}">${s}</option>`).join("");
    sel.dataset.filled = stages.join();
  }
  if (d.current_stage && stages.includes(d.current_stage)) sel.value = d.current_stage;
  const live = d.status === "running";
  sel.disabled = live;
  el("btn-resume").disabled = live;
  el("resume-note").textContent = live
    ? "rodando — pare ou espere terminar pra retomar"
    : d.status === "interrupted"
      ? "foi interrompido (o processo morreu) — retome daqui"
      : "refaz esse stage e todos os seguintes";
  const stoppable = live || d.status === "queued";
  el("btn-stop").hidden = !stoppable;
  if (!stoppable) resetStop();
}

// Two clicks to stop: the first arms the button, the second stops. A browser
// confirm() would block the Tauri window.
let stopTimer = null;
function resetStop() {
  clearTimeout(stopTimer);
  el("btn-stop").classList.remove("confirm");
  el("btn-stop").textContent = "Parar";
}

async function doStop() {
  const btn = el("btn-stop");
  if (!btn.classList.contains("confirm")) {
    btn.classList.add("confirm");
    btn.textContent = "Confirmar: parar edição";
    stopTimer = setTimeout(resetStop, 4000);
    return;
  }
  resetStop();
  btn.disabled = true;
  try {
    await api.stop(state.id);
    pushLog("── parado ──");
  } catch (err) {
    pushLog(`── não deu pra parar: ${err.message || err} ──`);
  } finally {
    btn.disabled = false;
    closeStream();
    load(state.id);
  }
}

function pushLog(line) {
  // Append one line instead of rebuilding the whole box on every log line
  // (FFmpeg prints several per second); trim the oldest only past the cap.
  state.lines.push(line);
  const box = el("pipe-log");
  box.append((box.firstChild ? "\n" : "") + line);
  if (state.lines.length > MAX_LOG_LINES * 1.5) {
    state.lines.splice(0, state.lines.length - MAX_LOG_LINES);
    box.textContent = state.lines.join("\n");
  }
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
  el("btn-see-result").hidden = d.status !== "done" && !d.output;
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
  el("pipe-facts").addEventListener("click", async (e) => {
    const link = e.target.closest("[data-reveal]");
    if (!link) return;
    try {
      await api.openFile(state.id, link.dataset.reveal, true);
    } catch (err) {
      el("pipe-error").hidden = false;
      el("pipe-error").textContent = `não deu pra abrir a pasta: ${err.message || err}`;
    }
  });
  el("btn-stop").addEventListener("click", doStop);
  el("pipe-log").addEventListener("scroll", (e) => {
    const box = e.currentTarget;
    state.pinned = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  });
  el("btn-pipe-back").addEventListener("click", () => go("/"));
  el("btn-see-cuts").addEventListener("click", () => go(`/video/${encodeURIComponent(state.id)}/cortes`));
  el("btn-see-result").addEventListener("click", () => go(`/video/${encodeURIComponent(state.id)}/resultado`));
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
    clearInterval(state.timer); // defensive: never two pollers
    closeStream();
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
