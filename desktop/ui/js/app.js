// Auto-Edit desktop — thin client over the headless API.
// Works both inside Tauri and opened directly in a browser (against `auto-edit serve`).

import { route, start } from "./router.js";
import library, { refresh } from "./library.js";
import newEdit from "./new-edit.js";

route("/", library);
route("/novo", newEdit);

document.querySelectorAll("[data-retry]").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); refresh(); })
);

start();
