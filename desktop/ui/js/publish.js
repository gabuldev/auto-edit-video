// Publicar no YouTube — o card da tela Resultado. Conecta a conta (OAuth no
// navegador), preenche com o que o stage metadata gerou, envia com barra de
// progresso (SSE) e guarda o histórico no publish.json do workspace.

import * as api from "./api.js";
import { el, escapeHtml } from "./shell.js";

const PRIVACY_LABEL = { private: "privado", unlisted: "não listado", public: "público" };

const state = { id: null, data: null, stream: null, poll: null, again: false, wired: false };

function setError(msg) {
  el("pub-error").hidden = !msg;
  el("pub-error").textContent = msg || "";
}

function show({ connect = false, form = false, progress = false } = {}) {
  el("pub-connect").hidden = !connect;
  el("pub-form").hidden = !form;
  el("pub-progress").hidden = !progress;
}

function accountLine(a) {
  if (a.connecting) return "aguardando você autorizar no navegador…";
  if (a.needs_reconnect) return "reconecte pra liberar retenção e legendas (permissões novas)";
  if (!a.connected) return "conta não conectada";
  return a.channel ? `conectado como ${escapeHtml(a.channel)}` : "conta conectada";
}

function historyHTML(items) {
  return items
    .slice()
    .reverse()
    .map((p) => {
      const when = p.published_at ? new Date(p.published_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
      const sched = p.publish_at
        ? ` · agendado pra ${new Date(p.publish_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}`
        : "";
      return `
      <div class="pub-item">
        <span class="grow" title="${escapeHtml(p.title || "")}">${escapeHtml(p.title || p.video_id)}</span>
        <span class="mono dim">${PRIVACY_LABEL[p.privacy] || p.privacy}${sched} · ${when}</span>
        <button class="btn btn-sm" data-url="${escapeHtml(p.url)}">abrir</button>
        <button class="btn btn-sm" data-url="https://studio.youtube.com/video/${encodeURIComponent(p.video_id)}/edit">Studio</button>
        ${(p.warnings || []).map((w) => `<span class="warn">${escapeHtml(w)}</span>`).join("")}
      </div>`;
    })
    .join("");
}

function fillForm(d) {
  const f = d.defaults || {};
  el("pub-title").value = f.title || "";
  el("pub-desc").value = f.description || "";
  el("pub-tags").value = (f.tags || []).join(", ");
  el("pub-privacy").value = f.privacy || "private";
  el("pub-when").value = "";
  syncForm();
}

function syncForm() {
  const len = el("pub-title").value.trim().length;
  const max = state.data?.limits?.title || 100;
  el("pub-title-count").textContent = `${len}/${max}`;
  el("pub-title-count").classList.toggle("over", len > max);

  const scheduled = Boolean(el("pub-when").value);
  if (scheduled) el("pub-privacy").value = "private";
  el("pub-privacy").disabled = scheduled;

  const notes = [];
  if (scheduled) notes.push("Agendado: fica privado e vira público sozinho na hora marcada.");
  if (state.data?.type === "short") notes.push("Short: o YouTube não aceita thumbnail personalizada pela API — ele escolhe o frame.");
  else if (state.data?.thumbnail) notes.push("A thumbnail gerada vai junto.");
  notes.push("Projeto do Google sem auditoria: o YouTube trava o vídeo como privado — aí é só liberar no Studio.");
  el("pub-note").textContent = notes.join(" ");
  el("btn-publish").disabled = !len || len > max;
}

function render(d) {
  state.data = d;
  el("pub-card").hidden = !d.eligible;
  if (!d.eligible) return;

  const a = d.account || {};
  el("pub-account").innerHTML = accountLine(a);
  const published = d.published || [];
  el("pub-history").hidden = published.length === 0;
  el("pub-history").innerHTML = historyHTML(published);

  if (d.job?.status === "running") {
    show({ progress: true });
    el("btn-pub-again").hidden = true;
    openStream();
    return;
  }
  if (!a.connected) {
    el("btn-pub-again").hidden = true;
    show({ connect: true });
    el("btn-yt-connect").disabled = a.connecting || !a.has_client_secret;
    el("btn-yt-connect").textContent = a.connecting
      ? "Esperando autorização…"
      : a.needs_reconnect ? "Reconectar YouTube" : "Conectar YouTube";
    el("pub-connect-note").innerHTML = a.has_client_secret
      ? (a.error ? `Não conectou: ${escapeHtml(a.error)}` : "Abre o navegador pra você autorizar o envio de vídeos pro seu canal.")
      : "Falta o client secret do Google: crie um OAuth client <b>Desktop app</b> no Google Cloud (com a YouTube Data API v3 habilitada), baixe o JSON e aponte <code class=\"mono\">AUTO_EDIT_YT_CLIENT_SECRET</code> pra ele. Depois reabra o app.";
    return;
  }
  const showForm = published.length === 0 || state.again;
  el("btn-pub-again").hidden = showForm;
  show({ form: showForm });
  // Preenche uma vez por vídeo: um reload não apaga o que você editou.
  if (showForm && el("pub-title").dataset.filledFor !== state.id) {
    fillForm(d);
    el("pub-title").dataset.filledFor = state.id;
  }
}

async function load() {
  try {
    render(await api.publishState(state.id));
  } catch {
    el("pub-card").hidden = true;
  }
}

function setProgress(pct) {
  el("pub-bar").style.width = `${pct}%`;
  el("pub-pct").textContent = `${pct}%`;
}

function openStream() {
  if (state.stream) return;
  let es;
  try { es = api.videoEvents(state.id); } catch { return; }
  state.stream = es;
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === "progress") setProgress(ev.pct);
    else if (ev.type === "done") { closeStream(); state.again = false; load(); }
    else if (ev.type === "error") {
      closeStream();
      setError(String(ev.message || "o envio falhou").replace(/^PublishError: /, ""));
      load();
    }
  };
  es.onerror = () => { closeStream(); load(); };
}

function closeStream() {
  state.stream?.close();
  state.stream = null;
}

async function publish() {
  setError("");
  const when = el("pub-when").value;
  const payload = {
    title: el("pub-title").value.trim(),
    description: el("pub-desc").value,
    tags: el("pub-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
    privacy: el("pub-privacy").value,
    publish_at: when ? new Date(when).toISOString() : null,
    force: (state.data?.published || []).length > 0,
  };
  el("btn-publish").disabled = true;
  try {
    await api.publishYoutube(state.id, payload);
    setProgress(0);
    show({ progress: true });
    openStream();
  } catch (err) {
    setError(String(err.message || err));
    el("btn-publish").disabled = false;
  }
}

async function connect() {
  setError("");
  try {
    render({ ...state.data, account: await api.connectYoutube() });
  } catch (err) {
    setError(String(err.message || err));
    return;
  }
  // O OAuth acontece no navegador; acompanha até terminar.
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    let a;
    try { a = await api.youtubeAccount(); } catch { return; }
    if (!a.connecting) {
      clearInterval(state.poll);
      state.poll = null;
      load();
    } else {
      el("pub-account").innerHTML = accountLine(a);
    }
  }, 2000);
}

function wire() {
  el("btn-yt-connect").addEventListener("click", connect);
  el("btn-publish").addEventListener("click", publish);
  el("btn-pub-again").addEventListener("click", () => {
    state.again = true;
    el("pub-title").dataset.filledFor = "";
    render(state.data);
  });
  for (const id of ["pub-title", "pub-when"]) el(id).addEventListener("input", syncForm);
  el("pub-history").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-url]");
    if (b) api.openUrl(b.dataset.url).catch((err) => setError(String(err.message || err)));
  });
}

export function mountPublish(id) {
  if (!state.wired) { wire(); state.wired = true; }
  if (state.id !== id) { state.again = false; el("pub-title").dataset.filledFor = ""; }
  state.id = id;
  el("pub-card").hidden = true;
  setError("");
  load();
}

export function unmountPublish() {
  closeStream();
  clearInterval(state.poll);
  state.poll = null;
}
