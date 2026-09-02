// Auto-Edit desktop — Tauri v2 shell.
// The heavy lifting lives in the Python engine (`auto-edit serve`); this window
// just loads the web UI in ../ui, which talks to the local API over HTTP + SSE.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Auto-Edit");
}
