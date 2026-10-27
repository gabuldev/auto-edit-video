"""
Local HTTP + SSE API over the headless engine (auto_edit.engine).

This is the surface a desktop frontend (Flutter/Tauri) or the future web UI
talks to — pure JSON plus a Server-Sent-Events stream for live pipeline
progress. It is intentionally thin: all logic lives in `engine`. Flask is an
optional dependency (`pip install "auto-edit-video[api]"`); importing this
module never requires it — only `create_app()` / `serve()` do.

Endpoints
    GET  /api/health
    GET  /api/library
    GET  /api/browse?dir=            (folders + videos of a directory)
    GET  /api/recordings             Biblioteca: vídeos da pasta de entrada (subpastas até 3 níveis) + edições de cada
    GET  /api/recordings/thumb?path= miniatura JPEG de um vídeo da pasta de entrada (só dela)
    GET  /api/folders                {inbox, output}: {path, custom} — as the pipeline uses them now
    POST /api/folders/<inbox|output>/open   abre a pasta no gerenciador de arquivos
    GET  /api/video-file?path=       (nome/tamanho de um vídeo escolhido ou arrastado)
    GET  /api/videos/<id>
    GET  /api/videos/<id>/plan       (cortes + o que é dito em cada um)
    PUT  /api/videos/<id>/plan       {kept_segments: [{start, end, summary?}]}
    GET  /api/videos/<id>/captions   (legenda do short: estilo final + ajuste + fast)
    PUT  /api/videos/<id>/captions   {position, offset, size, hidden}
    POST /api/videos/<id>/captions/preview  {ajuste} → PNG
    GET  /api/videos/<id>/result     (metadata + arquivos finais)
    GET  /api/videos/<id>/file/<kind>  (video | thumbnail | captions | notes)
    POST /api/videos/<id>/open/<kind>  {reveal}  abre no app padrão / no Finder (kind source = o vídeo original)
    POST /api/edit                 {video_path, type, context, language,
                                    whisper_model, max_iterations, dry_run, cold_open, reorder,
                                    overlays_dir, name}  (name: só exibição; vazio = nome do arquivo)
    POST /api/videos/<id>/resume   {from_stage, overlays_dir, caption_only?}
    POST /api/videos/<id>/stop     para o que está rodando (job, ralph avulso, fila)
    DELETE /api/videos/<id>        para e apaga o workspace + os arquivos em output/ (nunca o vídeo original)
    GET  /api/videos/<id>/shorts?max_dur=   (candidatos a short de um long pronto)
    POST /api/videos/<id>/shorts       {max_dur}  roda o clipper (job, SSE)
    POST /api/videos/<id>/shorts/cut   {pick: [1, 3], max_dur}  corta em fila
    GET  /api/styles                  (estilos, o ativo, fontes, marca)
    PUT  /api/styles/active           {id}
    POST /api/styles                  {name, tokens, id?, activate?}  salva um estilo seu
    DELETE /api/styles/<id>
    POST /api/styles/preview/<kind>   {tokens} → PNG (thumbnail | lower_third | cta)
    POST /api/styles/generate         {description, image?} → {job_id}; SSE progress/done{result: rascunho}/error (IA)
    POST /api/styles/adjust           {tokens, request, image?} → {job_id}, o mesmo a partir de um estilo
    POST /api/styles/palette          {image?} → {colors, suggested} (sem imagem: o logo salvo)
    POST /api/styles/<id>/export      grava em Downloads e mostra no Finder → {path}
    POST /api/styles/import           {file} → estilo salvo (nunca sobrescreve)
    PUT|DELETE|GET /api/brand/logo    {data: "data:image/png;base64,…"}
    GET  /api/publish/youtube                 (conta conectada?)
    POST /api/publish/youtube/connect         abre o OAuth no navegador
    POST /api/publish/youtube/disconnect
    GET  /api/videos/<id>/publish             (defaults do metadata + histórico)
    POST /api/videos/<id>/publish/youtube     {title, description, tags, privacy,
                                               publish_at, force}  upload (job, SSE)
    GET  /api/videos/<id>/retention           (análise salva da curva de retenção)
    POST /api/videos/<id>/retention           busca a curva no YouTube agora
    GET  /api/settings / PUT /api/settings   (~/.auto-edit/settings.json)
    GET  /api/agents                          (instalado? versão? Ollama: modelos)
    POST /api/agents/<name>/test {model}      prompt mínimo de verdade
    POST /api/agents/<name>/login             abre o Terminal com o login da CLI
    POST /api/agents/ollama/pull {model}
    GET  /api/setup                           primeira execução: agente pronto? Whisper baixado?
    PUT/DELETE /api/agents/openrouter/key {key}  chave da API (nunca volta inteira)
    POST /api/agents/<name>/install           instalador oficial num terminal (ou a página de download)
    POST /api/setup/whisper {model}           baixa o modelo do Whisper (progresso em /api/setup)
    POST /api/open-url                        {url}  só links do YouTube
    GET  /api/jobs/<job_id>/events        (SSE)
    GET  /api/videos/<id>/events          (SSE, that video's current job)
"""
from __future__ import annotations

import json
from typing import Iterator

from auto_edit import engine
from auto_edit import shorts as sh
from auto_edit.publish import youtube as yt


def _sse(events: Iterator[dict]) -> Iterator[str]:
    for ev in events:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


def create_app(jobs: engine.JobManager | None = None):
    """Build the Flask app. Raises RuntimeError if Flask isn't installed."""
    try:
        from flask import Flask, Response, jsonify, request, send_file
    except ImportError as exc:  # pragma: no cover - exercised only without flask
        raise RuntimeError(
            "Flask is required for the API server. Install with: "
            'pip install "auto-edit-video[api]"'
        ) from exc

    jobs = jobs or engine.jobs
    app = Flask("auto_edit.api")

    # Permissive CORS: this is a localhost-only dev API consumed by a separate
    # origin (the Tauri webview / a browser preview). Flask auto-handles the
    # OPTIONS preflight; we just stamp the headers on every response.
    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return resp

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "repo_root": str(engine.repo_root())})

    @app.get("/api/library")
    def library():
        return jsonify(
            {
                "videos": engine.list_library(
                    active_ids=jobs.active_ids(),
                    failed_ids=jobs.failed_ids(),
                    queued_ids=jobs.queued_ids(),
                )
            }
        )

    @app.get("/api/browse")
    def browse():
        """Folders + video files of a directory (default: the inbox) for the picker."""
        return jsonify(engine.browse(request.args.get("dir") or None))

    @app.get("/api/video-file")
    def video_file_info():
        """Name/size of a path the app got from its dialog or a drop — and a check it's a video."""
        path = request.args.get("path") or ""
        info = engine.video_file(path)
        if info is None:
            return jsonify({"error": "não é um vídeo que o pipeline abre (mp4, mov, mkv…)", "path": path}), 404
        return jsonify(info)

    @app.get("/api/videos/<video_id>")
    def video_detail(video_id: str):
        data = engine.detail(
            video_id,
            active=video_id in jobs.active_ids(),
            failed=video_id in jobs.failed_ids(),
            queued=video_id in jobs.queued_ids(),
        )
        if data is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        job = jobs.job_for_video(video_id)
        if job is not None:
            data["job_id"] = job.id
        return jsonify(data)

    @app.get("/api/videos/<video_id>/plan")
    def video_plan(video_id: str):
        data = engine.read_plan(video_id)
        if data is None:
            return jsonify({"error": "no_plan", "id": video_id}), 404
        return jsonify(data)

    @app.put("/api/videos/<video_id>/plan")
    def save_video_plan(video_id: str):
        body = request.get_json(silent=True) or {}
        try:
            data = engine.write_plan(video_id, body.get("kept_segments"))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(data)

    @app.get("/api/videos/<video_id>/captions")
    def video_captions(video_id: str):
        try:
            return jsonify(engine.video_captions(video_id))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/videos/<video_id>/captions")
    def save_video_captions(video_id: str):
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(engine.save_video_captions(video_id, body))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/videos/<video_id>/captions/preview")
    def video_caption_preview(video_id: str):
        import io

        from auto_edit import styles

        body = request.get_json(silent=True) or {}
        try:
            png = engine.video_caption_preview(video_id, body)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400
        return send_file(io.BytesIO(png), mimetype="image/png", max_age=0)

    @app.get("/api/videos/<video_id>/result")
    def video_result(video_id: str):
        data = engine.result(video_id)
        if data is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        return jsonify(data)

    @app.get("/api/videos/<video_id>/file/<kind>")
    def video_file(video_id: str, kind: str):
        """Serve one finished artifact — the player and the thumbnail read from here."""
        path = engine.artifact_path(video_id, kind)
        if path is None:
            return jsonify({"error": "not_found", "id": video_id, "kind": kind}), 404
        return send_file(
            path,
            mimetype=engine.ARTIFACT_MIME.get(kind),
            conditional=True,  # range requests: seeking in the player
            download_name=path.name,
        )

    @app.post("/api/videos/<video_id>/open/<kind>")
    def open_file(video_id: str, kind: str):
        """Open an artifact on this machine (default app, or `reveal` in the folder)."""
        body = request.get_json(silent=True) or {}
        path = engine.open_artifact(video_id, kind, reveal=bool(body.get("reveal")))
        if path is None:
            return jsonify({"error": "not_found", "id": video_id, "kind": kind}), 404
        return jsonify({"opened": str(path)})

    @app.post("/api/edit")
    def start_edit():
        body = request.get_json(silent=True) or {}
        video_path = body.get("video_path")
        video_type = body.get("type")
        if not video_path or video_type not in ("short", "long"):
            return jsonify({"error": "video_path and type ('short'|'long') are required"}), 400
        from auto_edit import settings

        saved = settings.load()  # what the request leaves out comes from Settings
        try:
            job = jobs.start_edit(
                video_path,
                video_type,
                context=body.get("context", ""),
                whisper_model=body.get("whisper_model") or saved["whisper_model"],
                language=body.get("language") or saved["language"],
                max_iterations=int(body.get("max_iterations", 3)),
                dry_run=bool(body.get("dry_run", False)),
                cold_open=bool(body.get("cold_open", saved["cold_open"])),
                reorder=bool(body.get("reorder", saved["reorder"])),
                overlays_dir=body.get("overlays_dir") or saved["overlays_dir"],
                name=body.get("name") or None,
            )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"job_id": job.id, "video_id": job.video_id}), 202

    @app.post("/api/videos/<video_id>/resume")
    def resume(video_id: str):
        body = request.get_json(silent=True) or {}
        from_stage = body.get("from_stage")
        if not from_stage:
            return jsonify({"error": "from_stage is required"}), 400
        try:
            job = jobs.resume_edit(
                video_id, from_stage, overlays_dir=body.get("overlays_dir"),
                caption_only=body.get("caption_only") is True,
            )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job_id": job.id, "video_id": job.video_id}), 202

    def _max_dur(raw) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return sh.DEFAULT_MAX_DURATION
        return value if value > 0 else sh.DEFAULT_MAX_DURATION

    @app.get("/api/videos/<video_id>/shorts")
    def shorts_state(video_id: str):
        data = engine.shorts_state(video_id, max_duration=_max_dur(request.args.get("max_dur")))
        if data is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        job = jobs.job_for_video(video_id)
        if job is not None and job.kind == "shorts":
            data["job"] = {"id": job.id, "status": job.status}
        return jsonify(data)

    @app.post("/api/videos/<video_id>/shorts")
    def find_shorts(video_id: str):
        body = request.get_json(silent=True) or {}
        try:
            job = jobs.find_shorts(video_id, max_duration=_max_dur(body.get("max_dur")))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except sh.ShortsError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job_id": job.id, "video_id": job.video_id}), 202

    @app.post("/api/videos/<video_id>/shorts/cut")
    def cut_shorts(video_id: str):
        body = request.get_json(silent=True) or {}
        pick = body.get("pick")
        if not isinstance(pick, list):
            return jsonify({"error": "pick precisa ser uma lista, ex: [1, 3]"}), 400
        try:
            ids = jobs.cut_shorts(video_id, pick, max_duration=_max_dur(body.get("max_dur")))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except (sh.ShortsError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"shorts": ids}), 202

    @app.get("/api/publish/youtube")
    def youtube_account():
        return jsonify(engine.youtube_account())

    @app.post("/api/publish/youtube/connect")
    def youtube_connect():
        return jsonify(engine.connect_youtube()), 202

    @app.post("/api/publish/youtube/disconnect")
    def youtube_disconnect():
        return jsonify(engine.disconnect_youtube())

    @app.get("/api/videos/<video_id>/publish")
    def publish_state(video_id: str):
        data = engine.publish_state(video_id)
        if data is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        job = jobs.job_for_video(video_id)
        if job is not None and job.kind == "publish":
            data["job"] = {"id": job.id, "status": job.status}
        return jsonify(data)

    @app.post("/api/videos/<video_id>/publish/youtube")
    def publish_youtube(video_id: str):
        body = request.get_json(silent=True) or {}
        force = bool(body.get("force"))
        state = engine.publish_state(video_id)
        if state is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        if state["published"] and not force:
            return jsonify({"error": "este vídeo já foi enviado pro YouTube", "published": state["published"]}), 409
        tags = body.get("tags") or []
        if isinstance(tags, str):
            tags = [t for t in tags.split(",")]
        try:
            job = jobs.publish_youtube(
                video_id,
                {
                    "title": body.get("title", ""),
                    "description": body.get("description", ""),
                    "tags": tags,
                    "privacy": body.get("privacy", "private"),
                    "publish_at": body.get("publish_at"),
                    "captions": body.get("captions", True),
                    "comment": body.get("comment"),
                },
                force=force,
            )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except yt.PublishError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job_id": job.id, "video_id": job.video_id}), 202

    @app.get("/api/videos/<video_id>/retention")
    def retention_state(video_id: str):
        data = engine.retention_state(video_id)
        if data is None:
            return jsonify({"error": "not_found", "id": video_id}), 404
        return jsonify(data)

    @app.post("/api/videos/<video_id>/retention")
    def refresh_retention(video_id: str):
        from auto_edit import retention as ret
        from auto_edit import youtube_auth

        try:
            return jsonify(engine.refresh_retention(video_id))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except (ret.RetentionError, youtube_auth.AuthError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/settings")
    def get_settings():
        from auto_edit import settings

        return jsonify(settings.load())

    @app.get("/api/recordings")
    def list_recordings():
        """The Biblioteca: the videos in the inbox, each with its edits."""
        library = engine.list_library(
            active_ids=jobs.active_ids(), failed_ids=jobs.failed_ids(), queued_ids=jobs.queued_ids()
        )
        return jsonify(engine.recordings_view(library))

    @app.get("/api/recordings/thumb")
    def recording_thumb():
        path = engine.recording_thumbnail(request.args.get("path") or "")
        if path is None:
            return jsonify({"error": "not_found"}), 404
        return send_file(path, mimetype="image/jpeg", max_age=3600)

    @app.get("/api/folders")
    def get_folders():
        return jsonify(engine.folders())

    @app.post("/api/folders/<which>/open")
    def open_folder(which: str):
        """Open the inbox or the output folder in the file manager."""
        if which not in engine.FOLDERS:
            return jsonify({"error": "not_found", "folder": which}), 404
        path = engine.open_folder(which)
        if path is None:
            return jsonify({"error": f"a pasta não existe: {engine.folders()[which]['path']}"}), 404
        return jsonify({"opened": str(path)})

    @app.put("/api/settings")
    def put_settings():
        from auto_edit import settings

        try:
            return jsonify(settings.save(request.get_json(silent=True) or {}))
        except settings.SettingsError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/styles")
    def list_styles():
        from auto_edit import agents, render, styles

        return jsonify({
            "active": styles.active_id(),
            "styles": styles.list_styles(),
            "fonts": [{"id": k, "label": v["label"]} for k, v in styles.FONTS.items()],
            "icons": list(styles.ICONS),
            "positions": {"lower_third": list(styles.POSITIONS_LT), "cta": list(styles.POSITIONS_CTA)},
            "brand": render.brand(),
            "ai_vision": agents.vision_ready(),
        })

    @app.put("/api/styles/active")
    def set_active_style():
        from auto_edit import styles

        try:
            return jsonify({"active": styles.set_active((request.get_json(silent=True) or {}).get("id") or "")})
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/styles")
    def save_style():
        from auto_edit import styles

        body = request.get_json(silent=True) or {}
        try:
            saved = styles.save(body.get("name") or "", body.get("tokens"), body.get("id"), body.get("description") or "")
            if body.get("activate"):
                styles.set_active(saved["id"])
            return jsonify(saved)
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/styles/<style_id>")
    def delete_style(style_id: str):
        from auto_edit import styles

        try:
            styles.delete(style_id)
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"active": styles.active_id()})

    @app.post("/api/styles/preview/<kind>")
    def preview_style(kind: str):
        import io

        from auto_edit import styles

        tokens = (request.get_json(silent=True) or {}).get("tokens")
        try:
            png = styles.preview(tokens, kind)
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400
        return send_file(io.BytesIO(png), mimetype="image/png", max_age=0)

    def _image_bytes(data_url) -> bytes | None:
        """A data: URL from the app → bytes; None when absent. ValueError when wrong."""
        import base64
        import re

        if not data_url:
            return None
        m = re.fullmatch(r"data:image/[a-z+.-]+;base64,([A-Za-z0-9+/=\s]+)", str(data_url).strip())
        if not m:
            raise ValueError("envie uma imagem PNG, JPG ou WebP")
        data = base64.b64decode(m.group(1))
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("imagem grande demais (máx. 5 MB)")
        return data

    def _style_job(description: str, image: bytes | None, base: dict | None):
        from auto_edit import styles

        def target(emit):
            try:
                draft = styles.generate(description, image, base=base,
                                        on_progress=lambda msg: emit({"type": "progress", "message": msg}))
            except styles.StyleError as exc:
                emit({"type": "error", "message": str(exc)})
                return
            emit({"type": "done", "status": "done", "result": draft})

        return jsonify({"job_id": jobs.run_task("style", target).id}), 202

    @app.post("/api/styles/generate")
    def generate_style():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("description", ""), str):
            return jsonify({"error": "envie {description, image?}"}), 400
        try:
            image = _image_bytes(body.get("image"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return _style_job(body.get("description") or "", image, None)

    @app.post("/api/styles/adjust")
    def adjust_style():
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or not isinstance(body.get("tokens"), dict)
                or not isinstance(body.get("request"), str) or not body["request"].strip()):
            return jsonify({"error": "envie {tokens, request}"}), 400
        try:
            image = _image_bytes(body.get("image"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return _style_job(body["request"], image, body["tokens"])

    @app.post("/api/styles/palette")
    def style_palette():
        from auto_edit import palette, render

        body = request.get_json(silent=True) or {}
        try:
            image = _image_bytes(body.get("image")) or render.brand().get("logo")
            if not image:
                return jsonify({"error": "sem logo salva nem imagem"}), 400
            colors = palette.extract(image)
        except ValueError as exc:  # PaletteError is one
            return jsonify({"error": str(exc)}), 400
        return jsonify({"colors": colors, "suggested": palette.suggest(colors)})

    @app.post("/api/styles/<style_id>/export")
    def export_style(style_id: str):
        from auto_edit import styles

        if not styles.get(style_id):
            return jsonify({"error": f"estilo não encontrado: {style_id}"}), 404
        path = styles.export_file(style_id, engine.downloads_dir())
        engine.os_open(path, reveal=True)
        return jsonify({"path": str(path)})

    @app.post("/api/styles/import")
    def import_style():
        from auto_edit import styles

        try:
            return jsonify(styles.import_((request.get_json(silent=True) or {}).get("file")))
        except styles.StyleError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/brand/logo")
    def upload_logo():
        from auto_edit import render

        try:
            render.save_logo((request.get_json(silent=True) or {}).get("data") or "")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(render.brand())

    @app.delete("/api/brand/logo")
    def delete_logo():
        from auto_edit import render

        render.save_logo(None)
        return jsonify(render.brand())

    @app.get("/api/brand/logo")
    def get_logo():
        from auto_edit import render

        logo = render.brand().get("logo")
        if not logo:
            return jsonify({"error": "sem logo"}), 404
        return send_file(logo, max_age=0)

    @app.get("/api/agents")
    def list_agents():
        from auto_edit import agent_status

        return jsonify({"agents": agent_status.all_status()})

    @app.post("/api/agents/<name>/test")
    def test_agent(name: str):
        from auto_edit import agent_status, agents

        if name not in agents.AGENTS:
            return jsonify({"error": f"agente desconhecido: {name}"}), 404
        from auto_edit import settings

        body = request.get_json(silent=True) or {}
        result = agent_status.test(name, model=body.get("model") or None)
        if result.get("ok"):
            # A working agent is what the first-run setup waits for; the first
            # one that works also becomes the primary if none was verified yet.
            saved = settings.load()
            update = {"verified_agent": name}
            if not saved.get("verified_agent"):
                update["agent"] = {"primary": name}
            settings.save(update)
        return jsonify(result)

    @app.post("/api/agents/<name>/login")
    def login_agent(name: str):
        from auto_edit import agent_status, agents

        if name not in agents.AGENTS:
            return jsonify({"error": f"agente desconhecido: {name}"}), 404
        try:
            return jsonify({"command": agent_status.open_login(name)})
        except agents.AgentError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/agents/openrouter/key")
    def save_openrouter_key():
        from auto_edit import agent_status, agents

        key = ((request.get_json(silent=True) or {}).get("key") or "").strip()
        if not key:
            return jsonify({"error": "cole a chave do OpenRouter (sk-or-…)"}), 400
        agents.save_openrouter_key(key)
        return jsonify(agent_status.status("openrouter"))

    @app.delete("/api/agents/openrouter/key")
    def delete_openrouter_key():
        from auto_edit import agent_status, agents

        agents.save_openrouter_key(None)
        return jsonify(agent_status.status("openrouter"))

    @app.get("/api/setup")
    def setup_state():
        from auto_edit import setup

        return jsonify(setup.state())

    @app.post("/api/agents/<name>/install")
    def install_agent(name: str):
        from auto_edit import agents, setup

        if name not in agents.AGENTS:
            return jsonify({"error": f"agente desconhecido: {name}"}), 404
        return jsonify(setup.open_install(name))

    @app.post("/api/setup/whisper")
    def download_whisper():
        from auto_edit import settings, setup

        model = (request.get_json(silent=True) or {}).get("model") or settings.load()["whisper_model"]
        if model not in setup.WHISPER_SIZES_MB:
            return jsonify({"error": f"modelo desconhecido: {model}"}), 400
        return jsonify(setup.download_whisper(model)), 202

    @app.post("/api/agents/ollama/pull")
    def pull_ollama():
        from auto_edit import agent_status, agents

        model = ((request.get_json(silent=True) or {}).get("model") or "").strip()
        if not model:
            return jsonify({"error": "informe o modelo, ex.: qwen2.5:7b"}), 400
        try:
            agent_status.pull(model)
        except agents.AgentError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"model": model, "status": "downloading"}), 202

    @app.post("/api/open-url")
    def open_url():
        body = request.get_json(silent=True) or {}
        if not engine.open_url(body.get("url")):
            return jsonify({"error": "só links do YouTube e das CLIs de agente"}), 400
        return jsonify({"opened": body["url"]})

    @app.delete("/api/videos/<video_id>")
    def delete_video(video_id: str):
        """Stop whatever runs on it, then remove the workspace and its output
        files (never the source video)."""
        try:
            jobs.stop(video_id)
            return jsonify(engine.delete_video(video_id))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except OSError as exc:  # Windows: a file still open (player, ffmpeg)
            return jsonify({"error": f"não deu pra apagar tudo: {exc}"}), 409

    @app.post("/api/videos/<video_id>/stop")
    def stop(video_id: str):
        try:
            return jsonify(jobs.stop(video_id))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/jobs/<job_id>/events")
    def job_events(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "not_found", "job_id": job_id}), 404
        return Response(_sse(job.subscribe()), mimetype="text/event-stream")

    @app.get("/api/videos/<video_id>/events")
    def video_events(video_id: str):
        job = jobs.job_for_video(video_id)
        if job is None:
            return jsonify({"error": "no_active_job", "id": video_id}), 404
        return Response(_sse(job.subscribe()), mimetype="text/event-stream")

    return app


def serve(host: str = "127.0.0.1", port: int = 8760) -> None:
    """Start the API server (blocking). threaded=True so SSE streams don't block."""
    engine.ensure_default_folders()  # workspace/input and workspace/output, ready on first launch
    app = create_app()
    app.run(host=host, port=port, threaded=True)
