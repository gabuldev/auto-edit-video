// Estilos: the brand (name, handle, logo), the style gallery with real
// previews (rendered by the engine on a frame of your own footage) and the
// editor. A style is just tokens; the engine validates whatever we send.
import * as api from "./api.js";
import { el, escapeHtml, setEngine } from "./shell.js";

const KINDS = ["thumbnail", "lower_third", "cta"];
const ICON_LABELS = { like: "👍 like", subscribe: "▶ inscrever", bell: "🔔 sino", comment: "💬 comentar" };

const state = {
  data: null, // GET /api/styles
  selected: null, // style id shown in the detail
  draft: null, // tokens being edited (null: not editing)
  fresh: false, // the draft is a new style (from the AI): saving never overwrites
  aiImage: null, // data: URL of the AI's reference image
  generating: false, // the AI is working: the gallery and the editor wait
  settings: null,
  thumbs: {}, // style id → blob URL of its gallery thumbnail
  seq: 0, // ignores previews that arrive after a newer request
  timers: {},
};

const NO_VISION = "seu agente de IA não enxerga imagens — troque nas Configurações (Claude, Codex, OpenRouter ou um modelo de visão no Ollama)";
const clone = (x) => JSON.parse(JSON.stringify(x));
const styleOf = (id) => state.data?.styles.find((s) => s.id === id);
const shown = () => state.draft || styleOf(state.selected)?.tokens;
const readDataUrl = (file) => new Promise((ok, fail) => {
  const r = new FileReader();
  r.onload = () => ok(r.result);
  r.onerror = fail;
  r.readAsDataURL(file);
});

function setError(msg) {
  el("sty-error").hidden = !msg;
  el("sty-error").textContent = msg || "";
}

function debounce(key, fn, ms) {
  clearTimeout(state.timers[key]);
  state.timers[key] = setTimeout(fn, ms);
}

function getTok(tokens, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), tokens);
}

function setTok(tokens, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  keys.reduce((o, k) => (o[k] ??= {}), tokens)[last] = value;
}

// ── Brand ────────────────────────────────────────────────────────────────────

function renderBrand() {
  const b = state.data.brand || {};
  const saved = state.settings?.brand || {};
  if (document.activeElement !== el("sty-name")) el("sty-name").value = saved.name || "";
  if (document.activeElement !== el("sty-handle")) el("sty-handle").value = saved.handle || "";
  el("sty-name").placeholder = b.name && !saved.name ? `padrão: ${b.name} (canal do YouTube)` : "seu nome ou do canal";
  el("sty-logo-initial").textContent = ((saved.name || b.name || "?").trim()[0] || "?").toUpperCase();
  el("sty-logo-img").hidden = !b.logo;
  el("sty-logo-remove").hidden = !b.logo;
  el("sty-logo-bg-wrap").hidden = !b.logo;
  if (b.logo && !el("sty-logo-img").src) el("sty-logo-img").src = api.logoUrl();
  if (!b.logo) el("sty-logo-img").removeAttribute("src");
  const bg = saved.logo_bg;
  el("sty-logo-bg-own").checked = !!bg;
  el("sty-logo-bg").disabled = !bg;
  if (bg) el("sty-logo-bg").value = bg;
  // the button shows the logo on the color it will get in the video
  el("sty-logo").style.background = b.logo ? bg || shown()?.colors.accent || "" : "";
  el("sty-overlays").value = state.settings?.overlays_dir || "";
}

async function saveBrand() {
  try {
    const name = el("sty-name").value.trim() || null;
    let handle = el("sty-handle").value.trim() || null;
    if (handle && !handle.startsWith("@")) handle = `@${handle}`;
    const logo_bg = el("sty-logo-bg-own").checked ? el("sty-logo-bg").value : null;
    state.settings = await api.saveSettings({ brand: { ...(state.settings?.brand || {}), name, handle, logo_bg } });
    renderBrand();
    el("sty-brand-saved").textContent = "salvo";
    setTimeout(() => (el("sty-brand-saved").textContent = ""), 1500);
    await reload(false);
    refreshPreviews(true);
  } catch (err) {
    setError(String(err.message || err));
  }
}

async function pickLogo(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) return setError("imagem grande demais (máx. 5 MB)");
  const data = await readDataUrl(file);
  try {
    await api.uploadLogo(data);
    state.settings = await api.settings();
    await reload(false);
    refreshPreviews(true);
  } catch (err) {
    setError(String(err.message || err));
  }
}

// ── Gallery ──────────────────────────────────────────────────────────────────

function renderGallery() {
  const { styles, active } = state.data;
  el("sty-gallery").innerHTML = `
      <button class="sty-card sty-card-ai" data-ai>
        <div class="sty-card-img sty-ai-art">✨</div>
        <div class="sty-card-meta"><b>Criar com IA</b></div>
      </button>` + styles
    .map((s) => `
      <button class="sty-card${s.id === state.selected ? " selected" : ""}" data-style="${escapeHtml(s.id)}">
        <div class="sty-card-img">${state.thumbs[s.id] ? `<img src="${state.thumbs[s.id]}" alt="" />` : `<div class="sty-spin"></div>`}</div>
        <div class="sty-card-meta">
          <span class="sty-swatch" style="background:${escapeHtml(s.tokens.colors.accent)}"></span>
          <b>${escapeHtml(s.name)}</b>
          ${s.id === active ? `<span class="badge sty-active">em uso</span>` : s.builtin ? "" : `<span class="badge">seu</span>`}
        </div>
      </button>`)
    .join("");
}

// Gallery thumbnails one at a time (the engine renders them), newest data first.
async function loadGalleryThumbs() {
  for (const s of state.data.styles) {
    if (state.thumbs[s.id]) continue;
    try {
      state.thumbs[s.id] = await api.stylePreview(s.tokens, "thumbnail");
    } catch {
      state.thumbs[s.id] = "";
    }
    renderGallery();
  }
}

// ── Detail + previews ────────────────────────────────────────────────────────

function renderDetail() {
  const s = styleOf(state.selected);
  if (!s) return;
  const editing = !!state.draft;
  el("sty-detail-name").textContent = state.fresh ? "Novo estilo" : editing ? `Personalizando: ${s.name}` : s.name;
  el("sty-detail-desc").textContent = state.fresh ? "criado pela IA — ajuste e salve" : editing ? "as prévias atualizam enquanto você mexe" : s.description || "";
  el("btn-sty-export").hidden = editing;
  el("btn-sty-use").hidden = editing || s.id === state.data.active;
  el("btn-sty-edit").hidden = editing;
  el("btn-sty-delete").hidden = editing || s.builtin;
  el("sty-editor").hidden = !editing;
  if (editing) renderEditor();
}

async function refreshPreviews(force = false) {
  const tokens = shown();
  if (!tokens) return;
  const seq = ++state.seq;
  if (force) state.thumbs = {};
  for (const kind of KINDS) {
    const box = document.querySelector(`.sty-shot[data-kind="${kind}"]`);
    box.classList.add("loading");
  }
  for (const kind of KINDS) {
    const box = document.querySelector(`.sty-shot[data-kind="${kind}"]`);
    try {
      const url = await api.stylePreview(tokens, kind);
      if (seq !== state.seq) return URL.revokeObjectURL(url);
      const img = box.querySelector("img");
      if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
      img.src = url;
      setError("");
    } catch (err) {
      if (seq === state.seq) setError(String(err.message || err));
    }
    box.classList.remove("loading");
  }
  if (force) loadGalleryThumbs();
}

function select(id) {
  if (state.generating) return;
  if (state.draft && id !== state.selected && !confirmDiscard()) return;
  state.draft = null;
  state.fresh = false;
  state.selected = id;
  renderGallery();
  renderDetail();
  refreshPreviews();
}

// Discarding edits: an inline confirm would block the webview; ask with the button label.
function confirmDiscard() {
  const b = el("btn-sty-cancel");
  if (b.dataset.armed) return true;
  b.dataset.armed = "1";
  b.textContent = "Clique de novo pra descartar";
  setTimeout(() => { delete b.dataset.armed; b.textContent = "Descartar"; }, 2500);
  return false;
}

// ── Editor ───────────────────────────────────────────────────────────────────

function fmt(path, v) {
  if (path === "panel_opacity") return `${Math.round(v * 100)}%`;
  if (path === "speed") return `${Math.round(v * 100)}%`;
  if (path === "radius") return `${v}px`;
  return v;
}

function renderEditor() {
  const t = state.draft;
  const fonts = state.data.fonts.map((f) => `<option value="${f.id}">${escapeHtml(f.label)}</option>`).join("");
  document.querySelectorAll("#sty-editor [data-fonts]").forEach((s) => { if (!s.options.length) s.innerHTML = fonts; });
  document.querySelectorAll("#sty-editor [data-tok]").forEach((input) => {
    const v = getTok(t, input.dataset.tok);
    if (input.type === "checkbox") input.checked = !!v;
    else input.value = v;
  });
  document.querySelectorAll("#sty-editor [data-out]").forEach((o) => (o.textContent = fmt(o.dataset.out, getTok(t, o.dataset.out))));
  renderSteps();
  if (document.activeElement !== el("sty-html")) el("sty-html").value = t.thumbnail.html || "";
  el("sty-html-reset").hidden = !t.thumbnail.html;
  const s = styleOf(state.selected);
  if (!el("sty-save-name").value) el("sty-save-name").value = s.builtin ? `Meu ${s.name}` : s.name;
  el("btn-sty-save-new").hidden = s.builtin || state.fresh; // a preset or an AI draft is always saved as new
  el("sty-logo-colors").hidden = !state.data.brand?.logo;
}

function renderSteps() {
  const steps = state.draft.cta.steps;
  const icons = state.data.icons.map((i) => `<option value="${i}">${ICON_LABELS[i] || i}</option>`).join("");
  el("sty-steps").innerHTML = steps
    .map((st, i) => `
      <div class="sty-step" data-step="${i}">
        <select class="input" data-step-key="icon">${icons}</select>
        <input class="input" data-step-key="text" maxlength="24" value="${escapeHtml(st.text)}" />
        <label class="sty-step-color" title="cor própria (sem: a de destaque)">
          <input type="checkbox" data-step-key="own" ${st.color ? "checked" : ""} />
          <input type="color" data-step-key="color" value="${st.color || state.draft.colors.accent}" ${st.color ? "" : "disabled"} />
        </label>
        ${steps.length > 1 ? `<button class="btn btn-sm btn-icon" data-step-remove title="remover">×</button>` : ""}
      </div>`)
    .join("");
  el("sty-steps").querySelectorAll("[data-step]").forEach((row, i) => (row.querySelector("[data-step-key=icon]").value = steps[i].icon));
  el("sty-step-add").hidden = steps.length >= 3;
}

function changed() {
  document.querySelectorAll("#sty-editor [data-out]").forEach((o) => (o.textContent = fmt(o.dataset.out, getTok(state.draft, o.dataset.out))));
  debounce("preview", () => refreshPreviews(), 350);
}

function startEditing() {
  if (state.generating) return;
  state.draft = clone(styleOf(state.selected).tokens);
  el("sty-save-name").value = "";
  renderDetail();
}

async function saveDraft(asNew) {
  const s = styleOf(state.selected);
  const name = el("sty-save-name").value.trim();
  if (!name) return setError("dê um nome pro estilo");
  try {
    const saved = await api.saveStyle({ id: asNew || s.builtin || state.fresh ? null : s.id, name, tokens: state.draft, activate: true });
    state.draft = null;
    state.fresh = false;
    delete state.thumbs[saved.id];
    await reload(false);
    select(saved.id);
    loadGalleryThumbs();
  } catch (err) {
    setError(String(err.message || err));
  }
}

// ── AI, logo colors, export / import ─────────────────────────────────────────

async function generateAi() {
  const description = el("sty-ai-desc").value.trim();
  if (!description && !state.aiImage) return setError("descreva o estilo ou anexe uma imagem");
  if (state.aiImage && !state.data.ai_vision) return setError(NO_VISION);
  if (state.draft && !confirmDiscard()) {
    el("sty-ai-status").textContent = "você tem edições abertas: clique de novo pra descartar";
    return;
  }
  setGenerating(true);
  el("sty-ai-status").textContent = "começando… (1 a 3 min)";
  setError("");
  try {
    const draft = await api.generateStyle(description, state.aiImage, (msg) => (el("sty-ai-status").textContent = `${msg}…`));
    state.draft = draft.tokens;
    state.fresh = true;
    el("sty-save-name").value = draft.name;
    el("sty-ai").hidden = true;
    setAiImage(null);
    renderDetail();
    refreshPreviews();
    el("sty-editor").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    setGenerating(false);
    el("sty-ai-status").textContent = "";
  }
}

// The AI adjusts the open draft's layout ("título maior, tira o círculo").
async function adjustAi() {
  const request = el("sty-adjust-req").value.trim();
  if (!request) return el("sty-adjust-req").focus();
  setGenerating(true);
  el("sty-adjust-status").textContent = "começando…";
  setError("");
  try {
    const draft = await api.adjustStyle(state.draft, request, (msg) => (el("sty-adjust-status").textContent = `${msg}…`));
    state.draft = draft.tokens;
    el("sty-adjust-req").value = "";
    renderEditor();
    refreshPreviews();
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    setGenerating(false);
    el("sty-adjust-status").textContent = "";
  }
}

// While the AI works, nothing else can start a draft that its answer would replace.
function setGenerating(on) {
  state.generating = on;
  el("btn-sty-ai-go").disabled = on;
  el("btn-sty-edit").disabled = on;
  el("btn-sty-adjust").disabled = on;
  el("btn-sty-save").disabled = on;
  el("btn-sty-save-new").disabled = on;
  el("sty-gallery").classList.toggle("busy", on);
}

// The AI looks at it: keep up to 1280px (enough to read the layout), JPEG
// so a full-screen retina screenshot stays far below the engine's 5 MB limit.
async function takeAiImage(file, name) {
  if (!file) return;
  try {
    const img = await createImageBitmap(file);
    const k = Math.min(1, 1280 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(img.width * k));
    c.height = Math.max(1, Math.round(img.height * k));
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    setAiImage(c.toDataURL("image/jpeg", 0.9), name || "imagem");
  } catch {
    setError("não consegui ler a imagem");
  }
}

function setAiImage(dataUrl, name = "") {
  state.aiImage = dataUrl;
  el("sty-ai-img").textContent = name;
  el("sty-ai-img-remove").hidden = !dataUrl;
}

async function useLogoColors() {
  try {
    const { suggested } = await api.stylePalette();
    if (!suggested) return setError("sem cor marcante no logo");
    Object.assign(state.draft.colors, suggested);
    renderEditor();
    changed();
  } catch (err) {
    setError(String(err.message || err));
  }
}

async function exportSelected() {
  try {
    const { path } = await api.exportStyle(state.selected);
    el("sty-detail-desc").textContent = `exportado: ${path}`;
  } catch (err) {
    setError(String(err.message || err));
  }
}

async function importFile(file) {
  if (!file) return;
  try {
    const saved = await api.importStyle(JSON.parse(await file.text()));
    await reload(false);
    select(saved.id);
    loadGalleryThumbs();
  } catch (err) {
    setError(err instanceof SyntaxError ? "arquivo não é um estilo do Auto-Edit" : String(err.message || err));
  }
}

// ── Load ─────────────────────────────────────────────────────────────────────

async function reload(full = true) {
  try {
    const [data, settings] = await Promise.all([api.styles(), api.settings()]);
    setEngine(true);
    state.data = data;
    state.settings = settings;
  } catch (err) {
    setEngine(false);
    setError(`não deu pra carregar os estilos: ${err.message || err}`);
    return;
  }
  if (!styleOf(state.selected)) state.selected = state.data.active;
  renderBrand();
  renderGallery();
  if (full) {
    renderDetail();
    refreshPreviews();
    loadGalleryThumbs();
  }
}

let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  el("sty-gallery").addEventListener("click", (e) => {
    if (e.target.closest("[data-ai]")) { el("sty-ai").hidden = false; el("sty-ai-desc").focus(); return; }
    const card = e.target.closest("[data-style]");
    if (card) select(card.dataset.style);
  });
  el("sty-name").addEventListener("input", () => debounce("brand", saveBrand, 700));
  el("sty-handle").addEventListener("input", () => debounce("brand", saveBrand, 700));
  el("sty-logo-bg-own").addEventListener("change", () => { el("sty-logo-bg").disabled = !el("sty-logo-bg-own").checked; saveBrand(); });
  el("sty-logo-bg").addEventListener("input", () => {
    el("sty-logo").style.background = el("sty-logo-bg").value;
    debounce("brand", saveBrand, 500);
  });
  el("sty-overlays").addEventListener("input", () => debounce("overlays", async () => {
    try {
      state.settings = await api.saveSettings({ overlays_dir: el("sty-overlays").value.trim() || null });
      setError("");
    } catch (err) { setError(String(err.message || err)); }
  }, 900));
  const pick = (e) => { e.preventDefault(); el("sty-logo-file").click(); };
  el("sty-logo").addEventListener("click", pick);
  el("sty-logo-pick").addEventListener("click", pick);
  el("sty-logo-file").addEventListener("change", (e) => { pickLogo(e.target.files[0]); e.target.value = ""; });
  el("sty-logo-remove").addEventListener("click", async (e) => {
    e.preventDefault();
    try { await api.deleteLogo(); await reload(false); refreshPreviews(true); } catch (err) { setError(String(err.message || err)); }
  });

  el("btn-sty-use").addEventListener("click", async () => {
    try { await api.setActiveStyle(state.selected); await reload(false); renderDetail(); } catch (err) { setError(String(err.message || err)); }
  });
  el("btn-sty-edit").addEventListener("click", startEditing);
  el("btn-sty-ai-go").addEventListener("click", generateAi);
  el("btn-sty-ai-close").addEventListener("click", () => (el("sty-ai").hidden = true));
  el("sty-ai-pick").addEventListener("click", (e) => { e.preventDefault(); el("sty-ai-file").click(); });
  el("sty-ai-file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    takeAiImage(f, f?.name);
  });
  // A screenshot is easier pasted (⌘V / Ctrl+V) or dropped than saved and attached.
  document.addEventListener("paste", (e) => {
    if (el("sty-ai").hidden) return;
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (!item) return; // plain text still pastes into the description
    e.preventDefault();
    takeAiImage(item.getAsFile(), "imagem colada");
  });
  el("sty-ai").addEventListener("dragover", (e) => { e.preventDefault(); el("sty-ai").classList.add("drop"); });
  el("sty-ai").addEventListener("dragleave", () => el("sty-ai").classList.remove("drop"));
  el("sty-ai").addEventListener("drop", (e) => {
    e.preventDefault();
    el("sty-ai").classList.remove("drop");
    const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/"));
    takeAiImage(f, f?.name);
  });
  el("sty-ai-img-remove").addEventListener("click", (e) => { e.preventDefault(); setAiImage(null); });
  el("sty-logo-colors").addEventListener("click", (e) => { e.preventDefault(); useLogoColors(); });
  el("btn-sty-export").addEventListener("click", exportSelected);
  el("sty-import").addEventListener("click", (e) => { e.preventDefault(); el("sty-import-file").click(); });
  el("sty-import-file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; importFile(f); });
  el("btn-sty-cancel").addEventListener("click", () => {
    if (!confirmDiscard()) return;
    state.draft = null;
    state.fresh = false;
    renderDetail();
    refreshPreviews();
  });
  el("btn-sty-save").addEventListener("click", () => saveDraft(false));
  el("btn-sty-save-new").addEventListener("click", () => saveDraft(true));
  el("btn-sty-delete").addEventListener("click", async () => {
    const b = el("btn-sty-delete");
    if (!b.dataset.armed) {
      b.dataset.armed = "1";
      b.textContent = "Confirmar exclusão";
      return setTimeout(() => { delete b.dataset.armed; b.textContent = "Excluir"; }, 2500);
    }
    try {
      await api.deleteStyle(state.selected);
      delete state.thumbs[state.selected];
      state.selected = null;
      await reload();
    } catch (err) { setError(String(err.message || err)); }
  });

  // Overlays are small on a 16:9 frame (as on the video): click to see it big.
  document.querySelector(".sty-previews").addEventListener("click", (e) => {
    const img = e.target.closest(".sty-shot")?.querySelector("img");
    if (!img?.src) return;
    const zoom = document.createElement("div");
    zoom.className = "sty-zoom";
    zoom.innerHTML = `<img src="${img.src}" alt="" />`;
    zoom.addEventListener("click", () => zoom.remove());
    document.body.append(zoom);
  });

  const editor = el("sty-editor");
  editor.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.tok) {
      setTok(state.draft, t.dataset.tok, t.type === "checkbox" ? t.checked : "num" in t.dataset ? Number(t.value) : t.value);
      return changed();
    }
    const row = t.closest("[data-step]");
    if (!row) return;
    const step = state.draft.cta.steps[Number(row.dataset.step)];
    const key = t.dataset.stepKey;
    if (key === "own") {
      step.color = t.checked ? row.querySelector("[data-step-key=color]").value : null;
      row.querySelector("[data-step-key=color]").disabled = !t.checked;
    } else if (key === "color") step.color = t.value;
    else step[key] = t.value;
    changed();
  });
  editor.addEventListener("click", (e) => {
    const rm = e.target.closest("[data-step-remove]");
    if (rm) {
      state.draft.cta.steps.splice(Number(rm.closest("[data-step]").dataset.step), 1);
      renderSteps();
      changed();
    }
  });
  el("btn-sty-adjust").addEventListener("click", adjustAi);
  el("sty-adjust-req").addEventListener("keydown", (e) => { if (e.key === "Enter") adjustAi(); });
  el("sty-html").addEventListener("input", () => {
    const html = el("sty-html").value;
    if (html.trim()) state.draft.thumbnail.html = html;
    else delete state.draft.thumbnail.html;
    el("sty-html-reset").hidden = !html.trim();
    debounce("preview", () => refreshPreviews(), 600);
  });
  el("sty-html-reset").addEventListener("click", (e) => {
    e.preventDefault();
    delete state.draft.thumbnail.html;
    el("sty-html").value = "";
    el("sty-html-reset").hidden = true;
    refreshPreviews();
  });
  el("sty-step-add").addEventListener("click", (e) => {
    e.preventDefault();
    state.draft.cta.steps.push({ icon: "comment", text: "COMENTA AQUI!", color: null });
    renderSteps();
    changed();
  });
}

export default {
  id: "styles",
  mount() {
    wire();
    setError("");
    reload();
  },
  unmount() {
    clearTimeout(state.timers.preview); // a pending brand/folder save still goes through
  },
};
