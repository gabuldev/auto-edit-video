// Ajustar legenda — o card da tela Resultado de um short pronto. Prévia vertical
// (PNG do motor) com uma faixa tracejada que se arrasta na vertical; tamanho e
// esconder. Nada é salvo até "Regravar legenda": soltar a faixa só atualiza o
// ajuste local e pede uma prévia nova (debounce). Regravar faz PUT e depois
// resume(id, "caption"), e segue pra tela do pipeline.

import * as api from "./api.js";
import { el } from "./shell.js";
import { go } from "./router.js";

const state = { grab: 0, id: null, adjust: {}, fast: true, seq: 0, timer: null, url: null, wired: false, drag: null };

const OLD_WARN = "Esse vídeo é de antes desta versão: vai recortar de novo (alguns minutos)";

function setError(msg) {
  el("cap-error").hidden = !msg;
  el("cap-error").textContent = msg || "";
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Band height as a fraction of the stage: ~one caption line, follows the size. */
const bandH = (a) => 0.07 * clamp(Number(a.size ?? 100), 50, 200) / 100;

/** Top edge of the band (0–1). libass anchors the text by its edge: bottom →
 * the bottom edge sits at (1 − offset); top → the top edge at offset. */
function topY(a) {
  const off = clamp(Number(a.offset ?? 33), 0, 40) / 100;
  const h = bandH(a);
  if (a.position === "top") return off;
  if (a.position === "middle") return 0.5 - h / 2;
  return 1 - off - h;
}

function placeBand(top = topY(state.adjust)) {
  const a = state.adjust;
  el("cap-band").hidden = Boolean(a.hidden);
  el("cap-band").style.top = `${top * 100}%`;
  el("cap-band").style.height = `${bandH(a) * 100}%`;
}

/** position/offset from the band's top edge, using the same anchoring. */
function fromTop(top) {
  const h = bandH(state.adjust);
  const c = clamp(top, 0, 1 - h) + h / 2;
  if (c < 0.4) return { position: "top", offset: clamp(Math.round((c - h / 2) * 100), 0, 40) };
  if (c > 0.6) return { position: "bottom", offset: clamp(Math.round((1 - c - h / 2) * 100), 0, 40) };
  return { position: "middle", offset: state.adjust.offset ?? 33 };
}

function syncControls() {
  const a = state.adjust;
  el("cap-size").value = a.size;
  el("cap-size-val").textContent = `${a.size}%`;
  el("cap-hidden").checked = Boolean(a.hidden);
  el("cap-band").classList.toggle("off", Boolean(a.hidden));
  placeBand();
}

function requestPreview(now = false) {
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    const seq = ++state.seq;
    el("cap-stage").classList.add("loading");
    try {
      const url = await api.videoCaptionPreview(state.id, state.adjust);
      if (seq !== state.seq) return URL.revokeObjectURL(url);
      const old = state.url;
      state.url = url;
      el("cap-img").src = url;
      if (old) URL.revokeObjectURL(old);
      setError("");
    } catch (err) {
      if (seq === state.seq) setError(String(err.message || err));
    } finally {
      if (seq === state.seq) el("cap-stage").classList.remove("loading");
    }
  }, now ? 0 : 350);
}

async function load() {
  const id = state.id;
  try {
    const d = await api.videoCaptions(id);
    if (id !== state.id) return;
    const c = d.captions || {};
    state.fast = d.fast !== false;
    state.adjust = {
      position: d.adjust?.position ?? c.position ?? "bottom",
      offset: d.adjust?.offset ?? c.offset ?? 33,
      size: d.adjust?.size ?? c.size ?? 100,
      hidden: Boolean(d.adjust?.hidden ?? c.hidden),
    };
    el("btn-cap-redo").textContent = state.fast ? "Regravar legenda" : "Regravar legenda (vai recortar, alguns minutos)";
    el("btn-cap-redo").title = state.fast ? "" : OLD_WARN;
    el("cap-card").hidden = false;
    syncControls();
    requestPreview(true);
  } catch (err) {
    if (id !== state.id) return;
    // Sem rota/sem legenda: o card simplesmente não aparece.
    el("cap-card").hidden = true;
  }
}

async function regravar() {
  const btn = el("btn-cap-redo");
  btn.disabled = true;
  setError("");
  try {
    await api.saveVideoCaptions(state.id, state.adjust);
    await api.resume(state.id, "caption");
    go(`/video/${encodeURIComponent(state.id)}`);
  } catch (err) {
    setError(String(err.message || err));
  } finally {
    btn.disabled = false;
  }
}

function wire() {
  const band = el("cap-band");
  const stageRect = () => el("cap-stage").getBoundingClientRect();
  const topAt = (e) => {
    const r = stageRect();
    return clamp((e.clientY - r.top) / r.height - state.grab, 0, 1 - bandH(state.adjust));
  };
  band.addEventListener("pointerdown", (e) => {
    band.setPointerCapture(e.pointerId);
    state.drag = e.pointerId;
    // Onde na faixa o dedo/mouse pegou: a faixa não pula pro cursor.
    const r = stageRect();
    state.grab = (e.clientY - r.top) / r.height - topY(state.adjust);
    e.preventDefault();
  });
  band.addEventListener("pointermove", (e) => {
    if (state.drag === e.pointerId) placeBand(topAt(e));
  });
  band.addEventListener("pointerup", (e) => {
    if (state.drag !== e.pointerId) return;
    state.drag = null;
    Object.assign(state.adjust, fromTop(topAt(e)));
    placeBand();
    requestPreview();
  });
  band.addEventListener("pointercancel", () => { state.drag = null; placeBand(); });
  el("cap-size").addEventListener("input", () => {
    state.adjust.size = Number(el("cap-size").value);
    placeBand();
    el("cap-size-val").textContent = `${state.adjust.size}%`;
    requestPreview();
  });
  el("cap-hidden").addEventListener("change", () => {
    state.adjust.hidden = el("cap-hidden").checked;
    syncControls();
    requestPreview();
  });
  el("btn-cap-redo").addEventListener("click", regravar);
}

export function mountCaptionAdjust(id) {
  if (!state.wired) { wire(); state.wired = true; }
  state.id = id;
  el("cap-card").hidden = true;
  setError("");
  load();
}

export function unmountCaptionAdjust() {
  clearTimeout(state.timer);
  state.seq++;
  if (state.url) URL.revokeObjectURL(state.url);
  state.url = null;
  el("cap-img").removeAttribute("src");
}
