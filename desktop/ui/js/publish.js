// Publicar no YouTube — o card da tela Resultado. Conecta a conta (OAuth no
// navegador), preenche com o que o stage metadata gerou, envia com barra de
// progresso (SSE) e guarda o histórico no publish.json do workspace.

import * as api from "./api.js";
import { el, escapeHtml } from "./shell.js";
import { openYoutubeSettings } from "./settings.js";

const PRIVACY_LABEL = { private: "Privado", unlisted: "Não listado", public: "Público" };

const ICON = {
  private: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  unlisted: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  public: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  sent: '<path d="M12 15V4M7 9l5-5 5 5"/><path d="M5 20h14"/>',
  sched: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  published: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
  bad: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  studio: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  warn: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.5v.01"/>',
};
const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
const tag = (cls, icon, text) => `<span class="pub-tag ${cls}">${svg(icon)}${text}</span>`;
const fmt = (iso) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

// "comentário não postado: <why>" → the what in bold, capitalized.
function warningHTML(w) {
  const at = w.indexOf(": ");
  const what = at > 0 ? w.slice(0, at) : w;
  const why = at > 0 ? w.slice(at + 2) : "";
  return `<div class="pub-warn">${svg("warn")}<span><b>${escapeHtml(what.charAt(0).toUpperCase() + what.slice(1))}</b>${why ? `: ${escapeHtml(why)}` : ""}</span></div>`;
}

const state = {
  id: null, data: null, stream: null, poll: null, again: false, tried: false, wired: false,
  live: null, liveFor: null, // the sent videos as YouTube has them now (asked once per video)
};

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
  if (a.connecting) return "Aguardando você autorizar no navegador… Fechou a página? Cancele e conecte de novo.";
  if (a.needs_reconnect) return "Reconecte pra liberar retenção e legendas (permissões novas)";
  if (!a.connected) return a.has_client_secret ? "Conta não conectada" : "YouTube não configurado";
  return a.channel ? `Conectado como ${escapeHtml(a.channel)}` : "Conta conectada";
}

// Where a sent video stands: YouTube's word when it could be asked (a
// scheduled one goes public by itself; a project without the audit keeps it
// private), else what was sent. → [visibility, status] tags, or "gone".
// Gone from YouTube (deleted there): what YouTube just said, else the mark
// the engine left in publish.json the last time it asked.
function isGone(p) {
  return state.live?.checked ? !state.live.videos?.[p.video_id] : !!p.removed;
}

function standing(p) {
  const live = state.live?.checked ? state.live.videos?.[p.video_id] : null;
  if (isGone(p)) return { gone: true };
  const privacy = PRIVACY_LABEL[live?.privacy || p.privacy] ? live?.privacy || p.privacy : "private";
  const at = live ? live.publish_at : p.publish_at;
  const vis = tag(`vis ${privacy}`, privacy, PRIVACY_LABEL[privacy]);
  if (["rejected", "failed", "deleted"].includes(live?.upload_status)) return { tags: vis + tag("bad", "bad", "Recusado pelo YouTube") };
  if (privacy === "private" && at && (live || new Date(at) > Date.now())) {
    return { tags: vis + tag("sched", "sched", `Programado pra ${fmt(at)}`) };
  }
  if (privacy === "private") return { tags: vis + tag("sent", "sent", "Enviado") };
  return { tags: vis + tag("published", "published", "Publicado") };
}

function historyHTML(items) {
  return items
    .slice()
    .reverse()
    .map((p) => {
      const s = standing(p);
      const sub = [
        p.published_at ? `Enviado em ${fmt(p.published_at)}` : "",
        p.captions ? "com legenda" : "",
        p.comment_id ? "com comentário" : "",
      ].filter(Boolean).join(" · ");
      const acts = s.gone ? "" : `
        <div class="pub-item-acts">
          <button class="btn btn-primary" type="button" data-url="${escapeHtml(p.url)}">${svg("play")}Ver no YouTube</button>
          <button class="btn" type="button" data-url="https://studio.youtube.com/video/${encodeURIComponent(p.video_id)}/edit">${svg("studio")}Abrir no Studio</button>
        </div>`;
      return `
      <div class="pub-item${s.gone ? " gone" : ""}">
        <div class="pub-item-main">
          <div class="pub-item-title" title="${escapeHtml(p.title || "")}">${escapeHtml(p.title || p.video_id)}</div>
          <div class="pub-tags">${s.gone ? tag("bad", "bad", "Não está mais no YouTube") : s.tags}</div>
          ${sub ? `<div class="pub-item-sub">${sub}</div>` : ""}
        </div>
        ${acts}
        ${s.gone ? "" : (p.warnings || []).map(warningHTML).join("")}
      </div>`;
    })
    .join("");
}

// What the metadata stage couldn't write comes marked "[REVISAR] …" (an empty
// transcript, say). The form never sends that: the field starts empty with
// the instruction, unmarked, as its placeholder.
const REVIEW = /\[REVISAR\]\s*/gi;
const needsReview = (text) => /^\s*\[REVISAR\]/i.test(text || "");

function fillField(id, text) {
  const review = needsReview(text);
  el(id).value = review ? "" : (text || "").replace(REVIEW, "");
  el(id).placeholder = review ? text.replace(REVIEW, "").trim() : "";
}

function fillForm(d) {
  const f = d.defaults || {};
  fillField("pub-title", f.title);
  fillField("pub-desc", f.description);
  el("pub-tags").value = (f.tags || []).join(", ");
  el("pub-privacy").value = f.privacy || "private";
  el("pub-when").value = "";
  el("pub-captions-row").hidden = !d.captions;
  el("pub-captions").checked = Boolean(d.captions);
  el("pub-comment-row").hidden = !d.pinned_comment;
  el("pub-comment-on").checked = false;
  fillField("pub-comment", d.pinned_comment);
  el("pub-comment").hidden = true;
  // Títulos alternativos do metadata: um clique troca o do campo.
  const options = (d.title_options || []).filter((t) => !needsReview(t));
  el("pub-titles").hidden = options.length < 2;
  el("pub-titles").innerHTML = options
    .map((t) => `<button type="button" class="btn btn-sm" data-title="${escapeHtml(t)}">${escapeHtml(t)}</button>`)
    .join("");
  syncForm();
}

function syncForm() {
  const len = el("pub-title").value.trim().length;
  const max = state.data?.limits?.title || 100;
  el("pub-title-count").textContent = `${len}/${max}`;
  el("pub-title-count").classList.toggle("over", len > max);

  // YouTube only schedules a private video: with a date, the visibility is
  // locked, and the field says why and how to undo it.
  const when = el("pub-when").value;
  const scheduled = Boolean(when);
  if (scheduled) el("pub-privacy").value = "private";
  el("pub-privacy").disabled = scheduled;
  el("pub-privacy-hint").hidden = !scheduled;
  el("pub-privacy-hint").textContent = scheduled
    ? `Agendado: fica privado até ${fmt(when)} e vira público sozinho. Pra escolher outra visibilidade, limpe o agendamento.`
    : "";
  el("pub-when-clear").hidden = !scheduled;

  const title = el("pub-title").value.trim();
  for (const b of el("pub-titles").querySelectorAll("button")) b.classList.toggle("on", b.dataset.title === title);

  const notes = [];
  if (state.data?.type === "short") notes.push("Short: o YouTube não aceita thumbnail personalizada pela API — ele escolhe o frame.");
  else if (state.data?.thumbnail) notes.push("A thumbnail gerada vai junto.");
  if (el("pub-comment-on").checked && el("pub-privacy").value === "private") {
    notes.push("Vídeo privado não aceita comentário: escolha não listado/público ou poste depois pelo Studio.");
  }
  const nv = state.data?.next_video;
  if (nv) notes.push(`Tela final (últimos 20s, no Studio): indique "${nv.title}".`);
  if ((state.data?.title_options || []).filter((t) => !needsReview(t)).length > 1) notes.push("Os outros títulos dá pra testar no Studio (Testar e comparar).");
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
  if (published.length && a.connected && state.liveFor !== state.id) loadLive();

  if (d.job?.status === "running") {
    show({ progress: true });
    el("pub-again").hidden = true;
    openStream();
    return;
  }
  if (!a.connected) {
    el("pub-again").hidden = true;
    show({ connect: true });
    // Without a Google credential there's nothing to connect yet: the step by
    // step lives in Configurações → YouTube.
    el("btn-yt-connect").hidden = !a.has_client_secret;
    el("btn-yt-setup").hidden = !!a.has_client_secret;
    el("btn-yt-connect").disabled = a.connecting;
    el("btn-yt-cancel").hidden = !a.connecting; // the tab was closed: stop waiting
    el("btn-yt-connect").textContent = a.connecting
      ? "Esperando autorização…"
      : a.needs_reconnect ? "Reconectar YouTube" : "Conectar YouTube";
    // The engine keeps the last attempt's error; only one tried from here shows.
    el("pub-connect-note").innerHTML = a.has_client_secret
      ? (state.tried && a.error ? `Não conectou: ${escapeHtml(a.error)}` : "Abre o navegador pra você autorizar o envio de vídeos pro seu canal.")
      : "O YouTube ainda não está configurado neste computador. O passo a passo pra conectar está em <b>Configurações → YouTube</b> (é uma vez só).";
    return;
  }
  // Every send deleted on YouTube: it's as if never sent (the history stays).
  const onYoutube = published.filter((p) => !isGone(p));
  const showForm = onYoutube.length === 0 || state.again;
  el("pub-again").hidden = showForm;
  show({ form: showForm });
  // Sending again is the exception: it says so, can be cancelled, and its
  // button doesn't outshine "Ver no YouTube".
  const resend = onYoutube.length > 0;
  el("pub-resend-head").hidden = !resend;
  el("btn-pub-cancel").hidden = !resend;
  el("btn-publish").classList.toggle("btn-primary", !resend);
  el("btn-publish").textContent = resend ? "Enviar de novo" : "Enviar pro YouTube";
  // Preenche uma vez por vídeo: um reload não apaga o que você editou.
  if (showForm && el("pub-title").dataset.filledFor !== state.id) {
    fillForm(d);
    el("pub-title").dataset.filledFor = state.id;
  }
}

// After the card shows what was sent, ask YouTube where each video stands.
async function loadLive() {
  const id = (state.liveFor = state.id);
  let live;
  try { live = await api.publishLive(id); } catch { return; }
  if (state.id !== id || !state.data) return;
  state.live = live;
  render(state.data); // a deletion can bring the form back
}

async function load() {
  try {
    render(await api.publishState(state.id));
  } catch {
    el("pub-card").hidden = true;
  }
}

function setProgress(pct) {
  el("pub-bar").style.transform = `scaleX(${pct / 100})`;
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
    else if (ev.type === "done") { closeStream(); state.again = false; state.liveFor = null; load(); }
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
    captions: !el("pub-captions-row").hidden && el("pub-captions").checked,
    comment: el("pub-comment-on").checked ? el("pub-comment").value.trim() : null,
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
  state.tried = true;
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
  el("btn-yt-setup").addEventListener("click", openYoutubeSettings);
  el("btn-yt-cancel").addEventListener("click", async () => {
    clearInterval(state.poll);
    state.poll = null;
    try { await api.cancelYoutubeConnect(); } catch (err) { setError(String(err.message || err)); }
    load();
  });
  el("btn-publish").addEventListener("click", publish);
  el("btn-pub-again").addEventListener("click", () => {
    state.again = true;
    el("pub-title").dataset.filledFor = "";
    render(state.data);
  });
  el("btn-pub-cancel").addEventListener("click", () => {
    state.again = false;
    setError("");
    render(state.data);
  });
  for (const id of ["pub-title", "pub-when"]) el(id).addEventListener("input", syncForm);
  el("pub-privacy").addEventListener("change", syncForm);
  el("pub-when-clear").addEventListener("click", () => {
    el("pub-when").value = "";
    syncForm();
  });
  el("pub-titles").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-title]");
    if (!b) return;
    el("pub-title").value = b.dataset.title;
    syncForm();
  });
  el("pub-comment-on").addEventListener("change", () => {
    el("pub-comment").hidden = !el("pub-comment-on").checked;
    syncForm();
  });
  el("pub-history").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-url]");
    if (b) api.openUrl(b.dataset.url).catch((err) => setError(String(err.message || err)));
  });
}

export function mountPublish(id) {
  if (!state.wired) { wire(); state.wired = true; }
  if (state.id !== id) { state.again = false; el("pub-title").dataset.filledFor = ""; }
  if (state.id !== id) { state.live = null; state.liveFor = null; }
  state.id = id;
  state.tried = false;
  el("pub-card").hidden = true;
  setError("");
  load();
}

export function unmountPublish() {
  closeStream();
  clearInterval(state.poll);
  state.poll = null;
}
