"""User settings (`~/.auto-edit/settings.json`), read by the CLI, the engine
and the desktop app.

Precedence, highest first: what a request/command passes explicitly, then
environment variables (so scripts and CI keep working as before), then this
file, then the defaults below. Settings never override a variable that is
already set — they fill the gaps.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from auto_edit import agents
from auto_edit import config as cfg

FILE_NAME = "settings.json"
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large")

DEFAULTS: dict = {
    "agent": {
        "primary": "claude",
        "fallback": None,
        "models": {name: None for name in agents.AGENTS},
    },
    "language": "pt",
    "whisper_model": "small",
    "inbox": None,
    "overlays_dir": None,
    "cold_open": True,
    "reorder": True,
}

# Setting → environment variable it stands for.
ENV = {
    ("agent", "primary"): "AUTO_EDIT_LLM",
    ("agent", "fallback"): "AUTO_EDIT_LLM_FALLBACK",
    ("language",): "AUTO_EDIT_LANGUAGE",
    ("inbox",): "AUTO_EDIT_INBOX",
    ("overlays_dir",): "AUTO_EDIT_ASSETS_OVERLAYS",
}


class SettingsError(ValueError):
    pass


def path() -> Path:
    return cfg.home_dir() / FILE_NAME


def _merge(base: dict, extra: dict) -> dict:
    out = deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    """Defaults + what was saved (a broken file reads as just the defaults)."""
    try:
        saved = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return _merge(DEFAULTS, saved if isinstance(saved, dict) else {})


def validate(data: dict) -> dict:
    """The full settings after a partial update, or SettingsError."""
    merged = _merge(load(), data or {})
    agent = merged["agent"]
    primary = agents.normalize(agent.get("primary") or "")
    if primary is None:
        raise SettingsError(f"agente principal desconhecido: {agent.get('primary')!r}")
    agent["primary"] = primary
    if agent.get("fallback"):
        fallback = agents.normalize(agent["fallback"])
        if fallback is None:
            raise SettingsError(f"agente de fallback desconhecido: {agent['fallback']!r}")
        agent["fallback"] = None if fallback == primary else fallback
    else:
        agent["fallback"] = None
    agent["models"] = {
        name: ((agent.get("models") or {}).get(name) or None) for name in agents.AGENTS
    }
    if merged["whisper_model"] not in WHISPER_MODELS:
        raise SettingsError(f"modelo do Whisper inválido: {merged['whisper_model']!r}")
    for key in ("inbox", "overlays_dir"):
        value = merged.get(key)
        if value:
            p = Path(value).expanduser()
            if not p.is_dir():
                raise SettingsError(f"pasta não existe: {value}")
            merged[key] = str(p)
        else:
            merged[key] = None
    merged["cold_open"] = bool(merged["cold_open"])
    merged["reorder"] = bool(merged["reorder"])
    merged["language"] = (merged.get("language") or "pt").strip() or "pt"
    return merged


def save(data: dict) -> dict:
    merged = validate(data)
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


def _get(data: dict, keys: tuple) -> object:
    for k in keys:
        data = data.get(k) if isinstance(data, dict) else None
    return data


def env_from_settings(base: dict | None = None) -> dict:
    """`base` (default: os.environ) with the gaps filled from settings.

    Variables already set win; agent models fill AUTO_EDIT_<AGENT>_MODEL.
    """
    env = dict(os.environ if base is None else base)
    data = load()
    for keys, var in ENV.items():
        value = _get(data, keys)
        if value and not env.get(var):
            env[var] = str(value)
    for name, agent in agents.AGENTS.items():
        model = (data["agent"].get("models") or {}).get(name)
        if model and not env.get(agent.model_env):
            env[agent.model_env] = model
    return env


def apply_to_process() -> None:
    """Fill os.environ from settings (CLI and engine start-up)."""
    os.environ.update({k: v for k, v in env_from_settings().items() if k not in os.environ})
