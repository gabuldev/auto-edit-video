// Aviso de versão nova. Só no app instalado (no navegador não há __TAURI__).
// Mac/Windows: o updater do Tauri baixa o pacote assinado e reinstala.
// Linux (.deb/.rpm não se atualizam sozinhos): a faixa abre a página do release.
// Nunca atualiza sem a pessoa clicar.

import { library } from "./api.js";
import { el } from "./shell.js";

const T = window.__TAURI__;
const EVERY = 6 * 3600 * 1000;
const RELEASES = "https://api.github.com/repos/gabuldev/auto-edit-video/releases/latest";
const LINUX = /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);

let found = null;      // {version, notes, update?, url?}
let dismissed = false; // "Depois": some até a próxima vez que o app abrir
let installing = false;

/** a > b, comparando "0.41.0" número a número. */
export function newer(a, b) {
  const pa = String(a).replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);
  const pb = String(b).replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  }
  return false;
}

async function checkLinux() {
  const r = await fetch(RELEASES, { cache: "no-store" });
  if (!r.ok) return null;
  const rel = await r.json();
  // O release nasce antes dos instaladores: só avisa quando o pacote já está lá.
  const ready = (rel.assets || []).some((a) => /\.(deb|rpm)$/.test(a.name));
  if (!ready || !newer(rel.tag_name, await T.app.getVersion())) return null;
  return { version: rel.tag_name.replace(/^v/, ""), notes: rel.body || "", url: rel.html_url };
}

async function checkUpdater() {
  const update = await T.updater.check();
  return update ? { version: update.version, notes: update.body || "", update } : null;
}

async function busy() {
  try {
    return (await library()).some((v) => v.status === "running");
  } catch {
    return false; // motor offline: nada rodando que reiniciar possa matar
  }
}

async function render() {
  const bar = el("update-bar");
  if (!found || dismissed) { bar.hidden = true; return; }
  el("update-title").textContent = `Versão ${found.version} disponível`;
  el("update-notes").textContent = found.notes.trim();
  el("update-notes-wrap").hidden = !found.notes.trim();
  const go = el("update-go");
  go.textContent = found.update ? "Atualizar" : "Baixar";
  if (!installing) {
    const running = found.update && (await busy());
    go.disabled = running;
    el("update-msg").textContent = running ? "termine a edição em andamento pra atualizar" : "";
  }
  bar.hidden = false;
}

async function check() {
  if (installing) return;
  try {
    found = LINUX ? await checkLinux() : await checkUpdater();
  } catch {
    found = null; // sem internet, GitHub fora, release sem latest.json: fica quieto
  }
  render();
}

async function install() {
  const msg = el("update-msg");
  const go = el("update-go");
  if (!found.update) {
    T.opener.openUrl(found.url);
    return;
  }
  if (await busy()) { render(); return; }
  installing = true;
  go.disabled = true;
  el("update-later").hidden = true;
  let total = 0;
  let got = 0;
  try {
    await found.update.download((ev) => {
      if (ev.event === "Started") total = ev.data.contentLength || 0;
      else if (ev.event === "Progress") {
        got += ev.data.chunkLength;
        msg.textContent = total ? `baixando… ${Math.round((got / total) * 100)}%` : "baixando…";
      } else if (ev.event === "Finished") msg.textContent = "instalando…";
    });
    // Windows: o instalador não troca arquivos que o motor está usando.
    await T.core.invoke("stop_engine_for_update");
    await found.update.install();
    await T.process.relaunch();
  } catch (e) {
    installing = false;
    msg.textContent = `não deu pra atualizar: ${e?.message || e}. Feche e abra o app pra tentar de novo.`;
    go.disabled = false;
    el("update-later").hidden = false;
  }
}

export function startUpdateCheck() {
  if (!T?.updater) return;
  el("update-go").addEventListener("click", install);
  el("update-later").addEventListener("click", () => { dismissed = true; render(); });
  check();
  setInterval(check, EVERY);
  // Uma edição pode começar ou terminar com a faixa aberta.
  setInterval(() => { if (found && !dismissed) render(); }, 10_000);
}
