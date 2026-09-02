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
    POST /api/edit                 {video_path, type, context, language,
                                    whisper_model, max_iterations, dry_run,
                                    overlays_dir}
    POST /api/videos/<id>/resume   {from_stage, overlays_dir}
    GET  /api/jobs/<job_id>/events        (SSE)
    GET  /api/videos/<id>/events          (SSE, that video's current job)
"""
from __future__ import annotations

import json
from typing import Iterator

from auto_edit import engine


def _sse(events: Iterator[dict]) -> Iterator[str]:
    for ev in events:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


def create_app(jobs: engine.JobManager | None = None):
    """Build the Flask app. Raises RuntimeError if Flask isn't installed."""
    try:
        from flask import Flask, Response, jsonify, request
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
                    active_ids=jobs.active_ids(), failed_ids=jobs.failed_ids()
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

    @app.post("/api/edit")
    def start_edit():
        body = request.get_json(silent=True) or {}
        video_path = body.get("video_path")
        video_type = body.get("type")
        if not video_path or video_type not in ("short", "long"):
            return jsonify({"error": "video_path and type ('short'|'long') are required"}), 400
        try:
            job = jobs.start_edit(
                video_path,
                video_type,
                context=body.get("context", ""),
                whisper_model=body.get("whisper_model", "small"),
                language=body.get("language", "pt"),
                max_iterations=int(body.get("max_iterations", 3)),
                dry_run=bool(body.get("dry_run", False)),
                overlays_dir=body.get("overlays_dir"),
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
