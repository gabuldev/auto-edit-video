# Auto-Edit (Flutter)

O app novo, em Flutter (macOS, Windows e Linux; celular depois), que vai
substituir o `desktop/` (Tauri). Épico #134. Fala com o motor só pela API
(`packages/auto_edit_client`, gerado do `auto_edit/openapi.yaml`).

Como o Tauri, ao abrir ele **reaproveita** um motor que já esteja na porta
8760 (um `auto-edit serve` rodado à mão) ou **sobe o seu**, e mata só o que ele
mesmo subiu ao fechar. A busca do motor segue a mesma ordem
(`lib/engine/locator.dart`): o motor embutido no pacote do app (#144), depois
`AUTO_EDIT_BIN`, o `.venv` do checkout, `~/.local/bin`, `~/.nix-profile/bin`,
Homebrew, `/usr/local/bin` e por fim o PATH do shell de login.
O log fica em `<pasta de suporte do app>/logs/engine.log`; "Reiniciar o motor"
move o anterior pra `engine.prev.log`.

```bash
cd app
flutter run -d linux     # ou macos / windows; em debug o motor roda na raiz do checkout
flutter test             # AUTO_EDIT_BIN=../.venv/bin/auto-edit inclui o teste com o motor real
```

Linux precisa de `clang cmake ninja-build pkg-config libgtk-3-dev`.

Telas:

- **Boas-vindas** (`lib/ui/welcome.dart`): abre sozinha numa máquina que ainda
  não edita (agente testado + Whisper baixado), como no Tauri. "configurar
  depois" fica lembrado em `<pasta de suporte>/prefs.json` e o Edições mostra o
  que falta com um atalho pra cá.
- **Configurações** (`lib/ui/settings/`): pastas (escolher, abrir, voltar pra
  padrão), YouTube (passo a passo do OAuth client, conectar/cancelar), agente
  principal + fallback + modelo, chave do OpenRouter, Ollama (baixar modelo) e
  os padrões do Novo edit. Salva sozinho 600 ms depois da última mudança, só
  com as chaves que essa tela edita (o motor junta com o resto).
- Edições mostra o motor conectado (versão e contrato); as outras chegam nas
  issues #139–#143.

Diálogos do sistema (pasta, JSON) passam por `Pickers` (`lib/platform.dart`,
`file_selector`): o JSON da credencial vai pro motor como conteúdo, não
caminho, pra funcionar com o motor em outra máquina.
