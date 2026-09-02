// Bits every screen shares: DOM helpers and the engine-status indicator.

export const el = (id) => document.getElementById(id);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export function humanSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes, i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

export function setEngine(ok) {
  el("engine-status").className = "engine-status " + (ok ? "ok" : "off");
  el("engine-label").textContent = ok ? "engine ok" : "offline";
  document.querySelectorAll("[data-offline-banner]").forEach((b) => { b.hidden = ok; });
}
