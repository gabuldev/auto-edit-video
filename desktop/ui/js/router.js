// Hash router with params ("/video/:id"). Each screen registers
// { mount, unmount } and owns its own polling, so a background screen never
// fights the one you're looking at.

const routes = [];
let current = null;

export function route(pattern, screen) {
  routes.push({ parts: pattern.split("/").filter(Boolean), screen });
}

export function go(path) {
  if (location.hash === `#${path}`) resolve();
  else location.hash = `#${path}`;
}

function match(path) {
  const parts = path.split("/").filter(Boolean);
  for (const r of routes) {
    if (r.parts.length !== parts.length) continue;
    const params = {};
    const ok = r.parts.every((p, i) => {
      if (p.startsWith(":")) { params[p.slice(1)] = decodeURIComponent(parts[i]); return true; }
      return p === parts[i];
    });
    if (ok) return { screen: r.screen, params };
  }
  return { screen: routes[0].screen, params: {} };
}

export function resolve() {
  const path = location.hash.replace(/^#/, "") || "/";
  const { screen, params } = match(path);
  // Always unmount, even when the next route is the same screen (another
  // video on Pipeline, or go() to the current path): mount() starts timers and
  // live streams, and mounting twice without unmounting stacked them up until
  // the page pegged the CPU.
  if (current) current.unmount?.();
  current = screen;

  document.querySelectorAll("[data-screen]").forEach((s) => {
    s.hidden = s.dataset.screen !== screen.id;
  });
  document.querySelectorAll(".nav-item").forEach((n) => {
    n.classList.toggle("active", n.dataset.route === path);
  });

  screen.mount?.(params);
}

export function start() {
  window.addEventListener("hashchange", resolve);
  resolve();
}
