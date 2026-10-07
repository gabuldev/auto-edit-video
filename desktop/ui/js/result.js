// Resultado — o vídeo pronto tocando, a thumbnail, e o texto de publicação
// pronto pra copiar. É a última parada: daqui você posta.

import * as api from "./api.js";
import { el, escapeHtml, humanSize, setEngine } from "./shell.js";
import { go } from "./router.js";
import { mountPublish, unmountPublish } from "./publish.js";

const state = { id: null, data: null };

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

function fieldHTML(key, label, value) {
  const text = valueText(value);
  const isList = Array.isArray(value);
  return `
  <div class="meta-field">
    <div class="meta-label">
      <span>${label}</span>
      <button class="btn btn-sm copy" data-copy="${escapeHtml(isList ? value.map((t) => `#${t}`).join(" ") : text)}">copiar</button>
    </div>
    ${
      isList
        ? `<div class="tags">${value.map((t) => `<span class="tag mono">${escapeHtml(t)}</span>`).join("")}</div>`
        : `<div class="meta-value">${escapeHtml(text)}</div>`
    }
  </div>`;
}

function fileHTML(kind, info, id) {
  const label = { video: "vídeo final", thumbnail: "thumbnail", captions: "legendas (.srt)", notes: "metadata (.txt)" }[kind] || kind;
  return `
  <div class="file">
    <span class="file-kind">${label}</span>
    <span class="file-size mono">${humanSize(info.size)}</span>
    <button class="btn btn-sm" data-open="${kind}">abrir</button>
    <button class="btn btn-sm" data-open="${kind}" data-reveal="1">mostrar na pasta</button>
    <button class="btn btn-sm copy" data-copy="${escapeHtml(info.path)}">copiar caminho</button>
  </div>`;
}

function render(d) {
  state.data = d;
  el("res-title").textContent = d.video_name || d.id;
  el("res-sub").innerHTML =
    `<span class="badge ${d.type === "short" ? "short" : "long"}">${d.type || "?"}</span>` +
    `<span class="chip ${d.status}"><span class="d"></span>${
      { done: "Pronto", running: "Rodando", failed: "Falhou", idle: "Parado", queued: "Na fila" }[d.status] || d.status
    }</span>`;

  // Shorts derivam de um long pronto; o próprio short não vira short.
  el("btn-res-shorts").hidden = !(d.type === "long" && d.status === "done");
  el("btn-res-shorts").href = `#/video/${encodeURIComponent(d.id)}/shorts`;

  const files = d.files || {};
  const hasVideo = Boolean(files.video);
  el("res-player").hidden = !hasVideo;
  if (hasVideo) {
    const src = `${api.API}/api/videos/${encodeURIComponent(d.id)}/file/video`;
    if (el("res-video").getAttribute("src") !== src) el("res-video").setAttribute("src", src);
  }
  el("res-thumb-box").hidden = !files.thumbnail;
  if (files.thumbnail) {
    el("res-thumb").src = `${api.API}/api/videos/${encodeURIComponent(d.id)}/file/thumbnail`;
  }

  const kinds = ["video", "thumbnail", "captions", "notes"].filter((k) => files[k]);
  el("res-files").innerHTML = kinds.map((k) => fileHTML(k, files[k], d.id)).join("");
  el("res-nofiles").hidden = kinds.length > 0;

  const meta = d.metadata;
  const rows = meta ? FIELDS.filter(([k]) => meta[k] != null && valueText(meta[k]).trim()) : [];
  el("res-meta").innerHTML = rows.map(([k, label]) => fieldHTML(k, label, meta[k])).join("");
  el("res-nometa").hidden = rows.length > 0;

  const thumbText = meta?.thumbnail;
  el("res-thumbtext").hidden = !thumbText;
  if (thumbText) {
    el("res-thumbtext").innerHTML =
      `<div class="meta-label"><span>Texto da thumbnail</span></div>` +
      `<div class="thumb-text"><b>${escapeHtml(thumbText.main_text || "")}</b>` +
      (thumbText.sub_text ? `<span class="chip-text">${escapeHtml(thumbText.sub_text)}</span>` : "") +
      (thumbText.template ? `<span class="mono dim">template: ${escapeHtml(thumbText.template)}</span>` : "") +
      `</div>`;
  }
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
  const before = button.textContent;
  button.textContent = "copiado";
  setTimeout(() => { button.textContent = before; }, 1200);
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
  el("btn-res-back").addEventListener("click", () => go(`/video/${encodeURIComponent(state.id)}`));
}

export default {
  id: "result",
  mount({ id }) {
    if (!state.wired) { wire(); state.wired = true; }
    state.id = id;
    el("res-video").removeAttribute("src");
    el("btn-res-shorts").hidden = true;
    load(id);
    mountPublish(id);
  },
  unmount() {
    unmountPublish();
    el("res-video").pause?.();
  },
};
