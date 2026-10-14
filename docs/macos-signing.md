# Assinatura e notarização no macOS

Sem isso, o macOS bloqueia a primeira abertura do app ("Apple could not verify
'Auto-Edit' is free of malware"). Com isso, o `.dmg` abre com duplo clique.

O CI (`.github/workflows/desktop.yml`) assina e notariza **sozinho** em todo
release, buscando os secrets abaixo no Doppler (`DOPPLER_TOKEN`). Sem eles, o app sai com assinatura
ad-hoc (o comportamento antigo). Pull requests sempre usam ad-hoc.

## O que o CI faz

1. Monta o motor (`scripts/stage_engine.py`) e pré-compila os `.pyc`.
2. Assina cada binário do motor — Python, as libs do torch/numpy, ffmpeg —
   com o Developer ID, hardened runtime e timestamp
   (`scripts/sign_macos_engine.py`). Os executáveis levam
   `desktop/src-tauri/engine.entitlements` (JIT do numba, módulos do Python).
3. Roda o smoke test no motor já assinado.
4. O Tauri assina o app, manda pra Apple notarizar e grampeia o ticket.

O app nunca escreve dentro de si (`PYTHONDONTWRITEBYTECODE`, cache do numba
em `~/.auto-edit/cache`): um arquivo novo dentro do bundle quebraria a
assinatura. O smoke test falha se isso acontecer.

## Configurar (uma vez)

Precisa ser feito por quem é **Account Holder** do time na Apple Developer.

### 1. Certificado Developer ID Application

1. No Mac: **Acesso às Chaves → Assistente de Certificado → Solicitar um
   Certificado de uma Autoridade de Certificação…** → "Salvo em disco".
2. Em [developer.apple.com/account/resources/certificates](https://developer.apple.com/account/resources/certificates/add)
   → **+** → **Developer ID Application** → envie o arquivo `.certSigningRequest`.
3. Baixe o `.cer` e dê duplo clique (entra no Acesso às Chaves).
4. No Acesso às Chaves, em **Meus Certificados**, clique com o direito em
   *Developer ID Application: …* → **Exportar** → formato `.p12`, com uma senha.

Confira o nome exato da identidade:

```bash
security find-identity -v -p codesigning | grep "Developer ID Application"
```

### 2. Chave de API do App Store Connect (pra notarizar)

[appstoreconnect.apple.com/access/integrations/api](https://appstoreconnect.apple.com/access/integrations/api)
→ **Team Keys** → **+** → acesso **Developer** → gere e baixe o `AuthKey_XXXX.p8`
(só dá pra baixar uma vez). Anote o **Key ID** e o **Issuer ID** da página.

### 3. Secrets no Doppler

Os secrets ficam no **Doppler**; o GitHub só guarda um token de leitura.

| Secret no Doppler | Valor |
|---|---|
| `APPLE_CERTIFICATE` | o `.p12` em base64: `base64 -i DeveloperID.p12 \| pbcopy` |
| `APPLE_CERTIFICATE_PASSWORD` | a senha do `.p12` |
| `APPLE_SIGNING_IDENTITY` | `Developer ID Application: NOME (TEAMID)` |
| `APPLE_API_KEY` | Key ID |
| `APPLE_API_ISSUER` | Issuer ID |
| `APPLE_API_KEY_P8` | conteúdo do `AuthKey_XXXX.p8` |

Crie um **service token** (só leitura) da config onde eles estão e salve no
GitHub:

```bash
gh secret set DOPPLER_TOKEN        # cole o token dp.st.…
```

Depois, apague o `.p12` e o `.p8` do disco. O próximo release já sai
notarizado. Pra refazer um release existente: **Actions → Desktop app → Run
workflow** com a tag.

## Conferir um app baixado

```bash
spctl -a -vv /Applications/Auto-Edit.app        # source=Notarized Developer ID
xcrun stapler validate /Applications/Auto-Edit.app
```
