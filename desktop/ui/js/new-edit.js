// Novo edit — pick a video, describe it, start the pipeline. Everything the CLI
// takes (`auto-edit short|long`) is here; the extras live under "Opções".

import * as api from "./api.js";
import { el, escapeHtml, humanSize, setEngine } from "./shell.js";
import { go } from "./router.js";

const state = { dir: null, selected: null, loaded: false, busy: false };

function fileRowHTML(v) {
  const when = v.modified ? new Date(v.modified).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
  return `
  <button class="pick-item${state.selected === v.path ? " sel" : ""}" data-path="${escapeHtml(v.path)}" type="button">
    <span class="pick-ico film"></span>
    <span class="pick-name">${escapeHtml(v.name)}</span>
    <span class="pick-meta mono">${humanSize(v.size)}${when ? ` · ${when}` : ""}</span>
  </button>`;
}

function dirRowHTML(d) {
  return `
  <button class="pick-item dir" data-dir="${escapeHtml(d.path)}" type="button">
    <span class="pick-ico folder"></span>
    <span class="pick-name">${escapeHtml(d.name)}</span>
    <span class="pick-meta mono">pasta</span>
  </button>`;
}

async function loadDir(dir) {
  const list = el("pick-list");
  list.innerHTML = `<div class="pick-empty">carregando…</div>`;
  let data;
  try {
    data = await api.browse(dir);
  } catch {
    setEngine(false);
    list.innerHTML = `<div class="pick-empty">motor offline — não dá pra listar arquivos.</div>`;
    return;
  }
  state.dir = data.dir;
  state.loaded = true;
  el("pick-path").textContent = data.dir;
  el("pick-up").disabled = !data.parent;
  el("pick-up").dataset.dir = data.parent || "";

  const items = [...data.dirs.map(dirRowHTML), ...data.videos.map(fileRowHTML)];
  list.innerHTML = items.length
    ? items.join("")
    : `<div class="pick-empty">${data.exists ? "nenhum vídeo nesta pasta." : "esta pasta não existe."}</div>`;
}

function select(path) {
  state.selected = path;
  document.querySelectorAll("#pick-list .pick-item").forEach((b) => {
    b.classList.toggle("sel", b.dataset.path === path);
  });
  el("sel-path").textContent = path || "nenhum vídeo escolhido";
  el("sel-path").classList.toggle("muted", !path);
  validate();
}

function readForm() {
  const type = document.querySelector('input[name="vtype"]:checked')?.value;
  return {
    video_path: state.selected || el("manual-path").value.trim(),
    type,
    context: el("f-context").value.trim(),
    language: el("f-language").value,
    whisper_model: el("f-whisper").value,
    max_iterations: Number(el("f-iterations").value) || 3,
    dry_run: el("f-dry").checked,
    overlays_dir: type === "long" ? el("f-overlays").value.trim() || null : null,
  };
}

function validate() {
  const f = readForm();
  const ok = Boolean(f.video_path && f.type && !state.busy);
  el("btn-start").disabled = !ok;
  el("row-overlays").hidden = f.type !== "long";
  return ok;
}

function setError(msg) {
  const box = el("new-error");
  box.hidden = !msg;
  box.textContent = msg || "";
}

async function submit() {
  if (!validate()) return;
  state.busy = true;
  setError("");
  el("btn-start").disabled = true;
  el("btn-start").textContent = "Iniciando…";
  try {
    const { video_id } = await api.startEdit(readForm());
    reset();
    // land on the live screen: the run has already started
    go(video_id ? `/video/${encodeURIComponent(video_id)}` : "/");
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    state.busy = false;
    el("btn-start").textContent = "Iniciar edição";
    validate();
  }
}

function reset() {
  state.selected = null;
  el("manual-path").value = "";
  el("f-context").value = "";
  select(null);
}

function wire() {
  el("pick-list").addEventListener("click", (e) => {
    const item = e.target.closest(".pick-item");
    if (!item) return;
    if (item.dataset.dir) loadDir(item.dataset.dir);
    else select(item.dataset.path);
  });
  el("pick-up").addEventListener("click", (e) => {
    const dir = e.currentTarget.dataset.dir;
    if (dir) loadDir(dir);
  });
  el("pick-reload").addEventListener("click", () => loadDir(state.dir));
  el("manual-path").addEventListener("input", () => {
    if (el("manual-path").value.trim()) select(null);
    validate();
  });
  document.querySelectorAll('input[name="vtype"]').forEach((r) =>
    r.addEventListener("change", validate)
  );
  el("btn-start").addEventListener("click", submit);
  el("btn-cancel").addEventListener("click", () => { reset(); go("/"); });
}

export default {
  id: "new",
  async mount() {
    if (!state.wired) { wire(); state.wired = true; }
    setEngine(await api.health());
    if (!state.loaded) await loadDir(null); // defaults to the inbox
    validate();
  },
};
