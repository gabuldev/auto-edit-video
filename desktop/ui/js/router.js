// Hash router. Each screen registers { mount, unmount } and owns its own polling
// so a background screen never fights the one you're looking at.

const routes = new Map();
let current = null;

export function route(path, screen) {
  routes.set(path, screen);
}

export function go(path) {
  if (location.hash === `#${path}`) resolve();
  else location.hash = `#${path}`;
}

export function resolve() {
  const path = location.hash.replace(/^#/, "") || "/";
  const screen = routes.get(path) || routes.get("/");
  if (current && current !== screen) current.unmount?.();
  current = screen;

  document.querySelectorAll("[data-screen]").forEach((s) => {
    s.hidden = s.dataset.screen !== screen.id;
  });
  document.querySelectorAll(".nav-item").forEach((n) => {
    n.classList.toggle("active", n.dataset.route === path);
  });

  screen.mount?.();
}

export function start() {
  window.addEventListener("hashchange", resolve);
  resolve();
}
