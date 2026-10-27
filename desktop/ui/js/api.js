// Thin wrapper over the headless API (`auto-edit serve`). No pipeline logic here.

export const API = (window.AUTO_EDIT_API || "http://127.0.0.1:8760").replace(/\/$/, "");

async function json(path, opts) {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `${path} → ${r.status}`);
  return body;
}

export async function health() {
  try {
    return (await fetch(`${API}/api/health`, { cache: "no-store" })).ok;
  } catch {
    return false;
  }
}

export const library = () => json("/api/library").then((b) => b.videos || []);

export const video = (id) => json(`/api/videos/${encodeURIComponent(id)}`);

export const result = (id) => json(`/api/videos/${encodeURIComponent(id)}/result`);

export const plan = (id) => json(`/api/videos/${encodeURIComponent(id)}/plan`);

export const savePlan = (id, kept_segments) =>
  json(`/api/videos/${encodeURIComponent(id)}/plan`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kept_segments }),
  });

/** `captionOnly`: só regravar a legenda do short (metadata/thumbnail ficam). */
export const resume = (id, from_stage, { captionOnly = false } = {}) =>
  json(`/api/videos/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(captionOnly ? { from_stage, caption_only: true } : { from_stage }),
  });

/** Nome/tamanho de um caminho vindo do diálogo ou de um arquivo arrastado (404 se não for vídeo). */
export const videoFile = (path) => json(`/api/video-file?path=${encodeURIComponent(path)}`);

export const startEdit = (payload) =>
  json("/api/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const shorts = (id, maxDur) =>
  json(`/api/videos/${encodeURIComponent(id)}/shorts${maxDur ? `?max_dur=${maxDur}` : ""}`);

export const findShorts = (id, max_dur) =>
  json(`/api/videos/${encodeURIComponent(id)}/shorts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_dur }),
  });

export const cutShorts = (id, pick, max_dur) =>
  json(`/api/videos/${encodeURIComponent(id)}/shorts/cut`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pick, max_dur }),
  });

export const openFile = (id, kind, reveal = false) =>
  json(`/api/videos/${encodeURIComponent(id)}/open/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reveal }),
  });

export const youtubeAccount = () => json("/api/publish/youtube");

export const connectYoutube = () => json("/api/publish/youtube/connect", { method: "POST" });

export const publishState = (id) => json(`/api/videos/${encodeURIComponent(id)}/publish`);

export const publishYoutube = (id, payload) =>
  json(`/api/videos/${encodeURIComponent(id)}/publish/youtube`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const retention = (id) => json(`/api/videos/${encodeURIComponent(id)}/retention`);

export const refreshRetention = (id) =>
  json(`/api/videos/${encodeURIComponent(id)}/retention`, { method: "POST" });

export const openUrl = (url) =>
  json("/api/open-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

export const stop = (id) => json(`/api/videos/${encodeURIComponent(id)}/stop`, { method: "POST" });

/** Para o que estiver rodando e apaga o workspace e os arquivos finais (nunca o vídeo original). */
export const deleteVideo = (id) => json(`/api/videos/${encodeURIComponent(id)}`, { method: "DELETE" });

export const settings = () => json("/api/settings");

/** Biblioteca: os vídeos da pasta de entrada (com subpastas) e as edições de cada um. */
export const recordings = () => json("/api/recordings");

/** Miniatura de um vídeo da pasta de entrada (o motor só serve as de lá). */
export const recordingThumbUrl = (path) => `${API}/api/recordings/thumb?path=${encodeURIComponent(path)}`;

/** Pasta de entrada e de saída como o pipeline usa agora: {inbox, output}: {path, custom}. */
export const folders = () => json("/api/folders");

/** Abre uma das duas pastas ("inbox" | "output") no gerenciador de arquivos. */
export const openFolder = (which) => json(`/api/folders/${which}/open`, { method: "POST" });

export const saveSettings = (data) =>
  json("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const agents = () => json("/api/agents").then((b) => b.agents || []);

export const testAgent = (name, model) =>
  json(`/api/agents/${name}/test`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });

export const loginAgent = (name) => json(`/api/agents/${name}/login`, { method: "POST" });

// OpenRouter has no CLI: "installing" it is pasting an API key. The engine
// keeps it; only a masked hint ever comes back.
export const saveOpenrouterKey = (key) =>
  json("/api/agents/openrouter/key", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });

export const deleteOpenrouterKey = () => json("/api/agents/openrouter/key", { method: "DELETE" });

export const pullOllama = (model) =>
  json("/api/agents/ollama/pull", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });

export const disconnectYoutube = () => json("/api/publish/youtube/disconnect", { method: "POST" });

export const setupState = () => json("/api/setup");

export const installAgent = (name) => json(`/api/agents/${name}/install`, { method: "POST" });

export const downloadWhisper = (model) =>
  json("/api/setup/whisper", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });

export const videoEvents = (id) =>
  new EventSource(`${API}/api/videos/${encodeURIComponent(id)}/events`);

// ── Estilos ─────────────────────────────────────────────────────────────────
const sendJson = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const styles = () => json("/api/styles");
export const setActiveStyle = (id) => json("/api/styles/active", sendJson("PUT", { id }));
export const saveStyle = (style) => json("/api/styles", sendJson("POST", style));
export const deleteStyle = (id) => json(`/api/styles/${encodeURIComponent(id)}`, { method: "DELETE" });
export const uploadLogo = (data) => json("/api/brand/logo", sendJson("PUT", { data }));
export const deleteLogo = () => json("/api/brand/logo", { method: "DELETE" });
export const logoUrl = () => `${API}/api/brand/logo?t=${Date.now()}`;
/** The AI creating (or adjusting) a style runs as a job: progress over SSE,
 * resolves with the draft {name, description, tokens}. */
async function styleAiJob(path, body, onProgress) {
  const { job_id } = await json(path, sendJson("POST", body));
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API}/api/jobs/${encodeURIComponent(job_id)}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "progress") onProgress?.(ev.message);
      else if (ev.type === "done") { es.close(); ev.result ? resolve(ev.result) : reject(new Error("a IA não terminou")); }
      else if (ev.type === "error") { es.close(); reject(new Error(ev.message || "a IA falhou")); }
    };
    es.onerror = () => { es.close(); reject(new Error("perdi a conexão com o motor")); };
  });
}
export const generateStyle = (description, image, onProgress) => styleAiJob("/api/styles/generate", { description, image }, onProgress);
export const adjustStyle = (tokens, request, onProgress) => styleAiJob("/api/styles/adjust", { tokens, request }, onProgress);
export const stylePalette = (image) => json("/api/styles/palette", sendJson("POST", image ? { image } : {}));
export const exportStyle = (id) => json(`/api/styles/${encodeURIComponent(id)}/export`, { method: "POST" });
export const importStyle = (file) => json("/api/styles/import", sendJson("POST", { file }));

/** A blob: URL with the PNG of one part of a style. */
export async function stylePreview(tokens, kind) {
  const r = await fetch(`${API}/api/styles/preview/${kind}`, { ...sendJson("POST", { tokens }), cache: "no-store" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `prévia → ${r.status}`);
  return URL.createObjectURL(await r.blob());
}

// ── Legenda por vídeo (short) ───────────────────────────────────────────────
export const videoCaptions = (id) => json(`/api/videos/${encodeURIComponent(id)}/captions`);
export const saveVideoCaptions = (id, adjust) =>
  json(`/api/videos/${encodeURIComponent(id)}/captions`, sendJson("PUT", adjust));

/** A blob: URL with the PNG of the vertical preview, with `adjust` over the saved one. */
export async function videoCaptionPreview(id, adjust) {
  const r = await fetch(`${API}/api/videos/${encodeURIComponent(id)}/captions/preview`, {
    ...sendJson("POST", adjust),
    cache: "no-store",
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `prévia → ${r.status}`);
  return URL.createObjectURL(await r.blob());
}
