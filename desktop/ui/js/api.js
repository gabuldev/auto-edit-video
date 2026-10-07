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

export const resume = (id, from_stage) =>
  json(`/api/videos/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_stage }),
  });

export const browse = (dir) =>
  json(`/api/browse${dir ? `?dir=${encodeURIComponent(dir)}` : ""}`);

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

export const videoEvents = (id) =>
  new EventSource(`${API}/api/videos/${encodeURIComponent(id)}/events`);
