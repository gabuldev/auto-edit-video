"""User-level config dir for auto-edit (~/.auto-edit/).

Holds creator profile (freeform .md files) and generated content plans.
Lives outside the repo so personal data isn't versioned with this opensource project.
"""
from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    override = os.environ.get("AUTO_EDIT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".auto-edit"


def profile_dir() -> Path:
    return home_dir() / "profile"


def plans_dir() -> Path:
    return home_dir() / "plans"


def ideas_dir() -> Path:
    return home_dir() / "ideas"


_PROFILE_README = """# Your Creator Profile

Drop any `.md` files in this folder. Every `.md` here is loaded as context
when you run `auto-edit plan new`, so the planner knows your channel, voice,
audience, and history.

Suggested files (all optional):

- `channel_history.md` — list of videos you've already published (titles, dates, themes)
- `voice.md` — tone, language, signature phrases, things you'd never say
- `audience.md` — who watches you, what they care about
- `goals.md` — where you want the channel to go this quarter

Format is up to you — bullet lists, prose, tables. The planner reads it all.
"""

_CHANNEL_HISTORY_TEMPLATE = """# Channel History

Past videos (most recent first). Free-form — title + date + one-line theme is enough.

Example:

- **2026-04** · *Scalable Flutter: choices that save (and destroy) your app* — opinion/architecture, EN
- **2026-03** · *I landed a job abroad using Flutter* — career, EN
- **2026-03** · *Criando um Agente de IA com NestJS e Gemini Flash* — tutorial, PT
"""

_IDEAS_README = """# Content Ideas Backlog

Ideas are stored as individual YAML files. Each file represents one content idea.
Use `auto-edit ideas add "title"` to create new ideas, and `auto-edit ideas list`
to browse them. When ready, use `auto-edit ideas pick` to link an idea to a plan slot.
"""

_PLANS_README = """# Generated Plans

Monthly content plans land here as `YYYY-MM.yaml`. Edit by hand or via
`auto-edit plan edit`. Safe to version this folder in a private git repo
if you want history across machines.
"""


def ensure_dirs() -> None:
    """Create ~/.auto-edit/ scaffolding on first use. Idempotent."""
    profile_dir().mkdir(parents=True, exist_ok=True)
    plans_dir().mkdir(parents=True, exist_ok=True)
    ideas_dir().mkdir(parents=True, exist_ok=True)

    readme = profile_dir() / "README.md"
    if not readme.exists():
        readme.write_text(_PROFILE_README, encoding="utf-8")

    history = profile_dir() / "channel_history.md"
    if not history.exists():
        history.write_text(_CHANNEL_HISTORY_TEMPLATE, encoding="utf-8")

    plans_readme = plans_dir() / "README.md"
    if not plans_readme.exists():
        plans_readme.write_text(_PLANS_README, encoding="utf-8")

    ideas_readme = ideas_dir() / "README.md"
    if not ideas_readme.exists():
        ideas_readme.write_text(_IDEAS_README, encoding="utf-8")


def load_profile() -> str:
    """Concatenate every .md file in profile_dir() (except README) into one context blob."""
    ensure_dirs()
    parts: list[str] = []
    for md in sorted(profile_dir().glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        parts.append(f"## {md.stem}\n\n{md.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts).strip()


def load_recent_plans(limit: int = 3) -> list[Path]:
    """Return up to N most recent plan files (by name, descending)."""
    ensure_dirs()
    files = sorted(plans_dir().glob("*.yaml"), reverse=True)
    return files[:limit]
