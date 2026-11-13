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
- **Edições** (`lib/ui/edits/`): as edições com status, etapas e a última linha
  do log ao vivo (SSE de cada uma que roda; a lista recarrega a cada 5s), busca,
  cancelar e excluir (perguntando na própria linha) e excluir várias. Vazia, é
  uma área pra arrastar ou escolher o vídeo.
- **Biblioteca** (`lib/ui/recordings_screen.dart`): os vídeos da pasta de
  entrada com miniatura, duração, formato, tamanho e as edições de cada um;
  "Editar" abre o Novo edit com o vídeo e o tipo pelo formato.
- **Novo edit** (`lib/ui/new_edit_screen.dart`): arrastar (`desktop_drop`) ou
  escolher o vídeo, nome, tipo, contexto e as opções (vêm das Configurações).
  Por enquanto, ao iniciar volta pra Edições; a tela do pipeline ao vivo chega
  na #140.
- O motor conectado (versão e contrato) fica no fim das Configurações. Estilos
  chega na #142.

Diálogos do sistema (pasta, JSON) passam por `Pickers` (`lib/platform.dart`,
`file_selector`): o JSON da credencial vai pro motor como conteúdo, não
caminho, pra funcionar com o motor em outra máquina.
