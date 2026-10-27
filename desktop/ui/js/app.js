// Auto-Edit desktop — thin client over the headless API.
// Works both inside Tauri and opened directly in a browser (against `auto-edit serve`).

import * as api from "./api.js";
import { el, setEngine } from "./shell.js";
import { route, start } from "./router.js";
import library, { refresh } from "./library.js";
import newEdit from "./new-edit.js";
import pipeline from "./pipeline.js";
import cuts from "./cuts.js";
import result from "./result.js";
import shorts from "./shorts.js";
import config from "./settings.js";
import stylesScreen from "./styles.js";
import welcome, { checkSetup } from "./welcome.js";
import { startUpdateCheck } from "./update.js";

route("/", library);
route("/novo", newEdit);
route("/video/:id", pipeline);
route("/video/:id/cortes", cuts);
route("/video/:id/resultado", result);
route("/video/:id/shorts", shorts);
route("/estilos", stylesScreen);
route("/config", config);
route("/bemvindo", welcome);

document.querySelectorAll("[data-retry]").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); refresh(); })
);

// The app starts the engine with the window and it takes a few seconds to
// answer. Until it does, the boot screen covers everything: no screen mounts
// half-offline. It never gives up, it only says more the longer it takes.
async function boot() {
  const since = Date.now();
  while (!(await api.health())) {
    const waited = Date.now() - since;
    el("boot-slow").hidden = waited < 15000;
    el("boot-stuck").hidden = waited < 60000;
    await new Promise((r) => setTimeout(r, 700));
  }
  setEngine(true);
  el("boot").hidden = true;
  start();
  checkSetup(); // a machine that can't edit yet goes to the first-run setup
  startUpdateCheck(); // no app instalado: avisa de versão nova (nunca atualiza sem clique)
}

boot();
