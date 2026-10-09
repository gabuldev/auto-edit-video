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
  ollama: "escolha abaixo",
};

const state = { saved: null, draft: null, agents: [], results: {}, busy: {}, poll: null, wired: false };

const clone = (x) => JSON.parse(JSON.stringify(x));

function dirty() {
  return JSON.stringify(state.saved) !== JSON.stringify(state.draft);
}

function setError(msg) {
  el("cfg-error").hidden = !msg;
  el("cfg-error").textContent = msg || "";
}

function syncSave() {
  el("btn-cfg-save").disabled = !dirty();
  el("btn-cfg-save").textContent = dirty() ? "Salvar alterações" : "Salvo";
}

function agentMeta(a) {
  if (!a.installed) return `<span class="meta bad">não instalado · <a href="#" data-docs="${escapeHtml(a.docs)}">como instalar</a></span>`;
  if (a.name === "ollama") {
    if (!a.server) return `<span class="meta bad">instalado, mas o servidor não está rodando (abra o app do Ollama)</span>`;
    return `<span class="meta">${escapeHtml(a.version || "")} · ${a.models.length} modelo(s)</span>`;
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

function renderForm() {
  const d = state.draft;
  el("cfg-inbox").value = d.inbox || "";
  el("cfg-overlays").value = d.overlays_dir || "";
  el("cfg-language").value = d.language;
  el("cfg-whisper").value = d.whisper_model;
  el("cfg-coldopen").checked = d.cold_open;
  el("cfg-reorder").checked = d.reorder;
}

async function renderYoutube() {
  let a;
  try { a = await api.youtubeAccount(); } catch { return; }
  el("cfg-yt-status").textContent = a.connected
    ? `conectado como ${a.channel || "?"}`
    : a.needs_reconnect ? "precisa reconectar (permissões novas)" : "não conectado";
  el("btn-cfg-yt").textContent = a.connected ? "Desconectar" : a.needs_reconnect ? "Reconectar YouTube" : "Conectar YouTube";
  el("btn-cfg-yt").dataset.connected = a.connected ? "1" : "";
}

async function loadAgents() {
  try {
    state.agents = await api.agents();
  } catch (err) {
    setError(String(err.message || err));
    return;
  }
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
  renderYoutube();
  await loadAgents();
}

async function save() {
  setError("");
  try {
    const s = await api.saveSettings(state.draft);
    state.saved = s;
    state.draft = clone(s);
    renderForm();
    renderAgents();
  } catch (err) {
    setError(String(err.message || err));
  }
  syncSave();
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
  });
  el("cfg-fallback").addEventListener("change", (e) => {
    state.draft.agent.fallback = e.target.value || null;
    renderAgents();
    syncSave();
  });
  const bind = (id, key, get = (x) => x.value.trim() || null) =>
    el(id).addEventListener("input", (e) => { state.draft[key] = get(e.target); syncSave(); });
  bind("cfg-inbox", "inbox");
  bind("cfg-overlays", "overlays_dir");
  el("cfg-language").addEventListener("change", (e) => { state.draft.language = e.target.value; syncSave(); });
  el("cfg-whisper").addEventListener("change", (e) => { state.draft.whisper_model = e.target.value; syncSave(); });
  el("cfg-coldopen").addEventListener("change", (e) => { state.draft.cold_open = e.target.checked; syncSave(); });
  el("cfg-reorder").addEventListener("change", (e) => { state.draft.reorder = e.target.checked; syncSave(); });
  el("btn-cfg-save").addEventListener("click", save);
  el("btn-ollama-pull").addEventListener("click", async () => {
    const model = el("cfg-ollama-pull-model").value.trim() || "qwen2.5:7b";
    try { await api.pullOllama(model); } catch (err) { setError(String(err.message || err)); }
    loadAgents();
  });
  el("btn-cfg-yt").addEventListener("click", async () => {
    try {
      if (el("btn-cfg-yt").dataset.connected) await api.disconnectYoutube();
      else await api.connectYoutube();
    } catch (err) { setError(String(err.message || err)); }
    // The consent happens in the browser; check back a few times.
    for (const wait of [1500, 5000, 10000, 20000]) setTimeout(renderYoutube, wait);
    renderYoutube();
  });
}

export default {
  id: "config",
  mount() {
    if (!state.wired) { wire(); state.wired = true; }
    setError("");
    load();
  },
  unmount() {
    clearInterval(state.poll);
    state.poll = null;
  },
};
