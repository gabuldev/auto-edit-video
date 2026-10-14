// Primeira execução — num computador sem nada, o que falta pra editar: um
// agente de IA instalado, logado e testado, e o modelo do Whisper baixado.
// Fica checando sozinho enquanto a pessoa instala/loga no Terminal.

import * as api from "./api.js";
import { el, escapeHtml } from "./shell.js";
import { go } from "./router.js";

const state = { setup: null, notes: {}, testing: {}, poll: null, wired: false };

const DISMISS_KEY = "auto-edit:setup-later";

function setError(msg) {
  el("ws-error").hidden = !msg;
  el("ws-error").textContent = msg || "";
}

function agentRow(a, recommended) {
  const s = state.setup;
  const verified = s.verified_agent === a.name;
  const usable = a.installed && (a.name !== "ollama" || (a.models || []).length);
  let meta;
  if (verified) meta = `<span class="meta ok">✓ funcionando</span>`;
  else if (!a.installed && a.api_key) meta = `<span class="meta">precisa de uma chave da API</span>`;
  else if (!a.installed) meta = `<span class="meta">não instalado</span>`;
  else if (a.name === "ollama" && !(a.models || []).length) meta = `<span class="meta">instalado — falta baixar um modelo (Configurações)</span>`;
  else meta = `<span class="meta">instalado ${escapeHtml(a.version || "")} — falta testar</span>`;
  const note = state.notes[a.name];
  return `
    <div class="wagent">
      <b>${escapeHtml(a.label)}</b>${recommended ? ` <span class="badge long">recomendado</span>` : ""}
      ${meta}
      <span class="grow"></span>
      ${!a.installed && !a.api_key ? `<button class="btn btn-sm${recommended ? " btn-primary" : ""}" data-install="${a.name}">Instalar</button>` : ""}
      ${!a.installed && a.api_key ? `<button class="btn btn-sm" data-install="${a.name}">Criar chave</button>` : ""}
      ${a.installed && a.login_command && !verified ? `<button class="btn btn-sm" data-login="${a.name}">Fazer login</button>` : ""}
      ${usable && !verified ? `<button class="btn btn-sm${recommended ? " btn-primary" : ""}" data-test="${a.name}" ${state.testing[a.name] ? "disabled" : ""}>${state.testing[a.name] ? "testando…" : "Testar"}</button>` : ""}
    </div>
    ${!a.installed && a.api_key ? `<div class="wkey">
      <input class="input mono" type="password" autocomplete="off" spellcheck="false" data-key-input="${a.name}" placeholder="cole a chave: sk-or-…" />
      <button class="btn btn-sm btn-primary" data-key-save="${a.name}">Salvar chave</button>
    </div>` : ""}
    ${note ? `<div class="wnote">${note}</div>` : ""}`;
}

function render() {
  const s = state.setup;
  const agents = s.agents || [];
  const claude = agents.find((a) => a.name === "claude");
  // This re-renders every few seconds: keep a key being typed (and its focus).
  const typing = {};
  el("ws-agent").querySelectorAll("[data-key-input]").forEach((i) => { typing[i.dataset.keyInput] = i.value; });
  const focused = document.activeElement?.dataset?.keyInput;
  el("ws-agent-main").innerHTML = claude ? agentRow(claude, true) : "";
  el("ws-agent-others").innerHTML = agents.filter((a) => a.name !== "claude").map((a) => agentRow(a, false)).join("");
  el("ws-agent").querySelectorAll("[data-key-input]").forEach((i) => {
    i.value = typing[i.dataset.keyInput] || "";
    if (i.dataset.keyInput === focused) i.focus();
  });
  el("ws-agent-state").textContent = s.agent_ready ? "pronto" : "pendente";
  el("ws-agent-state").classList.toggle("ok", s.agent_ready);

  const w = s.whisper;
  el("ws-whisper-sub").textContent = `o Whisper "${w.model}" (~${w.size_mb} MB) transcreve o áudio no seu computador, sem enviar nada.`;
  el("ws-whisper-state").textContent = w.ready ? "pronto" : w.downloading ? "baixando" : "pendente";
  el("ws-whisper-state").classList.toggle("ok", w.ready);
  el("btn-ws-whisper").hidden = w.ready || w.downloading;
  el("ws-whisper-progress").hidden = !w.downloading;
  const pct = Math.round((w.progress || 0) * 100);
  el("ws-whisper-bar").style.width = `${pct}%`;
  el("ws-whisper-pct").textContent = `${pct}%`;
  if (w.error) setError(`não deu pra baixar o Whisper: ${w.error}`);

  el("btn-ws-done").disabled = !s.ready;
}

async function load() {
  try {
    state.setup = await api.setupState();
  } catch (err) {
    setError(`o motor não respondeu: ${err.message || err}`);
    return;
  }
  render();
}

async function act(e) {
  const k = e.target.closest("[data-key-save]");
  if (k) {
    setError("");
    const input = el("ws-agent").querySelector(`[data-key-input="${k.dataset.keySave}"]`);
    try {
      await api.saveOpenrouterKey(input.value);
      state.notes[k.dataset.keySave] = "Chave salva. Agora clique em <b>Testar</b>.";
    } catch (err) {
      setError(String(err.message || err));
    }
    return load();
  }
  const b = e.target.closest("[data-install],[data-login],[data-test]");
  if (!b) return;
  setError("");
  const name = b.dataset.install || b.dataset.login || b.dataset.test;
  try {
    if (b.dataset.install) {
      const r = await api.installAgent(name);
      state.notes[name] = r.command
        ? "Abri o Terminal com o instalador oficial. Quando terminar, volte aqui — esta tela detecta sozinha."
        : name === "openrouter"
          ? "Abri o OpenRouter no navegador. Crie uma chave, cole aqui embaixo e clique em Salvar chave."
          : `Abri a página de download no navegador. Instale, volte aqui e clique em Testar.`;
    } else if (b.dataset.login) {
      const r = await api.loginAgent(name);
      state.notes[name] = `Abri o Terminal com <code class="mono">${escapeHtml(r.command)}</code>. Faça o login lá (no Claude Code: digite <code class="mono">/login</code>) e depois clique em <b>Testar</b>.`;
    } else {
      state.testing[name] = true;
      render();
      const r = await api.testAgent(name, null);
      state.testing[name] = false;
      state.notes[name] = r.ok
        ? `✓ respondeu em ${r.seconds}s — este agente vai editar seus vídeos.`
        : `✗ ${escapeHtml(r.error || "não respondeu")} — se ainda não fez login, clique em <b>Fazer login</b>.`;
    }
  } catch (err) {
    state.testing[name] = false;
    setError(String(err.message || err));
  }
  await load();
}

function wire() {
  el("ws-agent").addEventListener("click", act);
  el("btn-ws-whisper").addEventListener("click", async () => {
    setError("");
    try { await api.downloadWhisper(state.setup.whisper.model); } catch (err) { setError(String(err.message || err)); }
    load();
  });
  el("btn-ws-done").addEventListener("click", () => go("/"));
  el("ws-later").addEventListener("click", () => {
    try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* storage blocked: just go */ }
  });
}

// On launch: send a machine that can't edit yet straight here (unless the
// person chose "configurar depois"); otherwise show a banner in the library.
export async function checkSetup() {
  let s;
  try { s = await api.setupState(); } catch { return; }
  const missing = [];
  if (!s.agent_ready) missing.push("um agente de IA funcionando");
  if (!s.whisper.ready) missing.push("o modelo de transcrição");
  el("setup-banner").hidden = s.ready;
  el("setup-banner-text").textContent = missing.length ? `Falta ${missing.join(" e ")}.` : "";
  let later = false;
  try { later = localStorage.getItem(DISMISS_KEY) === "1"; } catch { /* ignore */ }
  if (!s.ready && !later && (location.hash === "" || location.hash === "#/")) go("/bemvindo");
}

export default {
  id: "welcome",
  mount() {
    if (!state.wired) { wire(); state.wired = true; }
    setError("");
    load();
    // Installs and logins happen in the Terminal: keep checking.
    clearInterval(state.poll);
    state.poll = setInterval(load, 3000);
  },
  unmount() {
    clearInterval(state.poll);
    state.poll = null;
  },
};
