# Overlay assets (graphics on the video)

## Onde colocar os ficheiros (único sítio “oficial”)

Coloca **sempre** os MP4 aqui:

```text
<raiz-do-repo>/assets/overlays/
```

Nomes esperados (ver `agents/overlayer.md`):

| Ficheiro | Uso |
|----------|-----|
| `lowerthid_gabul.mp4` | Lower third com nome (fundo verde) |
| `ctas.mp4` | CTA / subscrever (fundo verde) |

Estes ficheiros **deixam de ser ignorados pelo `.gitignore`** (só a pasta `assets/overlays` é exceção) para o Git e o Cursor os verem e podem ser versionados.

## Chroma key

FFmpeg usa verde **`#00FF00`** (`0x00FF00`). Exporta com fundo verde sólido ou ajusta `CHROMA_*` em `tools/overlayer.py`.

Antes do chromakey, cada overlay é **escalado para a resolução do vídeo editado** (com letterbox), para um gráfico 1080p não ficar só no canto superior esquerdo num vídeo 4K.

## Resolução de caminhos

O overlayer procura nesta ordem:

1. **`$AUTO_EDIT_REPO_ROOT/assets/overlays`** — usa este
2. **`$AUTO_EDIT_REPO_ROOT/overlays`** — só se ainda tiveres ficheiros antigos na raiz; o ideal é **migrar** para `assets/overlays/`

Para copiar de `overlays/` → `assets/overlays/` uma vez:

```bash
auto-edit sync-overlays
```

Override total (uma pasta só):

```bash
export AUTO_EDIT_ASSETS_OVERLAYS=/caminho/absoluto/para/overlays
```

## Timestamps

`original_start` em `overlay_plan.json` está em **tempo do vídeo original** (antes dos cortes). Se esse instante for cortado, o overlay é ignorado. Ajusta o plano ou os cortes em `reviewed_plan.json`.
