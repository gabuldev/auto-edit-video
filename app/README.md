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

Pacotes com o motor embutido: `.github/workflows/app-package.yml` (Actions →
App (Flutter) packages → Run workflow) compila o app, põe o motor do
`scripts/stage_engine.py` em `engine/` dentro do pacote (no macOS em
`Contents/Resources`), roda o `smoke_engine.py` nele e guarda `.dmg`, `.zip`
(Windows) e `.tar.gz` (Linux; precisa da `libmpv2` do sistema) como artefatos.
Ainda não vão pro release nem atualizam o app Tauri (#144).

Linux precisa de `clang cmake ninja-build pkg-config libgtk-3-dev libmpv-dev`
(o player é o `media_kit`, que usa a libmpv do sistema no Linux; no macOS e
no Windows ela vem no pacote). Nos testes o player é trocado por um
substituto (`PlayerScope`, `lib/ui/player.dart`).

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
  Ao iniciar, abre o pipeline dela.
- **Pipeline ao vivo** (`lib/ui/pipeline/pipeline_screen.dart`): clicar numa
  edição abre. Stages (só os que esse tipo roda), o log do `ralph.sh` por SSE
  (o motor reenvia o histórico do job, então entra do começo; segue o fim até
  você rolar pra cima), retomar a partir de um stage, parar (dois cliques) e
  o vídeo original/entregue na pasta.
- **Revisar cortes** (`lib/ui/pipeline/cuts_screen.dart`): os trechos mantidos
  com o que é dito em cada um, os blocos descartados e o que o planner cortou;
  desmarcar e "Salvar plano" (`PUT /plan`) ou "Salvar e recortar" (retoma do
  `execute`). O ▶ de cada trecho toca aquele pedaço do vídeo original
  (`GET /file/source`).
- **Resultado** (`lib/ui/result/`): o vídeo pronto no player, thumbnails A/B/C
  com o QA de cada uma e "Usar esta na publicação", os arquivos (mostrar na
  pasta), o texto de publicação com copiar e, num short pronto, **Ajustar
  legenda** (a prévia do motor no lugar do vídeo, uma faixa que se arrasta,
  tamanho, esconder; "Regravar legenda" retoma do `caption` só com a legenda).
  **Publicar no YouTube**: conectar (ou o atalho pras Configurações sem
  credencial), formulário preenchido pelo metadata (`[REVISAR]` vira só a
  dica do campo), títulos alternativos, visibilidade, agendar, legenda,
  comentário pra fixar, envio com progresso, e o histórico com o estado atual
  no YouTube (programado virou público? apagado?).
- No Resultado também: **Retenção no YouTube** (num vídeo publicado: a curva
  com as quedas, 30s/60s/metade contra os vídeos anteriores, e cada queda com
  o que era dito; clicar leva o player 3s antes) e **Efeitos e cortes** (zoom
  e B-roll num trecho marcado com o tempo do player, tirar um trecho, e
  "Refazer o render" a partir do `execute`).
- **Retenção** (`lib/ui/trend_screen.dart`, na barra lateral): a tendência do
  canal (`/api/insights/trend`) por tipo, mais antigos → mais novos e sem →
  com as lições de retenção, o gráfico dos 30s vídeo a vídeo e a lista
  (clicar abre o Resultado).
- **Shorts** (`lib/ui/shorts_screen.dart`, "Gerar shorts" num long pronto):
  roda o clipper (com o log), cada candidato com nota, gancho, fala,
  "sobrepõe outro" e "já cortado"; "Assistir" toca só aquele trecho; marcar e
  cortar em fila (vão pra Edições).
- **Estilos** (`lib/ui/styles/`): a marca (nome, @, logo, fundo da logo), a
  galeria com a thumbnail real de cada estilo, as quatro prévias do motor
  (clique pra ampliar), usar, exportar, excluir os seus, importar
  `.autoedit-style.json` (o app lê o arquivo e manda o conteúdo) e o editor
  de tokens (cores, fontes, cantos, velocidade, nome na tela, passos da
  chamada, legenda, HTML da thumbnail, cores do logo). Criar/Ajustar com IA
  segue desligado, como no Tauri (beta, só na CLI).
- O motor conectado (versão e contrato) fica no fim das Configurações.

Diálogos do sistema (pasta, JSON) passam por `Pickers` (`lib/platform.dart`,
`file_selector`): o JSON da credencial vai pro motor como conteúdo, não
caminho, pra funcionar com o motor em outra máquina.
