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
    GET  /api/browse?dir=            (folders + videos, for the picker)
    GET  /api/videos/<id>
    GET  /api/videos/<id>/plan       (cortes + o que é dito em cada um)
    PUT  /api/videos/<id>/plan       {kept_segments: [{start, end, summary?}]}
    GET  /api/videos/<id>/result     (metadata + arquivos finais)
    GET  /api/videos/<id>/file/<kind>  (video | thumbnail | captions | notes)
    POST /api/videos/<id>/open/<kind>  {reveal}  abre no app padrão / no Finder
    POST /api/edit                 {video_path, type, context, language,
                                    whisper_model, max_iterations, dry_run, cold_open, reorder,
                                    overlays_dir}
    POST /api/videos/<id>/resume   {from_stage, overlays_dir}
    POST /api/videos/<id>/stop     para o que está rodando (job, ralph avulso, fila)
    GET  /api/videos/<id>/shorts?max_dur=   (candidatos a short de um long pronto)
    POST /api/videos/<id>/shorts       {max_dur}  roda o clipper (job, SSE)
    POST /api/videos/<id>/shorts/cut   {pick: [1, 3], max_dur}  corta em fila
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
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
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
            job = jobs.resume_edit(video_id, from_stage, overlays_dir=body.get("overlays_dir"))
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

    @app.put("/api/settings")
    def put_settings():
        from auto_edit import settings

        try:
            return jsonify(settings.save(request.get_json(silent=True) or {}))
        except settings.SettingsError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/agents")
    def list_agents():
        from auto_edit import agent_status

        return jsonify({"agents": agent_status.all_status()})

    @app.post("/api/agents/<name>/test")
    def test_agent(name: str):
        from auto_edit import agent_status, agents

        if name not in agents.AGENTS:
            return jsonify({"error": f"agente desconhecido: {name}"}), 404
        body = request.get_json(silent=True) or {}
        return jsonify(agent_status.test(name, model=body.get("model") or None))

    @app.post("/api/agents/<name>/login")
    def login_agent(name: str):
        from auto_edit import agent_status, agents

        if name not in agents.AGENTS:
            return jsonify({"error": f"agente desconhecido: {name}"}), 404
        try:
            return jsonify({"command": agent_status.open_login(name)})
        except agents.AgentError as exc:
            return jsonify({"error": str(exc)}), 400

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
    app = create_app()
    app.run(host=host, port=port, threaded=True)
