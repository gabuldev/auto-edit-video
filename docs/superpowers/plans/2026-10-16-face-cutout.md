# Recorte automático do rosto — plano

> Executado inline (superpowers:executing-plans), TDD em cada task.

**Goal:** `{{rosto}}` / `{{rosto_contorno}}` preenchidos automaticamente com a pessoa recortada de um frame do vídeo.
**Spec:** `docs/superpowers/specs/2026-10-15-thumbnail-html-design.md` §9.

## Global Constraints
- Modelo `u2net_human_seg.onnx`, SHA-256 `01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c`, 175997641 bytes.
- Nada falha por causa do recorte: sempre cai em "sem rosto".
- Foto em `assets/thumbnails/faces/` (ou `AUTO_EDIT_ASSETS_FACES`) tem prioridade.

### Task 1: `auto_edit/face_cutout.py` + dependência
- Tests (`tests/test_face_cutout.py`, sessão ONNX falsa): máscara vira alpha e corta na caixa da pessoa; pessoa < 3% → None; `outlined` deixa pixels brancos opacos fora da pessoa; `ensure_model` com download falso: hash certo → arquivo final, hash errado → `CutoutError` e sem arquivo; `cutout_files` escolhe o frame com mais pessoa e reaproveita o cache; sem `onnxruntime` → `CutoutError`.
- `pyproject.toml`: `onnxruntime`. Smoke: `onnxruntime` nos imports.

### Task 2: lacuna `rosto_contorno` + pipeline
- `thumb_html.IMAGE_SLOTS` ganha `rosto_contorno`; `styles.html_spec` repassa.
- `tools/thumbnailer.py`: layout com `rosto`/`rosto_contorno` e sem foto → `face_cutout.cutout_files([frame])`, passa `face`/`face_outline` no spec; falha → sem rosto. Tests com `cutout_files` falso.

### Task 3: prévia + IA
- `styles.render_thumbnail`: sem foto, usa `face_cutout.preview_files()` (frames 20/40/60/80% do último vídeo; só se o modelo existe, senão dispara o download em segundo plano). Tests com fakes.
- `agents/stylist.md`: explica as duas lacunas. Docs (CLAUDE.md).
- Teste real com o vídeo mais recente e a referência do usuário.
