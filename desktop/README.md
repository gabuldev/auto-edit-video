# Auto-Edit Desktop (protótipo Tauri)

Cliente **fino** (Tauri v2) da tela **Biblioteca**, consumindo a API headless
do `auto-edit serve` (`/api/library` + SSE de progresso). Toda a lógica de
pipeline fica no Python — este app só mostra e dispara.

> Feito/empurrado de um ambiente na nuvem: **compile e rode na sua máquina**
> (Mac ou Windows). Depende da API do PR #53 (`auto-edit serve`).

## 1. Suba o motor (em um terminal)

```bash
pip install "auto-edit-video[api]"   # ou: pip install flask
auto-edit serve                       # http://127.0.0.1:8760
```

## 2a. Preview instantâneo (sem Rust) — pra "ver como fica" já

O frontend é HTML/CSS/JS puro; abre direto no navegador:

```bash
cd desktop/ui
python3 -m http.server 5173
# abre http://localhost:5173
```

Com o motor no ar, mostra a biblioteca real e o progresso ao vivo. Sem o motor,
mostra um banner "offline" + linhas de exemplo (dá pra ver o design mesmo assim).

## 2b. App nativo (Tauri)

**Pré-requisitos:**
- [Rust](https://rustup.rs) (rustup) + Node 18+
- **macOS:** Xcode Command Line Tools (`xcode-select --install`)
- **Windows:** Microsoft C++ Build Tools + WebView2 (já vem no Win11)
- **Linux:** `webkit2gtk`, `libayatana-appindicator`, `librsvg` (ver docs do Tauri)

```bash
cd desktop
npm install
npm run tauri icon app-icon.png   # gera src-tauri/icons/ (uma vez)
npm run tauri dev                 # abre a janela do app
```

## Configuração

- A URL da API é `http://127.0.0.1:8760` por padrão. Pra trocar, defina
  `window.AUTO_EDIT_API` antes do `app.js` (ex.: um `<script>` no `index.html`).
- A CSP em `src-tauri/tauri.conf.json` já libera `connect-src` pra `127.0.0.1:8760`.

## Estrutura

```
desktop/
├── ui/                 # frontend (roda no navegador OU dentro do Tauri)
│   ├── index.html
│   ├── styles.css      # tema dark/teal Gabuldev
│   └── app.js          # fetch /api/library + EventSource (SSE)
├── src-tauri/          # shell Tauri v2 (Rust)
│   ├── Cargo.toml  build.rs  tauri.conf.json
│   ├── src/main.rs
│   └── capabilities/default.json
├── app-icon.png        # fonte do ícone (expandida por `tauri icon`)
└── package.json
```

## Próximos passos

- Telas: Novo edit → Pipeline ao vivo → Revisar cortes → Resultado (mockups já
  desenhados no canvas de design).
- Empacotar o `auto-edit serve` como *sidecar* do Tauri (hoje roda à parte).
