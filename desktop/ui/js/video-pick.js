// Getting a video's path from the person: the app's open dialog and files
// dropped on the window. Shared by Novo edit and the empty Edições.
//
// Both come from Tauri with real paths. A browser never exposes where a file
// is, so the browser preview can only say so.

import * as api from "./api.js";

const T = window.__TAURI__;

export const VIDEO_EXTS = ["mp4", "mov", "mkv", "avi", "webm", "m4v", "mts", "m2ts"];
export const isVideo = (path) => VIDEO_EXTS.includes(path.split(".").pop().toLowerCase());
export const NOT_VIDEO = "Isso não é um vídeo que o pipeline abre (mp4, mov, mkv, webm…).";
const BROWSER = "O navegador não informa onde o arquivo está: escolha o vídeo no app instalado.";

/** The OS open dialog, filtered to videos and opening in the inbox
 * (Configurações → Pastas). The path, or null when cancelled. */
export async function chooseVideo() {
  if (!T?.dialog) throw new Error(BROWSER);
  let inbox;
  try { inbox = (await api.folders()).inbox.path; } catch { /* engine offline: the OS decides */ }
  return T.dialog.open({
    title: "Escolher vídeo",
    multiple: false,
    directory: false,
    defaultPath: inbox,
    filters: [{ name: "Vídeos", extensions: VIDEO_EXTS }],
  });
}

let guarded = false;

/**
 * Files dropped on `screen` while `active()` holds: `over(bool)` while one is
 * dragged over, then `path(p)` with the first video, or `fail(message)`.
 */
export function onVideoDrop(screen, { active, over, path, fail }) {
  // Tauri takes file drops at the window level (HTML drop events never see
  // the files): each listener only reacts while its own screen is showing.
  const webview = T?.webview?.getCurrentWebview?.();
  if (webview) {
    webview.onDragDropEvent(({ payload }) => {
      if (!active()) return;
      if (payload.type === "enter" || payload.type === "over") over(true);
      else if (payload.type === "leave") over(false);
      else if (payload.type === "drop") {
        over(false);
        const found = payload.paths.find(isVideo);
        if (found) path(found);
        else fail(NOT_VIDEO);
      }
    });
    return;
  }
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  if (!guarded) {
    guarded = true;
    // Without this, a file dropped a bit off target opens in the tab and the form is gone.
    window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener("drop", (e) => { if (hasFiles(e)) e.preventDefault(); });
  }
  screen.addEventListener("dragenter", (e) => { if (hasFiles(e) && active()) over(true); });
  screen.addEventListener("dragleave", (e) => { if (!screen.contains(e.relatedTarget)) over(false); });
  screen.addEventListener("drop", (e) => {
    if (!hasFiles(e) || !active()) return;
    over(false);
    fail(BROWSER);
  });
}
