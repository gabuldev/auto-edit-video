"""The engine's contract (auto_edit/openapi.yaml) can't drift from the code:
every Flask route is in the spec and vice versa, and the real answers of the
engine match the schemas the Dart client is generated from."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from auto_edit import api, engine

SPEC = yaml.safe_load(api.SPEC_PATH.read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "delete", "patch"}


def _operations():
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


def _resolve(ref: str) -> dict:
    assert ref.startswith("#/"), ref
    node = SPEC
    for part in ref[2:].split("/"):
        node = node[part]
    return node


# ── A small JSON Schema validator: the subset openapi.yaml uses ──────────────

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(value, schema: dict, where: str = "$") -> list[str]:
    """Errors of `value` against `schema` (empty when it matches)."""
    if "$ref" in schema:
        return validate(value, _resolve(schema["$ref"]), where)
    errors: list[str] = []
    for sub in schema.get("allOf", []):
        errors += validate(value, sub, where)
    for key in ("oneOf", "anyOf"):
        if key in schema and not any(not validate(value, s, where) for s in schema[key]):
            errors.append(f"{where}: matches none of {key}")
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_TYPES[t](value) for t in types):
            return errors + [f"{where}: {value!r} is not {'/'.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{where}: missing {name!r}")
        extra = schema.get("additionalProperties")
        for name, v in value.items():
            if name in props:
                errors += validate(v, props[name], f"{where}.{name}")
            elif isinstance(extra, dict):
                errors += validate(v, extra, f"{where}.{name}")
            elif extra is False:
                errors.append(f"{where}: unexpected {name!r}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], f"{where}[{i}]")
    return errors


def _response_schema(path: str, method: str, status: int) -> dict:
    resp = SPEC["paths"][path][method]["responses"][str(status)]
    if "$ref" in resp:
        resp = _resolve(resp["$ref"])
    return resp["content"]["application/json"]["schema"]


# ── The document itself ──────────────────────────────────────────────────────


class TestDocument:
    def test_is_openapi_3_1_with_a_version(self):
        assert SPEC["openapi"].startswith("3.1")
        assert re.fullmatch(r"\d+\.\d+\.\d+", SPEC["info"]["version"])
        assert api.api_version() == SPEC["info"]["version"]

    def test_is_a_valid_openapi_document(self):
        validator = pytest.importorskip("openapi_spec_validator")
        validator.validate(SPEC)

    def test_every_operation_has_a_unique_id_and_responses(self):
        ids = [op.get("operationId") for _, _, op in _operations()]
        assert all(ids), "operation without operationId"
        assert len(ids) == len(set(ids)), "duplicated operationId"
        assert all(op.get("responses") for _, _, op in _operations())

    def test_every_ref_resolves(self):
        refs = re.findall(r'\$ref["\']?:\s*["\']([^"\']+)', api.SPEC_PATH.read_text(encoding="utf-8"))
        assert refs
        for ref in refs:
            _resolve(ref)

    def test_path_parameters_are_declared(self):
        for path, item in SPEC["paths"].items():
            names = set(re.findall(r"{(\w+)}", path))
            for method in METHODS & set(item):
                params = item.get("parameters", []) + item[method].get("parameters", [])
                declared = {(_resolve(p["$ref"]) if "$ref" in p else p)["name"] for p in params}
                assert names <= declared, f"{method.upper()} {path}: {names - declared}"


# ── Spec ↔ Flask routes ──────────────────────────────────────────────────────


def _flask_routes() -> set[tuple[str, str]]:
    pytest.importorskip("flask")
    app = api.create_app()
    out = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        for m in rule.methods - {"HEAD", "OPTIONS"}:
            out.add((m.lower(), path))
    return out


def test_spec_and_routes_match():
    routes = _flask_routes()
    spec = {(m, p) for p, m, _ in _operations()}
    assert sorted(routes - spec) == [], "routes missing from auto_edit/openapi.yaml"
    assert sorted(spec - routes) == [], "spec operations with no route"


# ── Real answers match the schemas ───────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    monkeypatch.setattr(engine, "library_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTO_EDIT_INBOX", str(tmp_path / "inbox"))
    (tmp_path / "inbox").mkdir()
    _long(tmp_path)
    _short(tmp_path)
    return api.create_app().test_client()


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _long(root: Path) -> None:
    ws = root / "vid"
    ws.mkdir()
    _write(ws / "pipeline.json", {
        "video_name": "vid", "type": "long", "language": "pt", "current_stage": "done",
        "created_at": "2026-01-01T00:00:00+00:00", "video_path": str(root / "inbox" / "vid.mp4"),
        "stages": {"extract": {"status": "done"}, "plan": {"status": "done"}},
    })
    _write(ws / "transcription.json", {"duration": 30.0, "segments": [
        {"start": 0.0, "end": 10.0, "text": "oi"}, {"start": 10.0, "end": 30.0, "text": "tudo bem"}]})
    _write(ws / "reviewed_plan.json", {
        "kept_segments": [{"start": 0.0, "end": 10.0, "summary": "abertura"}, {"start": 12.0, "end": 30.0}],
        "cuts": [{"start": 10.0, "end": 12.0, "reason": "pausa", "type": "silence"}],
    })
    _write(ws / "metadata.json", {
        "youtube_title": "Título", "youtube_description": "Desc", "tags": ["a"],
        "thumbnail_variants": [{"id": "A", "layout": "atual", "file": "thumbnail.png", "qa": "aprovada"}],
    })
    out = root / "output"
    out.mkdir(exist_ok=True)
    (out / "vid_final.mp4").write_bytes(b"\0" * 64)
    (out / "vid_thumbnail.png").write_bytes(b"png")


def _short(root: Path) -> None:
    ws = root / "clip"
    ws.mkdir()
    _write(ws / "pipeline.json", {
        "video_name": "clip", "type": "short", "language": "pt", "current_stage": "caption",
        "created_at": "2026-01-02T00:00:00+00:00", "stages": {"caption": {"status": "running"}},
    })


def _check(client, method: str, url: str, path: str, status: int = 200, body=None):
    resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert resp.status_code == status, resp.get_data(as_text=True)
    errors = validate(resp.get_json(), _response_schema(path, method, status))
    assert errors == [], f"{method.upper()} {url}:\n" + "\n".join(errors)


GETS = [
    ("/api/health", "/api/health"),
    ("/api/library", "/api/library"),
    ("/api/folders", "/api/folders"),
    ("/api/recordings", "/api/recordings"),
    ("/api/videos/vid", "/api/videos/{video_id}"),
    ("/api/videos/clip", "/api/videos/{video_id}"),
    ("/api/videos/vid/plan", "/api/videos/{video_id}/plan"),
    ("/api/videos/vid/result", "/api/videos/{video_id}/result"),
    ("/api/videos/vid/effects", "/api/videos/{video_id}/effects"),
    ("/api/videos/clip/captions", "/api/videos/{video_id}/captions"),
    ("/api/videos/vid/shorts", "/api/videos/{video_id}/shorts"),
    ("/api/videos/vid/publish", "/api/videos/{video_id}/publish"),
    ("/api/videos/vid/retention", "/api/videos/{video_id}/retention"),
    ("/api/insights/trend", "/api/insights/trend"),
    ("/api/publish/youtube", "/api/publish/youtube"),
    ("/api/styles", "/api/styles"),
    ("/api/settings", "/api/settings"),
]


@pytest.mark.parametrize("url,path", GETS, ids=[g[0] for g in GETS])
def test_get_answers_match_the_schema(client, url, path):
    _check(client, "get", url, path)


def test_browse_matches(client, tmp_path):
    (tmp_path / "inbox" / "a.mp4").write_bytes(b"x")
    _check(client, "get", f"/api/browse?dir={tmp_path / 'inbox'}", "/api/browse")
    _check(client, "get", f"/api/video-file?path={tmp_path / 'inbox' / 'a.mp4'}", "/api/video-file")


def test_writes_match_the_schema(client):
    _check(client, "put", "/api/videos/vid/plan", "/api/videos/{video_id}/plan",
           body={"kept_segments": [{"start": 0, "end": 8}, {"start": 12, "end": 30}]})
    _check(client, "post", "/api/videos/vid/plan/cut", "/api/videos/{video_id}/plan/cut",
           body={"start": 14, "end": 16, "timeline": "original"})
    _check(client, "put", "/api/videos/vid/thumbnail", "/api/videos/{video_id}/thumbnail", body={"variant": "A"})
    _check(client, "put", "/api/videos/clip/captions", "/api/videos/{video_id}/captions",
           body={"position": "top", "size": 120})
    _check(client, "post", "/api/videos/vid/stop", "/api/videos/{video_id}/stop", body={})


@pytest.fixture
def fake_agents(monkeypatch, tmp_path):
    """Claude and Ollama installed (Ollama with a model, downloading another),
    an OpenRouter key saved: every shape /api/agents and /api/setup give."""
    from auto_edit import agent_status, agents

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(agents, "find_binary", lambda a: f"/bin/{a.name}" if a.name in ("claude", "ollama") else None)
    monkeypatch.setattr(agent_status, "_version", lambda binary: "1.0")
    monkeypatch.setattr(agents, "ollama_models", lambda: ["qwen2.5:7b"])
    monkeypatch.setattr(agents, "openrouter_key", lambda: "sk-or-v1-0123456789abcdef")
    monkeypatch.setattr(agent_status, "_pulls", {"qwen2.5:14b": "downloading"})
    monkeypatch.setattr(agent_status, "_run_claude", lambda prompt, model, timeout: '{"ok": true}')


def test_agents_and_setup_match_the_schema(client, fake_agents):
    _check(client, "get", "/api/agents", "/api/agents")
    _check(client, "get", "/api/setup", "/api/setup")
    _check(client, "post", "/api/agents/claude/test", "/api/agents/{name}/test", body={})
    # a test that fails: error and seconds, no answer
    _check(client, "post", "/api/agents/codex/test", "/api/agents/{name}/test", body={"model": "x"})
    _check(client, "put", "/api/agents/openrouter/key", "/api/agents/openrouter/key", body={"key": "sk-or-v1-abc"})
    _check(client, "put", "/api/settings", "/api/settings",
           body={"agent": {"primary": "claude", "fallback": None, "models": {"claude": "opus"}}})


def test_errors_match_the_schema(client):
    _check(client, "get", "/api/videos/nope", "/api/videos/{video_id}", 404)
    _check(client, "get", "/api/videos/nope/plan", "/api/videos/{video_id}/plan", 404)
    _check(client, "put", "/api/videos/vid/thumbnail", "/api/videos/{video_id}/thumbnail", 400, body={"variant": "X"})
    _check(client, "post", "/api/edit", "/api/edit", 400, body={"type": "long"})
    _check(client, "post", "/api/videos/vid/resume", "/api/videos/{video_id}/resume", 400, body={})
    _check(client, "get", "/api/jobs/nope/events", "/api/jobs/{job_id}/events", 404)


def test_job_events_match_the_schema():
    jobs = engine.JobManager()

    def target(emit):
        emit({"type": "log", "line": "oi"})
        emit({"type": "stage", "stage": "plan"})
        emit({"type": "progress", "pct": 40})
        emit({"type": "done", "status": "done", "output": None})

    job = jobs.run_task("style", target)
    events = list(job.subscribe())
    assert [e["type"] for e in events] == ["log", "stage", "progress", "done"]
    schema = {"$ref": "#/components/schemas/JobEvent"}
    for ev in events:
        assert validate(ev, schema) == []


class TestValidator:
    """The validator above must actually catch drift."""

    def test_catches_a_missing_field_and_a_wrong_type(self):
        schema = {"$ref": "#/components/schemas/Health"}
        assert validate({"ok": True, "api_version": "1.1.0", "version": "1"}, schema) == []
        assert validate({"ok": True, "version": "1"}, schema)
        assert validate({"ok": "yes", "api_version": "1.1.0", "version": "1"}, schema)

    def test_enum_null_and_nested(self):
        schema = {"$ref": "#/components/schemas/VideoSummary"}
        bad = {"id": "x", "video_name": "x", "type": "medium", "status": "done",
               "current_stage": None, "stages": {}, "has_thumbnail": False}
        assert any("medium" in e for e in validate(bad, schema))
        assert validate({**bad, "type": "long"}, schema) == []
