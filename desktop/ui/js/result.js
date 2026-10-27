// Resultado — o vídeo pronto tocando, a thumbnail, e o texto de publicação
// pronto pra copiar. É a última parada: daqui você posta.

import * as api from "./api.js";
import { el, escapeHtml, releaseMedia, humanSize, setEngine } from "./shell.js";
import { go, previousPath } from "./router.js";
import { mountPublish, unmountPublish } from "./publish.js";
import { mountCaptionAdjust, unmountCaptionAdjust } from "./caption-adjust.js";
import { mountRetention } from "./retention.js";

const state = { id: null, data: null, capMounted: false, stamp: Date.now() };

const FIELDS = [
  ["short_title", "Título do short"],
  ["hook", "Gancho"],
  ["youtube_title", "Título do YouTube"],
  ["youtube_description", "Descrição"],
  ["hashtags", "Hashtags"],
  ["tags", "Tags"],
  ["pinned_comment", "Comentário pra fixar"],
];

function valueText(v) {
  return Array.isArray(v) ? v.join(", ") : String(v);
}

const COPY = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>`;

function fieldHTML(key, label, value) {
  const text = valueText(value);
  const isList = Array.isArray(value);
  return `
  <div class="meta-field">
    <div class="meta-label">
      <span>${label}</span>
      <button class="copy" type="button" data-copy="${escapeHtml(isList ? value.map((t) => `#${t}`).join(" ") : text)}" title="Copiar" aria-label="Copiar ${label}">${COPY}</button>
    </div>
    ${
      isList
        ? `<div class="tags">${value.map((t) => `<span class="tag mono">${escapeHtml(t)}</span>`).join("")}</div>`
        : `<div class="meta-value">${escapeHtml(text)}</div>`
    }
  </div>`;
}

const FOLDER = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`;

function fileHTML(kind, info) {
  const label = { video: "Vídeo final", thumbnail: "Thumbnail", captions: "Legendas (.srt)", notes: "Metadata (.txt)" }[kind] || kind;
  return `
  <div class="file">
    <span class="file-kind">${label}</span>
    <span class="file-size mono">${humanSize(info.size)}</span>
    <button class="btn btn-sm btn-icon" data-open="${kind}" data-reveal="1" title="Mostrar na pasta" aria-label="Mostrar ${label} na pasta">${FOLDER}</button>
  </div>`;
}

function setShape(ratio) {
  el("res-player").style.setProperty("--ar", ratio);
  el("res-player").classList.toggle("vertical", ratio < 1);
}

function render(d) {
  state.data = d;
  el("res-title").textContent = d.name || d.video_name || d.id;
  el("res-sub").innerHTML =
    `<span class="badge ${d.type === "short" ? "short" : "long"}">${d.type || "?"}</span>` +
    `<span class="chip ${d.status}"><span class="d"></span>${
      { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado", queued: "Na fila", interrupted: "Interrompido" }[d.status] || d.status
    }</span>`;

  // Shorts derivam de um long pronto; o próprio short não vira short.
  el("btn-res-shorts").hidden = !(d.type === "long" && d.status === "done");
  el("btn-res-shorts").href = `#/video/${encodeURIComponent(d.id)}/shorts`;

  const files = d.files || {};
  const hasVideo = Boolean(files.video);
  el("res-player").hidden = !hasVideo;
  // Video and thumbnail take the video's shape: a guess by type until the file loads.
  if (!el("res-player").dataset.measured) setShape(d.type === "short" ? 9 / 16 : 16 / 9);
  if (hasVideo) {
    // ?t= : o vídeo pode ter sido regravado e o webview guarda cache.
    const src = `${api.API}/api/videos/${encodeURIComponent(d.id)}/file/video?t=${state.stamp}`;
    if (el("res-video").getAttribute("src") !== src) el("res-video").setAttribute("src", src);
  }
  // Ajustar legenda: só short com vídeo pronto (monta uma vez por visita).
  if (d.type === "short" && hasVideo && d.status === "done") {
    if (!state.capMounted) { state.capMounted = true; mountCaptionAdjust(d.id); }
  } else {
    el("cap-card").hidden = true;
  }
  el("res-thumb-box").hidden = !files.thumbnail;
  if (files.thumbnail) {
    el("res-thumb").src = `${api.API}/api/videos/${encodeURIComponent(d.id)}/file/thumbnail`;
  }

  const kinds = ["video", "thumbnail", "captions", "notes"].filter((k) => files[k]);
  el("res-files").innerHTML = kinds.map((k) => fileHTML(k, files[k])).join("");
  el("res-nofiles").hidden = kinds.length > 0;

  const meta = d.metadata;
  const rows = meta ? FIELDS.filter(([k]) => meta[k] != null && valueText(meta[k]).trim()) : [];
  el("res-meta").innerHTML = rows.map(([k, label]) => fieldHTML(k, label, meta[k])).join("");
  el("res-nometa").hidden = rows.length > 0;
}

async function load(id) {
  try {
    const d = await api.result(id);
    setEngine(true);
    el("res-error").hidden = true;
    render(d);
  } catch (err) {
    setEngine(false);
    el("res-error").hidden = false;
    el("res-error").textContent = `não deu pra ler o resultado: ${err.message || err}`;
  }
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea"); // clipboard API precisa de https/localhost
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  // "Copiado" pops over the icon, which turns green for a moment.
  clearTimeout(button.copiedTimer);
  button.classList.add("copied");
  button.copiedTimer = setTimeout(() => button.classList.remove("copied"), 1600);
}

function wire() {
  document.querySelector('[data-screen="result"]').addEventListener("click", (e) => {
    const btn = e.target.closest("button.copy");
    if (btn) copy(btn.dataset.copy, btn);
    const open = e.target.closest("button[data-open]");
    if (open) {
      // O motor abre pelo sistema: a janela do Tauri não segue link de download.
      api.openFile(state.id, open.dataset.open, Boolean(open.dataset.reveal)).catch((err) => {
        el("res-error").hidden = false;
        el("res-error").textContent = `não deu pra abrir: ${err.message || err}`;
      });
    }
  });
  // Back to where we came from: the library ("Ver resultado") or the pipeline.
  el("btn-res-back").addEventListener("click", () =>
    go(previousPath() === "/" ? "/" : `/video/${encodeURIComponent(state.id)}`));
  el("res-video").addEventListener("loadedmetadata", (e) => {
    const { videoWidth: w, videoHeight: h } = e.target;
    if (!w || !h) return;
    setShape(w / h);
    el("res-player").dataset.measured = "1";
  });
}

export default {
  id: "result",
  mount({ id }) {
    if (!state.wired) { wire(); state.wired = true; }
    state.id = id;
    state.stamp = Date.now();
    state.capMounted = false;
    el("res-video").removeAttribute("src");
    delete el("res-player").dataset.measured;
    el("btn-res-shorts").hidden = true;
    load(id);
    mountPublish(id);
    mountRetention(id);
  },
  unmount() {
    unmountPublish();
    unmountCaptionAdjust();
    releaseMedia(el("res-video"));
  },
};
