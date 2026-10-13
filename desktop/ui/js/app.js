// Auto-Edit desktop — thin client over the headless API.
// Works both inside Tauri and opened directly in a browser (against `auto-edit serve`).

import { route, start } from "./router.js";
import library, { refresh } from "./library.js";
import newEdit from "./new-edit.js";
import pipeline from "./pipeline.js";
import cuts from "./cuts.js";
import result from "./result.js";
import shorts from "./shorts.js";
import config from "./settings.js";
import welcome, { checkSetup } from "./welcome.js";

route("/", library);
route("/novo", newEdit);
route("/video/:id", pipeline);
route("/video/:id/cortes", cuts);
route("/video/:id/resultado", result);
route("/video/:id/shorts", shorts);
route("/config", config);
route("/bemvindo", welcome);

document.querySelectorAll("[data-retry]").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); refresh(); })
);

start();
checkSetup(); // a machine that can't edit yet goes to the first-run setup
