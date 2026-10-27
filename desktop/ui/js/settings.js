// Configurações — qual agente de IA edita (e com qual modelo), as contas, as
// pastas e os padrões que vêm preenchidos no Novo edit. Salva em
// ~/.auto-edit/settings.json; variáveis de ambiente continuam valendo por cima.

import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";

const MODEL_HINT = {
  claude: "padrão da CLI (ex.: claude-opus-5-5)",
  cursor: "auto",
  agy: "padrão da CLI",
  opencode: "ex.: opencode/big-pickle",
  codex: "padrão da CLI (ex.: gpt-5-codex)",
  openrouter: "openrouter/auto, ou ex.: openai/gpt-5",
  ollama: "escolha abaixo",
};

const state = {
  saved: null, draft: null, agents: [], results: {}, busy: {}, poll: null, wired: false,
  // YouTube: credential there? following the consent; land on the card; Conectar clicked here
  ytReady: null, ytPoll: null, ytFocus: false, ytTried: false,
};

const clone = (x) => JSON.parse(JSON.stringify(x));

function dirty() {
  return JSON.stringify(state.saved) !== JSON.stringify(state.draft);
}

function setError(msg) {
  el("cfg-error").hidden = !msg;
  el("cfg-error").textContent = msg || "";
}

// Everything on this screen saves itself, a moment after the last change (so
// typing a model name isn't a save per key); the top bar says how it went.
let saveTimer = null;
let statusTimer = null;

function setStatus(text, kind = "") {
  clearTimeout(statusTimer);
  el("cfg-save-status").textContent = text;
  el("cfg-save-status").className = `save-status ${kind}`;
  if (kind === "ok") statusTimer = setTimeout(() => setStatus("Salvo automaticamente"), 2500);
}

function syncSave() {
  if (!dirty()) return;
  clearTimeout(saveTimer);
  setStatus("Salvando…");
  saveTimer = setTimeout(save, 600);
}

// OpenRouter: no CLI, just an API key pasted here.
function keyForm(a) {
  return `<div class="cfg-key">
      <input class="input mono" type="password" autocomplete="off" spellcheck="false" data-key-input="${a.name}" placeholder="cole a chave: sk-or-…" />
      <button class="btn btn-sm btn-primary" data-key-save="${a.name}">Salvar chave</button>
    </div>
    <span class="meta">crie uma em <a href="#" data-docs="${escapeHtml(a.docs)}">openrouter.ai/settings/keys</a> — fica só no seu computador.</span>`;
}

// A 7B local model took ~5 min on a 10-min long's plan alone (an edit calls
// the agent 6+ times) and filled it with the prompt's example.
const OLLAMA_SLOW = `<span class="meta">modelo local é lento (minutos por etapa) e modelos pequenos (7B) erram em vídeo longo — prefira um de 14B+ ou use o Ollama como fallback</span>`;

function agentMeta(a) {
  if (a.api_key) {
    if (!a.installed) return `<span class="meta bad">sem chave da API</span>${keyForm(a)}`;
    return a.key_source === "env"
      ? `<span class="meta">chave ${escapeHtml(a.key_hint || "")} (da variável OPENROUTER_API_KEY)</span>`
      : `<span class="meta">chave ${escapeHtml(a.key_hint || "")} · <a href="#" data-key-remove="${a.name}">remover</a></span>`;
  }
  if (!a.installed) return `<span class="meta bad">não instalado · <a href="#" data-docs="${escapeHtml(a.docs)}">como instalar</a></span>`;
  if (a.name === "ollama") {
    if (!a.server) return `<span class="meta bad">instalado, mas o servidor não está rodando (abra o app do Ollama)</span>`;
    return `<span class="meta">${escapeHtml(a.version || "")} · ${a.models.length} modelo(s)</span>${OLLAMA_SLOW}`;
  }
  return `<span class="meta">${escapeHtml(a.version || "instalado")}</span>`;
}

function modelInput(a) {
  const value = state.draft.agent.models[a.name] || "";
  if (a.name === "ollama") {
    const opts = (a.models || []).map((m) => `<option ${m === value ? "selected" : ""}>${escapeHtml(m)}</option>`).join("");
    return `<select class="input mono model" data-model="ollama"><option value="">primeiro instalado</option>${opts}</select>`;
  }
  return `<input class="input mono model" data-model="${a.name}" value="${escapeHtml(value)}" placeholder="modelo: ${escapeHtml(MODEL_HINT[a.name] || "padrão")}" />`;
}

function resultHTML(name) {
  const r = state.results[name];
  if (state.busy[name]) return `<div class="result">testando… (um prompt mínimo de verdade, pode levar até 1 min)</div>`;
  if (!r) return "";
  if (r.saved) return `<div class="result ok">✓ chave salva — clique em Testar</div>`;
  if (r.ok) return `<div class="result ok">✓ respondeu em ${r.seconds}s</div>`;
  return `<div class="result bad">✗ ${escapeHtml(r.error || "falhou")}${r.answer ? `\nresposta: ${escapeHtml(r.answer)}` : ""}</div>`;
}

function renderAgents() {
  const primary = state.draft.agent.primary;
  el("cfg-agents").innerHTML = state.agents.map((a) => `
    <div class="cfg-agent${a.name === primary ? " primary" : ""}">
      <input type="radio" name="cfg-primary" value="${a.name}" ${a.name === primary ? "checked" : ""} ${a.installed ? "" : "disabled"} title="usar como principal" />
      <div class="who">
        <b>${escapeHtml(a.label)}${a.name === primary ? ` <span class="badge long">principal</span>` : ""}${a.name === state.draft.agent.fallback ? ` <span class="badge short">fallback</span>` : ""}</b>
        ${agentMeta(a)}
        ${a.installed ? modelInput(a) : ""}
      </div>
      <div class="acts">
        ${a.installed ? `<button class="btn btn-sm" data-test="${a.name}" ${state.busy[a.name] ? "disabled" : ""}>Testar</button>` : ""}
        ${a.installed && a.login_command ? `<button class="btn btn-sm" data-login="${a.name}">Fazer login</button>` : ""}
      </div>
      ${resultHTML(a.name)}
    </div>`).join("");

  const fb = state.draft.agent.fallback || "";
  el("cfg-fallback").innerHTML = `<option value="">sem fallback</option>` + state.agents
    .filter((a) => a.installed && a.name !== primary)
    .map((a) => `<option value="${a.name}" ${a.name === fb ? "selected" : ""}>${escapeHtml(a.label)}</option>`).join("");
}

function renderOllama() {
  const o = state.agents.find((a) => a.name === "ollama");
  el("cfg-ollama-card").hidden = !o;
  if (!o) return;
  const pulling = Object.entries(o.pulling || {});
  el("cfg-ollama").innerHTML = !o.installed
    ? `<div class="empty small">Ollama não instalado — <a href="#" data-docs="https://ollama.com">ollama.com</a></div>`
    : `<div class="cfg-models">${(o.models || []).map((m) => `<span class="tag mono">${escapeHtml(m)}</span>`).join("") || `<span class="dim">nenhum modelo ainda — baixe um abaixo (ex.: qwen2.5:7b, ~4,7 GB)</span>`}</div>`
      + pulling.map(([m, st]) => `<div class="dim mono">${escapeHtml(m)}: ${st === "downloading" ? "baixando…" : escapeHtml(st)}</div>`).join("");
  el("btn-ollama-pull").disabled = !o.installed || !o.server;
  // Keep refreshing while something downloads.
  clearInterval(state.poll);
  state.poll = pulling.some(([, st]) => st === "downloading") ? setInterval(loadAgents, 4000) : null;
}

// Pastas: shown as the pipeline uses them (the engine resolves the defaults);
// chosen in the OS dialog and saved right away, never typed.
const FOLDER_KEY = { inbox: "inbox", output: "output_dir" };

async function renderFolders() {
  let f;
  try { f = await api.folders(); } catch { return; }
  for (const which of Object.keys(FOLDER_KEY)) {
    el(`cfg-${which}`).textContent = `\u200E${f[which].path}\u200E`; // LRMs: the path keeps its order in the rtl cut
    el(`cfg-${which}`).title = f[which].path;
    el(`cfg-${which}-default`).hidden = f[which].custom;
    el(`cfg-${which}-reset`).hidden = !f[which].custom;
    el(`cfg-${which}`).classList.toggle("missing", f[which].exists === false);
  }
  // A chosen inbox can be deleted later: say so, Trocar fixes it.
  el("cfg-inbox-missing").hidden = f.inbox.exists !== false;
}

// Saves just this folder setting: other unsaved edits on the screen stay pending.
async function saveFolder(which, path) {
  setError("");
  const key = FOLDER_KEY[which];
  try {
    const s = await api.saveSettings({ ...state.saved, [key]: path });
    state.saved = s;
    state.draft[key] = s[key];
    renderFolders();
    setStatus("Salvo", "ok");
  } catch (err) { setError(String(err.message || err)); }
}

async function pickFolder(which) {
  const dialog = window.__TAURI__?.dialog;
  if (!dialog) { setError("Escolher pasta só funciona no app instalado."); return; }
  let path;
  try {
    path = await dialog.open({ directory: true, multiple: false, defaultPath: el(`cfg-${which}`).title || undefined });
  } catch (err) { setError(String(err.message || err)); return; }
  if (path) saveFolder(which, path);
}

function renderForm() {
  const d = state.draft;
  el("cfg-language").value = d.language;
  el("cfg-whisper").value = d.whisper_model;
  el("cfg-coldopen").checked = d.cold_open;
  el("cfg-reorder").checked = d.reorder;
}

// ── YouTube ──────────────────────────────────────────────────────────────────
// Connecting needs an OAuth client of one's own from Google Cloud (the JSON
// it downloads): the step by step stays open until there is one.

function ytStatus(a) {
  if (a.connecting) return ["wait", "Aguardando você autorizar no navegador… Fechou a página? Cancele e conecte de novo."];
  if (a.connected) return ["ok", `Conectado como <b>${escapeHtml(a.channel || "?")}</b>`];
  if (a.needs_reconnect) return ["warn", "Precisa reconectar pra liberar as permissões novas"];
  if (a.has_client_secret) return ["off", "Não conectado"];
  return ["off", "Não configurado: falta a credencial do Google (passo a passo abaixo)"];
}

function renderYoutube(a) {
  const ready = !!a.has_client_secret;
  const [tone, text] = ytStatus(a);
  el("cfg-yt-dot").className = `yt-dot ${tone}`;
  el("cfg-yt-status").innerHTML = text;
  const btn = el("btn-cfg-yt");
  btn.textContent = a.connecting ? "Esperando autorização…"
    : a.connected ? "Desconectar" : a.needs_reconnect ? "Reconectar YouTube" : "Conectar YouTube";
  btn.dataset.connected = a.connected ? "1" : "";
  btn.disabled = a.connecting || (!ready && !a.connected);
  btn.title = ready || a.connected ? "" : "Primeiro escolha o JSON da credencial (passo 5)";
  btn.classList.toggle("btn-primary", ready && !a.connected && !a.connecting);
  el("btn-cfg-yt-cancel").hidden = !a.connecting;
  // The engine keeps the last attempt's error; only one tried from here shows.
  const failed = state.ytTried && !a.connecting && a.error;
  el("cfg-yt-error").hidden = !failed;
  el("cfg-yt-error").textContent = failed ? `Não conectou: ${a.error}` : "";
  el("cfg-yt-client").hidden = !ready;
  el("cfg-yt-client").innerHTML = ready
    ? `Credencial do Google: <span class="mono" title="${escapeHtml(a.client_id || "")}">${escapeHtml(a.client_id || "configurada")}</span> · <a href="#" data-yt-json>trocar arquivo</a>`
    : "";
  // Open while there's no credential; once it changes, follow it (in between,
  // it stays as the person left it).
  if (state.ytReady !== ready) el("cfg-yt-guide").open = !ready;
  state.ytReady = ready;
}

function ytError(msg) {
  el("cfg-yt-error").hidden = !msg;
  el("cfg-yt-error").textContent = msg || "";
}

async function loadYoutube() {
  let a;
  try { a = await api.youtubeAccount(); } catch { return; }
  renderYoutube(a);
  // The consent happens in the browser: follow it until it ends.
  clearTimeout(state.ytPoll);
  state.ytPoll = a.connecting ? setTimeout(loadYoutube, 2000) : null;
  if (state.ytFocus) {
    state.ytFocus = false;
    const card = el("cfg-yt-card");
    card.scrollIntoView({ block: "start", behavior: "smooth" });
    card.classList.remove("flash");
    void card.offsetWidth; // restart the animation
    card.classList.add("flash");
  }
}

async function saveClient(body) {
  ytError("");
  try {
    renderYoutube(await api.setYoutubeClient(body));
  } catch (err) {
    ytError(String(err.message || err));
  }
}

async function pickClientJson() {
  const dialog = window.__TAURI__?.dialog;
  if (!dialog) { el("cfg-yt-file").click(); return; } // the browser reads it instead
  let path;
  try {
    path = await dialog.open({
      title: "Escolher o JSON da credencial do Google",
      multiple: false,
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
  } catch (err) { ytError(String(err.message || err)); return; }
  if (path) saveClient({ path });
}

/** "Abrir Configurações" from elsewhere (the Publicar card): lands on YouTube. */
export function openYoutubeSettings() {
  state.ytFocus = true;
  location.hash = "#/config";
}

// Checking every agent CLI takes a few seconds: until the first answer, a
// skeleton in the list's own shape says so (later refreshes keep the list up).
const SKELETON_ROWS = 7;

function renderAgentsLoading() {
  const row = `
  <div class="cfg-agent skel" aria-hidden="true">
    <span class="skel-dot"></span>
    <span class="who"><span class="skel-bar" style="width: 38%"></span><span class="skel-bar sm" style="width: 22%"></span></span>
    <span></span>
  </div>`;
  el("cfg-agents").innerHTML =
    `<div class="cfg-loading" role="status"><span class="mini-spin"></span>Verificando os agentes de IA instalados no seu computador… leva alguns segundos.</div>` +
    row.repeat(SKELETON_ROWS);
  el("cfg-fallback").innerHTML = `<option>Carregando…</option>`;
  el("cfg-fallback").disabled = true;
}

async function loadAgents() {
  if (!state.agents.length) renderAgentsLoading();
  try {
    state.agents = await api.agents();
  } catch (err) {
    setError(String(err.message || err));
    if (!state.agents.length) el("cfg-agents").innerHTML = `<div class="empty small">Não deu pra verificar os agentes de IA.</div>`;
    return;
  }
  el("cfg-fallback").disabled = false;
  renderAgents();
  renderOllama();
}

async function load() {
  try {
    const s = await api.settings();
    setEngine(true);
    state.saved = s;
    state.draft = clone(s);
  } catch (err) {
    setEngine(false);
    setError(`não deu pra ler as configurações: ${err.message || err}`);
    return;
  }
  renderForm();
  syncSave();
  renderFolders();
  loadYoutube();
  await loadAgents();
}

async function save() {
  clearTimeout(saveTimer);
  setError("");
  const sent = JSON.stringify(state.draft);
  try {
    const s = await api.saveSettings(JSON.parse(sent));
    state.saved = s;
    if (JSON.stringify(state.draft) !== sent) { syncSave(); return; } // changed meanwhile: save that too
    const agentsBefore = JSON.stringify(state.draft.agent);
    state.draft = clone(s);
    renderForm();
    // Only when saving changed them (e.g. a fallback equal to the primary is
    // cleared): re-rendering every time steals the focus from a model being typed.
    if (JSON.stringify(s.agent) !== agentsBefore) renderAgents();
    setStatus("Salvo", "ok");
  } catch (err) {
    setError(String(err.message || err));
    setStatus("Não salvo", "err");
  }
}

async function test(name) {
  state.busy[name] = true;
  renderAgents();
  try {
    state.results[name] = await api.testAgent(name, state.draft.agent.models[name] || null);
  } catch (err) {
    state.results[name] = { ok: false, error: String(err.message || err) };
  }
  state.busy[name] = false;
  renderAgents();
}

function wire() {
  el("cfg-agents").addEventListener("change", (e) => {
    if (e.target.name === "cfg-primary") {
      state.draft.agent.primary = e.target.value;
      if (state.draft.agent.fallback === e.target.value) state.draft.agent.fallback = null;
      renderAgents();
    }
    if (e.target.dataset.model) state.draft.agent.models[e.target.dataset.model] = e.target.value.trim() || null;
    syncSave();
  });
  el("cfg-agents").addEventListener("input", (e) => {
    if (e.target.dataset.model) {
      state.draft.agent.models[e.target.dataset.model] = e.target.value.trim() || null;
      syncSave();
    }
  });
  el("cfg-agents").addEventListener("click", async (e) => {
    const ks = e.target.closest("[data-key-save]");
    if (ks) {
      const input = el("cfg-agents").querySelector(`[data-key-input="${ks.dataset.keySave}"]`);
      try {
        await api.saveOpenrouterKey(input.value);
        state.results[ks.dataset.keySave] = { ok: true, seconds: "—", saved: true };
      } catch (err) {
        state.results[ks.dataset.keySave] = { ok: false, error: String(err.message || err) };
      }
      return loadAgents();
    }
    const kr = e.target.closest("[data-key-remove]");
    if (kr) {
      e.preventDefault();
      try { await api.deleteOpenrouterKey(); } catch (err) { setError(String(err.message || err)); }
      delete state.results[kr.dataset.keyRemove];
      return loadAgents();
    }
    const t = e.target.closest("[data-test]");
    if (t) return test(t.dataset.test);
    const l = e.target.closest("[data-login]");
    if (l) {
      try {
        const r = await api.loginAgent(l.dataset.login);
        state.results[l.dataset.login] = { ok: false, error: `abri o Terminal com \`${r.command}\` — termine o login lá e clique em Testar` };
      } catch (err) {
        state.results[l.dataset.login] = { ok: false, error: String(err.message || err) };
      }
      renderAgents();
    }
  });
  document.querySelector('[data-screen="config"]').addEventListener("click", (e) => {
    const a = e.target.closest("[data-docs]");
    // The webview won't follow links: the engine opens them in the browser.
    if (a) { e.preventDefault(); api.openUrl(a.dataset.docs).catch((err) => setError(String(err.message || err))); }
    const open = e.target.closest("[data-folder-open]");
    if (open) api.openFolder(open.dataset.folderOpen).catch((err) => setError(String(err.message || err)));
    const pick = e.target.closest("[data-folder-pick]");
    if (pick) pickFolder(pick.dataset.folderPick);
    const reset = e.target.closest("[data-folder-reset]");
    if (reset) { e.preventDefault(); saveFolder(reset.dataset.folderReset, null); } // back to workspace/input|output
  });
  el("cfg-fallback").addEventListener("change", (e) => {
    state.draft.agent.fallback = e.target.value || null;
    renderAgents();
    syncSave();
  });
  const bind = (id, key, get = (x) => x.value.trim() || null) =>
    el(id).addEventListener("input", (e) => { state.draft[key] = get(e.target); syncSave(); });
  el("cfg-language").addEventListener("change", (e) => { state.draft.language = e.target.value; syncSave(); });
  el("cfg-whisper").addEventListener("change", (e) => { state.draft.whisper_model = e.target.value; syncSave(); });
  el("cfg-coldopen").addEventListener("change", (e) => { state.draft.cold_open = e.target.checked; syncSave(); });
  el("cfg-reorder").addEventListener("change", (e) => { state.draft.reorder = e.target.checked; syncSave(); });
  el("btn-ollama-pull").addEventListener("click", async () => {
    const model = el("cfg-ollama-pull-model").value.trim() || "qwen2.5:7b";
    try { await api.pullOllama(model); } catch (err) { setError(String(err.message || err)); }
    loadAgents();
  });
  el("btn-cfg-yt").addEventListener("click", async () => {
    ytError("");
    state.ytTried = !el("btn-cfg-yt").dataset.connected;
    try {
      if (el("btn-cfg-yt").dataset.connected) await api.disconnectYoutube();
      else await api.connectYoutube();
    } catch (err) { ytError(String(err.message || err)); }
    loadYoutube();
  });
  el("btn-cfg-yt-cancel").addEventListener("click", async () => {
    el("btn-cfg-yt-cancel").disabled = true;
    try { renderYoutube(await api.cancelYoutubeConnect()); } catch (err) { ytError(String(err.message || err)); }
    el("btn-cfg-yt-cancel").disabled = false;
    loadYoutube();
  });
  el("cfg-yt-card").addEventListener("click", (e) => {
    if (!e.target.closest("[data-yt-json]")) return;
    e.preventDefault();
    pickClientJson();
  });
  el("cfg-yt-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) saveClient({ content: await file.text() });
  });
}

export default {
  id: "config",
  mount() {
    if (!state.wired) { wire(); state.wired = true; }
    setError("");
    if (!state.agents.length) renderAgentsLoading(); // before the first byte arrives
    load();
  },
  unmount() {
    if (dirty()) save(); // a change still waiting its moment is saved on the way out
    clearInterval(state.poll);
    state.poll = null;
    clearTimeout(state.ytPoll);
    state.ytPoll = null;
    state.ytTried = false;
  },
};
