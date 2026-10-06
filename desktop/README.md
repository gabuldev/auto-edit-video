# Auto-Edit Desktop (protótipo Tauri)

Cliente **fino** (Tauri v2) da UI do auto-edit, consumindo a API headless do
`auto-edit serve`. Toda a lógica de pipeline fica no Python — este app só mostra
e dispara.

**Telas:** Biblioteca (lista + progresso ao vivo por SSE), Novo edit (escolhe o
vídeo na pasta de entrada, com busca, e inicia o pipeline), Pipeline ao vivo
(stages, log do `ralph.sh` em tempo real e retomar a partir de um stage),
Revisar cortes (os trechos mantidos com o que é dito em cada um; desmarcar e
salvar reescreve o `reviewed_plan.json`), Resultado (o vídeo pronto tocando, a
thumbnail, o texto de publicação pronto pra copiar e **Publicar no YouTube**:
conecta o canal, edita título/descrição/tags, escolhe a visibilidade ou agenda,
e envia com barra de progresso) e Shorts (a partir de um
long pronto: o `clipper` propõe trechos, você assiste cada um no player, marca e
corta — cada marcado vira um `<nome>_shortN` que roda em fila).

## 1. O motor

O app nativo (Tauri) **sobe o motor sozinho** ao abrir e o encerra ao fechar.
Se já houver um `auto-edit serve` ouvindo na 8760, ele é reaproveitado (e não é
encerrado). O log do motor vai pra pasta de logs do app (`engine.log`; no macOS,
`~/Library/Logs/dev.gabul.autoedit/`).

Ele procura o executável `auto-edit` em: `AUTO_EDIT_BIN`, `.venv` do repo,
`~/.local/bin`, `~/.nix-profile/bin`, Homebrew e, por fim, no PATH do seu shell
de login. Em dev o motor roda na raiz do repo (mesmos workspaces do CLI); num
app empacotado, em `~/.auto-edit` (troque com `AUTO_EDIT_CWD`).

Só precisa do extra da API instalado:

```bash
pip install "auto-edit-video[api]"   # ou: uv pip install -e ".[api]"
```

No preview pelo navegador (2a), o motor não sobe sozinho: rode `auto-edit serve`.

## 2a. Preview instantâneo (sem Rust) — pra "ver como fica" já

O frontend é HTML/CSS/JS puro; abre direto no navegador:

```bash
cd desktop/ui
python3 -m http.server 5173
# abre http://localhost:5173
```

> A UI usa módulos ES, então precisa ser servida por http (abrir o
> `index.html` por `file://` não funciona).

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
  `window.AUTO_EDIT_API` antes do `js/app.js` (ex.: um `<script>` no `index.html`).
- O file picker do "Novo edit" começa na pasta de entrada (`AUTO_EDIT_INBOX`, ou
  `upload/` do repo) e navega a partir dela.
- A CSP em `src-tauri/tauri.conf.json` já libera `connect-src` pra `127.0.0.1:8760`.

## Estrutura

```
desktop/
├── ui/                 # frontend (roda no navegador OU dentro do Tauri)
│   ├── index.html      # todas as telas; o router mostra uma por vez
│   ├── styles.css      # tema dark/teal Gabuldev
│   └── js/
│       ├── app.js      # registra as rotas e sobe o router
│       ├── router.js   # rotas por hash (#/ , #/novo , #/video/:id[/cortes|/resultado])
│       ├── api.js      # única camada que fala com a API
│       ├── shell.js    # helpers + indicador do motor
│       ├── library.js  # tela Biblioteca (SSE por linha)
│       ├── new-edit.js # tela Novo edit (file picker + form)
│       ├── pipeline.js # tela Pipeline ao vivo (stages + log SSE + resume)
│       ├── cuts.js     # tela Revisar cortes (edita o plano e recorta)
│       ├── result.js   # tela Resultado (player, thumbnail e metadata)
├── src-tauri/          # shell Tauri v2 (Rust)
│   ├── Cargo.toml  build.rs  tauri.conf.json
│   ├── src/main.rs
│   └── capabilities/default.json
├── app-icon.png        # fonte do ícone (expandida por `tauri icon`)
└── package.json
```

## Próximos passos

- Publicar direto pelo app (o `auto-edit insights auth youtube` já existe no CLI).
- Empacotar o `auto-edit serve` como *sidecar* do Tauri (hoje o app sobe o CLI
  instalado na máquina).
