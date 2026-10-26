# Atualização dentro do app

O app confere se há versão nova ao abrir e a cada 6h. Se houver, mostra uma
aviso no canto de baixo ("Versão X disponível", o que mudou, **Atualizar** /
**Depois**). Nunca atualiza sem a pessoa clicar. Com uma edição rodando, o
botão fica desligado: reiniciar mataria o processamento.

- **Mac e Windows**: o updater do Tauri (`tauri-plugin-updater`) lê
  `latest.json` do último release, baixa o pacote, confere a assinatura,
  instala e reinicia. Antes de instalar, o app desliga o motor
  (`stop_engine_for_update`): no Windows o instalador não troca arquivos em uso.
- **Linux** (`.deb`/`.rpm` não se atualizam sozinhos): a faixa vem da API do
  GitHub e o botão **Baixar** abre a página do release.
- Sem internet, GitHub fora ou release ainda sem `latest.json` (os instaladores
  sobem ~1h depois da tag): não mostra nada.

Código: `desktop/ui/js/update.js` (faixa), `desktop/src-tauri/src/main.rs`
(plugins), `tauri.conf.json` → `plugins.updater` (chave pública + endpoint).

## Assinatura das atualizações

O app só instala uma atualização assinada com a chave do projeto: ninguém
consegue empurrar um app falso pelo atualizador. O CI assina em todo release
(`tauri.release.conf.json` liga `createUpdaterArtifacts`) com a chave privada
do Doppler. Sem a chave, o release sai normal, só sem atualização pelo app
(aviso no log do CI).

### Configurar (uma vez)

1. Gere o par de chaves (pede uma senha):

   ```bash
   cd desktop && ./node_modules/.bin/tauri signer generate -w ~/.tauri/auto-edit-updater.key
   ```

2. No Doppler (o mesmo config do `DOPPLER_TOKEN`, onde estão os secrets da Apple):
   - `TAURI_SIGNING_PRIVATE_KEY`: o conteúdo de `~/.tauri/auto-edit-updater.key`
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: a senha

3. A chave **pública** (`~/.tauri/auto-edit-updater.key.pub`) vai em
   `desktop/src-tauri/tauri.conf.json` → `plugins.updater.pubkey`.

**Guarde a chave privada.** Perdê-la significa que os apps já instalados não
aceitam mais nenhuma atualização (teriam que baixar o instalador de novo).

## Limitação

Quem tem uma versão anterior ao atualizador precisa baixar o instalador uma
vez. Daí em diante recebe o aviso no app.
