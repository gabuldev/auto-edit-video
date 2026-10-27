// Novo edit — pick a video, describe it, start the pipeline. Everything the CLI
// takes (`auto-edit short|long`) is here; the extras live under "Opções".

import * as api from "./api.js";
import { el, humanSize, setEngine } from "./shell.js";
import { go } from "./router.js";
import { chooseVideo, isVideo, NOT_VIDEO, onVideoDrop } from "./video-pick.js";

const state = { video: null, busy: false, picking: false };
let pending = null; // a path chosen on the empty Biblioteca, picked up on mount

/** Open Novo edit with this video already chosen. */
export function openWithVideo(path) {
  pending = path;
  go("/novo");
}

const onScreen = () => !el("drop-zone").closest("[data-screen]").hidden;

function setVideo(v) {
  state.video = v;
  el("dz-empty").hidden = Boolean(v);
  el("dz-file").hidden = !v;
  if (v) {
    el("dz-name").textContent = v.name;
    el("dz-size").textContent = humanSize(v.size);
    // The path is cut from the left (rtl); the LRMs keep its own order intact.
    el("dz-meta").textContent = `\u200E${v.path}\u200E`;
    el("dz-meta").title = v.path;
  }
  // Left blank, the edit keeps the file's name: show which one.
  el("f-name").placeholder = v ? `Sem nome, usa “${v.name.replace(/\.[^.]+$/, "")}”` : "Sem nome, usa o nome do arquivo";
  validate();
}

// A path from the app's dialog or a drop: the engine checks it's a video and
// fills in the size.
async function usePath(path) {
  setError("");
  if (!isVideo(path)) { setError(NOT_VIDEO); return; }
  try {
    setVideo(await api.videoFile(path));
  } catch (err) {
    setError(String(err.message || err));
  }
}

async function pickVideo() {
  if (state.picking) return;
  state.picking = true;
  el("drop-zone").classList.add("busy");
  setError("");
  try {
    const path = await chooseVideo();
    if (path) await usePath(path);
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    state.picking = false;
    el("drop-zone").classList.remove("busy");
  }
}

const dragging = (on) => el("drop-zone").classList.toggle("over", on);

function readForm() {
  const type = document.querySelector('input[name="vtype"]:checked')?.value;
  return {
    video_path: state.video?.path || "",
    type,
    context: el("f-context").value.trim(),
    language: el("f-language").value,
    whisper_model: el("f-whisper").value,
    max_iterations: Number(el("f-iterations").value) || 3,
    dry_run: el("f-dry").checked,
    cold_open: el("f-coldopen").checked,
    reorder: el("f-reorder").checked,
    overlays_dir: type === "long" ? el("f-overlays").value.trim() || null : null,
    name: el("f-name").value.trim() || null,
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
  el("f-context").value = "";
  el("f-name").value = "";
  setError("");
  setVideo(null);
}

function wire() {
  el("dz-empty").addEventListener("click", pickVideo);
  el("dz-change").addEventListener("click", pickVideo);
  // Dropping anywhere on this screen counts.
  onVideoDrop(el("drop-zone").closest("[data-screen]"), {
    active: onScreen, over: dragging, path: usePath, fail: setError,
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
    // Defaults from Configurações, once per visit, without clobbering a form in progress.
    if (!state.video && !el("f-context").value) {
      try {
        const cfg = await api.settings();
        el("f-language").value = cfg.language;
        el("f-whisper").value = cfg.whisper_model;
        el("f-coldopen").checked = cfg.cold_open;
        el("f-reorder").checked = cfg.reorder;
        if (cfg.overlays_dir && !el("f-overlays").value) el("f-overlays").value = cfg.overlays_dir;
      } catch { /* engine offline: keep the form's own defaults */ }
    }
    if (pending) { const path = pending; pending = null; await usePath(path); }
    validate();
  },
};
