# Insights v1 (YouTube read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Novo módulo `auto_edit/insights/` que ingere métricas do YouTube (canal inteiro) num SQLite em `AUTO_EDIT_HOME`, com costura de plataforma pro IG futuro, link opcional workspace↔vídeo e um relatório.

**Architecture:** Pacote Typer sub-app (padrão de `plan.py`). `store.py` (SQLite), `connector.py` (contrato de plataforma + dataclasses), `youtube.py` (connector YT: OAuth + Data/Analytics API), `service.py` (sync/link/report puros), `cli.py` (comandos). Store em `AUTO_EDIT_HOME/insights.db`; tokens em `AUTO_EDIT_HOME/tokens/`.

**Tech Stack:** Python 3.11+, Typer, SQLite (stdlib), `google-auth-oauthlib` + `google-api-python-client`, pytest, ruff, rich.

## Global Constraints

- Python >= 3.11. Sem rede real em testes — connectors/clients mockados.
- Multi-plataforma na costura: `platform` em todo schema/comando; só `youtube` implementado no v1.
- Store SQLite em `AUTO_EDIT_HOME/insights.db`; segue o padrão de `content-creator/core/db.py` (schema idempotente + `_migrate`).
- Métricas normalizadas nullable + `raw_json` pro específico da plataforma. PK de `videos` = `(platform, platform_video_id)`.
- Secrets (client secret, token OAuth) **nunca** no repo; token em `AUTO_EDIT_HOME/tokens/<platform>.json` (chmod 600), dir com mode 700.
- Escopos YT: `youtube.readonly` + `yt-analytics.readonly`. Client secret via env `AUTO_EDIT_YT_CLIENT_SECRET`.
- CLI segue o padrão de `plan.py`: `insights_app = typer.Typer(...)` montado via `app.add_typer(insights_app, name="insights")` em `auto_edit/cli.py`.
- Testes: `python -m pytest tests/ -v`. Lint: `ruff check auto_edit/ tests/ --select E,F,W --ignore E501`.
- Trabalhar na branch `feat/insights-youtube-v1`. Rodar pytest via `.venv/bin/python` (o `python3` do sistema é 3.9 e quebra a coleta).

---

### Task 1: Config — caminhos do insights

**Files:**
- Modify: `auto_edit/config.py`
- Test: `tests/test_insights_store.py` (arquivo novo; começa por estes)

**Interfaces:**
- Produces: `insights_db_path() -> Path` (= `home_dir()/"insights.db"`); `tokens_dir() -> Path` (= `home_dir()/"tokens"`, criado com mode 700).

- [ ] **Step 1: Teste que falha**

Create `tests/test_insights_store.py`:

```python
"""Tests for auto_edit/insights — config paths, store CRUD."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import config as cfg


class TestConfigPaths:
    def test_insights_db_path_under_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        assert cfg.insights_db_path() == tmp_path / "insights.db"

    def test_tokens_dir_created_700(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        d = cfg.tokens_dir()
        assert d == tmp_path / "tokens"
        assert d.is_dir()
        assert (d.stat().st_mode & 0o777) == 0o700
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py -v`
Expected: FAIL — `AttributeError: module 'auto_edit.config' has no attribute 'insights_db_path'`

- [ ] **Step 3: Implementar**

Em `auto_edit/config.py`, após `ideas_dir()`:

```python
def insights_db_path() -> Path:
    return home_dir() / "insights.db"


def tokens_dir() -> Path:
    d = home_dir() / "tokens"
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/config.py tests/test_insights_store.py
git commit -m "feat: caminhos de config do insights (db + tokens)"
```

---

### Task 2: Store SQLite

**Files:**
- Create: `auto_edit/insights/__init__.py` (vazio por ora)
- Create: `auto_edit/insights/store.py`
- Test: `tests/test_insights_store.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (usa só stdlib).
- Produces:
  - `connect(db_path: Path) -> sqlite3.Connection`
  - `upsert_video(conn, platform: str, platform_video_id: str, *, title: str, url: str, thumbnail_url: str, published_at: str | None) -> None`
  - `link_video(conn, platform: str, platform_video_id: str, *, workspace_path: str, template: str | None, topic: str | None) -> bool`
  - `add_snapshot(conn, platform: str, platform_video_id: str, point: dict) -> None` — `point` tem chaves de métrica + opcional `raw` (dict).
  - `latest_snapshots(conn, platform: str | None = None) -> list[dict]`
  - `list_videos(conn, platform: str | None = None) -> list[dict]`

- [ ] **Step 1: Teste que falha**

Adicionar em `tests/test_insights_store.py`:

```python
from auto_edit.insights import store as st


def _mkconn(tmp_path):
    return st.connect(tmp_path / "insights.db")


class TestStore:
    def test_upsert_and_list(self, tmp_path):
        conn = _mkconn(tmp_path)
        st.upsert_video(conn, "youtube", "v1", title="A", url="u", thumbnail_url="t", published_at="2026-01-01")
        st.upsert_video(conn, "youtube", "v1", title="A2", url="u", thumbnail_url="t", published_at="2026-01-01")
        rows = st.list_videos(conn, "youtube")
        assert len(rows) == 1
        assert rows[0]["title"] == "A2"  # upsert atualizou

    def test_upsert_keeps_link_fields(self, tmp_path):
        conn = _mkconn(tmp_path)
        st.upsert_video(conn, "youtube", "v1", title="A", url="u", thumbnail_url="t", published_at=None)
        assert st.link_video(conn, "youtube", "v1", workspace_path="/ws", template="dev", topic="nfc") is True
        st.upsert_video(conn, "youtube", "v1", title="A2", url="u", thumbnail_url="t", published_at=None)
        row = st.list_videos(conn, "youtube")[0]
        assert row["template"] == "dev" and row["workspace_path"] == "/ws"

    def test_link_missing_video_false(self, tmp_path):
        conn = _mkconn(tmp_path)
        assert st.link_video(conn, "youtube", "nope", workspace_path="/ws", template=None, topic=None) is False

    def test_snapshots_append_and_latest(self, tmp_path):
        conn = _mkconn(tmp_path)
        st.upsert_video(conn, "youtube", "v1", title="A", url="u", thumbnail_url="t", published_at=None)
        st.add_snapshot(conn, "youtube", "v1", {"views": 10, "ctr": 0.05, "raw": {"x": 1}, "fetched_at": "2026-01-01T00:00:00"})
        st.add_snapshot(conn, "youtube", "v1", {"views": 25, "ctr": 0.07, "fetched_at": "2026-01-02T00:00:00"})
        latest = st.latest_snapshots(conn, "youtube")
        assert len(latest) == 1
        assert latest[0]["views"] == 25  # snapshot mais recente
        assert latest[0]["title"] == "A"  # joinou com videos

    def test_platform_filter(self, tmp_path):
        conn = _mkconn(tmp_path)
        st.upsert_video(conn, "youtube", "v1", title="Y", url="u", thumbnail_url="t", published_at=None)
        st.upsert_video(conn, "instagram", "v1", title="I", url="u", thumbnail_url="t", published_at=None)
        assert len(st.list_videos(conn, "youtube")) == 1
        assert len(st.list_videos(conn)) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py::TestStore -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_edit.insights'`

- [ ] **Step 3: Implementar**

Create `auto_edit/insights/__init__.py`:

```python
```
(arquivo vazio — o `insights_app` é exportado numa task posterior)

Create `auto_edit/insights/store.py`:

```python
"""SQLite store para métricas de insights (padrão de content-creator/core/db.py)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  platform          TEXT NOT NULL,
  platform_video_id TEXT NOT NULL,
  title             TEXT NOT NULL DEFAULT '',
  url               TEXT NOT NULL DEFAULT '',
  thumbnail_url     TEXT NOT NULL DEFAULT '',
  published_at      TEXT,
  workspace_path    TEXT,
  template          TEXT,
  topic             TEXT,
  linked_at         TEXT,
  created_at        TEXT NOT NULL,
  PRIMARY KEY (platform, platform_video_id)
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  platform          TEXT NOT NULL,
  platform_video_id TEXT NOT NULL,
  fetched_at        TEXT NOT NULL,
  views             INTEGER,
  reach             INTEGER,
  watch_time_min    REAL,
  avg_view_pct      REAL,
  ctr               REAL,
  likes             INTEGER,
  comments          INTEGER,
  shares            INTEGER,
  saves             INTEGER,
  followers_gained  INTEGER,
  raw_json          TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (platform, platform_video_id)
    REFERENCES videos(platform, platform_video_id)
);
"""

_METRIC_COLS = [
    "views", "reach", "watch_time_min", "avg_view_pct", "ctr",
    "likes", "comments", "shares", "saves", "followers_gained",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def upsert_video(conn, platform, platform_video_id, *, title, url,
                 thumbnail_url, published_at) -> None:
    conn.execute(
        """
        INSERT INTO videos (platform, platform_video_id, title, url,
                            thumbnail_url, published_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_video_id) DO UPDATE SET
          title = excluded.title,
          url = excluded.url,
          thumbnail_url = excluded.thumbnail_url,
          published_at = excluded.published_at
        """,
        (platform, platform_video_id, title, url, thumbnail_url,
         published_at, _now()),
    )
    conn.commit()


def link_video(conn, platform, platform_video_id, *, workspace_path,
               template, topic) -> bool:
    cur = conn.execute(
        """
        UPDATE videos SET workspace_path = ?, template = ?, topic = ?, linked_at = ?
        WHERE platform = ? AND platform_video_id = ?
        """,
        (workspace_path, template, topic, _now(), platform, platform_video_id),
    )
    conn.commit()
    return cur.rowcount > 0


def add_snapshot(conn, platform, platform_video_id, point: dict) -> None:
    raw = point.get("raw", {})
    fetched_at = point.get("fetched_at") or _now()
    cols = ["platform", "platform_video_id", "fetched_at"] + _METRIC_COLS + ["raw_json"]
    vals = [platform, platform_video_id, fetched_at]
    vals += [point.get(c) for c in _METRIC_COLS]
    vals.append(json.dumps(raw, ensure_ascii=False))
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO metric_snapshots ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "raw_json" in d:
        d["raw"] = json.loads(d.pop("raw_json"))
    return d


def list_videos(conn, platform: str | None = None) -> list[dict]:
    if platform:
        rows = conn.execute(
            "SELECT * FROM videos WHERE platform = ? ORDER BY published_at DESC",
            (platform,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM videos ORDER BY published_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def latest_snapshots(conn, platform: str | None = None) -> list[dict]:
    """Último snapshot por vídeo (maior fetched_at), joinado com videos."""
    where = "WHERE v.platform = ?" if platform else ""
    params = (platform,) if platform else ()
    rows = conn.execute(
        f"""
        SELECT v.*, s.fetched_at, s.views, s.reach, s.watch_time_min, s.avg_view_pct,
               s.ctr, s.likes, s.comments, s.shares, s.saves, s.followers_gained, s.raw_json
        FROM videos v
        JOIN metric_snapshots s
          ON s.platform = v.platform AND s.platform_video_id = v.platform_video_id
        JOIN (
          SELECT platform, platform_video_id, MAX(fetched_at) AS mx
          FROM metric_snapshots GROUP BY platform, platform_video_id
        ) latest
          ON latest.platform = s.platform
         AND latest.platform_video_id = s.platform_video_id
         AND latest.mx = s.fetched_at
        {where}
        ORDER BY s.views DESC
        """,
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Lint + Commit**

```bash
.venv/bin/ruff check auto_edit/insights/ tests/test_insights_store.py --select E,F,W --ignore E501
git add auto_edit/insights/__init__.py auto_edit/insights/store.py tests/test_insights_store.py
git commit -m "feat: store SQLite do insights (videos + metric_snapshots)"
```

---

### Task 3: Connector (contrato de plataforma)

**Files:**
- Create: `auto_edit/insights/connector.py`
- Test: `tests/test_insights_connector.py`

**Interfaces:**
- Produces:
  - dataclasses `VideoRef(platform_video_id, title, url, thumbnail_url, published_at)` e `MetricPoint(platform_video_id, views=None, reach=None, watch_time_min=None, avg_view_pct=None, ctr=None, likes=None, comments=None, shares=None, saves=None, followers_gained=None, raw=dict)`, com `MetricPoint.as_store_dict() -> dict`.
  - `Connector` (Protocol) com `platform: str`, `authenticate()`, `list_videos(since=None)`, `fetch_metrics(video_ids)`, `video_id_from_url(url) -> str | None`.
  - `PLATFORMS: list[str]` (= `["youtube"]`).
  - `get_connector(platform: str) -> Connector` (lazy import do youtube).
  - `detect_platform(url: str) -> str | None` (tenta cada connector).

- [ ] **Step 1: Teste que falha**

Create `tests/test_insights_connector.py`:

```python
"""Tests for auto_edit/insights/connector.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights import connector as cn


class TestMetricPoint:
    def test_as_store_dict_roundtrips_fields(self):
        p = cn.MetricPoint("v1", views=10, ctr=0.05, raw={"a": 1})
        d = p.as_store_dict()
        assert d["views"] == 10 and d["ctr"] == 0.05
        assert d["raw"] == {"a": 1}
        assert d["saves"] is None


class TestRegistry:
    def test_platforms_lists_youtube(self):
        assert "youtube" in cn.PLATFORMS

    def test_get_connector_youtube(self):
        c = cn.get_connector("youtube")
        assert c.platform == "youtube"

    def test_get_connector_unknown_raises(self):
        with pytest.raises(ValueError, match="youtube"):
            cn.get_connector("myspace")

    def test_detect_platform_from_youtube_url(self):
        assert cn.detect_platform("https://youtu.be/abc123") == "youtube"

    def test_detect_platform_unknown_none(self):
        assert cn.detect_platform("https://example.com/x") is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_connector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_edit.insights.connector'`

- [ ] **Step 3: Implementar**

Create `auto_edit/insights/connector.py`:

```python
"""Contrato de plataforma pro insights. YT (v1) e IG (v2) implementam o mesmo Protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

PLATFORMS: list[str] = ["youtube"]


@dataclass
class VideoRef:
    platform_video_id: str
    title: str
    url: str
    thumbnail_url: str
    published_at: str  # ISO 8601


@dataclass
class MetricPoint:
    platform_video_id: str
    views: int | None = None
    reach: int | None = None
    watch_time_min: float | None = None
    avg_view_pct: float | None = None
    ctr: float | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    followers_gained: int | None = None
    raw: dict = field(default_factory=dict)

    def as_store_dict(self) -> dict:
        return {
            "views": self.views, "reach": self.reach,
            "watch_time_min": self.watch_time_min, "avg_view_pct": self.avg_view_pct,
            "ctr": self.ctr, "likes": self.likes, "comments": self.comments,
            "shares": self.shares, "saves": self.saves,
            "followers_gained": self.followers_gained, "raw": self.raw,
        }


@runtime_checkable
class Connector(Protocol):
    platform: str

    def authenticate(self) -> None: ...
    def list_videos(self, since: str | None = None) -> list[VideoRef]: ...
    def fetch_metrics(self, video_ids: list[str]) -> list[MetricPoint]: ...
    @staticmethod
    def video_id_from_url(url: str) -> str | None: ...


def get_connector(platform: str):
    if platform == "youtube":
        from auto_edit.insights.youtube import YouTubeConnector
        return YouTubeConnector()
    raise ValueError(
        f"Plataforma desconhecida: {platform!r}. Disponíveis: {', '.join(PLATFORMS)}"
    )


def detect_platform(url: str) -> str | None:
    for platform in PLATFORMS:
        if get_connector(platform).video_id_from_url(url):
            return platform
    return None
```

> Nota: `get_connector("youtube")` importa `youtube.py`, que só existe após a Task 5. Rode os testes desta task DEPOIS da 5, OU implemente um stub mínimo de `YouTubeConnector` com `platform="youtube"` e `video_id_from_url` na Task 4 (é o que a Task 4 faz). A ordem de execução é 3 → 4 → 5, e a Task 4 já provê `video_id_from_url`, então `detect_platform`/`get_connector` funcionam ao fim da Task 4.

- [ ] **Step 4: Rodar (após Task 4 prover o stub) e ver passar**

Os testes de `TestMetricPoint`/`TestRegistry.test_platforms_lists_youtube` passam já. Os que instanciam o connector (`test_get_connector_youtube`, `detect_platform`) passam ao fim da Task 4. Rodar:
Run: `.venv/bin/python -m pytest tests/test_insights_connector.py::TestMetricPoint tests/test_insights_connector.py::TestRegistry::test_platforms_lists_youtube tests/test_insights_connector.py::TestRegistry::test_get_connector_unknown_raises -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add auto_edit/insights/connector.py tests/test_insights_connector.py
git commit -m "feat: contrato Connector + dataclasses do insights"
```

---

### Task 4: YouTube — URL + parsers (puro) + stub do connector

**Files:**
- Create: `auto_edit/insights/youtube.py`
- Test: `tests/test_insights_youtube.py`

**Interfaces:**
- Consumes: `VideoRef`, `MetricPoint` (Task 3).
- Produces: em `youtube.py`:
  - `YouTubeConnector` classe com `platform = "youtube"`, `video_id_from_url(url)` (staticmethod).
  - `_parse_uploads(items: list[dict]) -> list[VideoRef]` (playlistItems.list response items).
  - `_parse_analytics(headers: list[dict], rows: list[list]) -> list[MetricPoint]` (reports.query response).
  - Métodos `authenticate`/`list_videos`/`fetch_metrics` ficam como stubs a preencher na Task 5 (podem levantar `NotImplementedError` por ora — só os puros são testados aqui).

- [ ] **Step 1: Teste que falha**

Create `tests/test_insights_youtube.py`:

```python
"""Tests for auto_edit/insights/youtube.py — pure parsing only, no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights.youtube import (
    YouTubeConnector,
    _parse_uploads,
    _parse_analytics,
)


class TestVideoIdFromUrl:
    def test_watch(self):
        assert YouTubeConnector.video_id_from_url("https://www.youtube.com/watch?v=abc123DEF") == "abc123DEF"

    def test_short_link(self):
        assert YouTubeConnector.video_id_from_url("https://youtu.be/xyz789") == "xyz789"

    def test_shorts(self):
        assert YouTubeConnector.video_id_from_url("https://youtube.com/shorts/QW3rt-yui") == "QW3rt-yui"

    def test_not_youtube(self):
        assert YouTubeConnector.video_id_from_url("https://vimeo.com/123") is None


class TestParseUploads:
    def test_maps_items_to_videorefs(self):
        items = [{
            "contentDetails": {"videoId": "v1"},
            "snippet": {
                "title": "Meu Reel",
                "publishedAt": "2026-07-01T12:00:00Z",
                "thumbnails": {"high": {"url": "http://thumb/hi.jpg"}},
            },
        }]
        refs = _parse_uploads(items)
        assert len(refs) == 1
        assert refs[0].platform_video_id == "v1"
        assert refs[0].title == "Meu Reel"
        assert refs[0].url == "https://www.youtube.com/watch?v=v1"
        assert refs[0].thumbnail_url == "http://thumb/hi.jpg"
        assert refs[0].published_at == "2026-07-01T12:00:00Z"


class TestParseAnalytics:
    def test_maps_rows_to_metricpoints(self):
        headers = [{"name": "video"}, {"name": "views"},
                   {"name": "estimatedMinutesWatched"}, {"name": "averageViewPercentage"},
                   {"name": "subscribersGained"}]
        rows = [["v1", 1000, 250.0, 47.5, 12]]
        points = _parse_analytics(headers, rows)
        assert len(points) == 1
        p = points[0]
        assert p.platform_video_id == "v1"
        assert p.views == 1000
        assert p.watch_time_min == 250.0
        assert p.avg_view_pct == 47.5
        assert p.followers_gained == 12
        assert p.ctr is None  # ausente → None
        assert p.raw == {"views": 1000, "estimatedMinutesWatched": 250.0,
                         "averageViewPercentage": 47.5, "subscribersGained": 12}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_edit.insights.youtube'`

- [ ] **Step 3: Implementar (puros + stubs)**

Create `auto_edit/insights/youtube.py`:

```python
"""Connector YouTube: OAuth + Data API v3 + Analytics API v2."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from auto_edit.insights.connector import MetricPoint, VideoRef

# YT metric name -> nosso campo do MetricPoint
_METRIC_MAP = {
    "views": "views",
    "estimatedMinutesWatched": "watch_time_min",
    "averageViewPercentage": "avg_view_pct",
    "impressions": "reach",
    "impressionClickThroughRate": "ctr",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "subscribersGained": "followers_gained",
}

_ANALYTICS_METRICS = [
    "views", "estimatedMinutesWatched", "averageViewPercentage",
    "likes", "comments", "shares", "subscribersGained",
]
_CTR_METRICS = ["impressions", "impressionClickThroughRate"]

_SHORTS_RE = re.compile(r"/shorts/([A-Za-z0-9_-]+)")


def _parse_uploads(items: list[dict]) -> list[VideoRef]:
    refs: list[VideoRef] = []
    for it in items:
        vid = it.get("contentDetails", {}).get("videoId")
        if not vid:
            continue
        sn = it.get("snippet", {})
        thumbs = sn.get("thumbnails", {})
        thumb = (
            thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
        ).get("url", "")
        refs.append(VideoRef(
            platform_video_id=vid,
            title=sn.get("title", ""),
            url=f"https://www.youtube.com/watch?v={vid}",
            thumbnail_url=thumb,
            published_at=sn.get("publishedAt", ""),
        ))
    return refs


def _parse_analytics(headers: list[dict], rows: list[list]) -> list[MetricPoint]:
    names = [h.get("name") for h in headers]
    try:
        vid_idx = names.index("video")
    except ValueError:
        return []
    points: list[MetricPoint] = []
    for row in rows:
        kwargs: dict = {}
        raw: dict = {}
        for i, name in enumerate(names):
            if i == vid_idx or name is None:
                continue
            raw[name] = row[i]
            field = _METRIC_MAP.get(name)
            if field:
                kwargs[field] = row[i]
        points.append(MetricPoint(platform_video_id=row[vid_idx], raw=raw, **kwargs))
    return points


class YouTubeConnector:
    platform = "youtube"

    @staticmethod
    def video_id_from_url(url: str) -> str | None:
        m = _SHORTS_RE.search(url)
        if m:
            return m.group(1)
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "youtu.be" in host:
            vid = parsed.path.lstrip("/")
            return vid or None
        if "youtube.com" in host:
            q = parse_qs(parsed.query)
            if "v" in q:
                return q["v"][0]
        return None

    def authenticate(self) -> None:
        raise NotImplementedError  # Task 5

    def list_videos(self, since: str | None = None) -> list[VideoRef]:
        raise NotImplementedError  # Task 5

    def fetch_metrics(self, video_ids: list[str]) -> list[MetricPoint]:
        raise NotImplementedError  # Task 5
```

- [ ] **Step 4: Rodar e ver passar (youtube + os de connector que dependiam do stub)**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py tests/test_insights_connector.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/insights/youtube.py tests/test_insights_youtube.py
git commit -m "feat: youtube connector — parse de uploads/analytics + url"
```

---

### Task 5: YouTube — OAuth + chamadas de API (glue) + deps

**Files:**
- Modify: `auto_edit/insights/youtube.py`
- Modify: `pyproject.toml` (deps)
- Modify: `CLAUDE.md` (env var)
- Test: `tests/test_insights_youtube.py`

**Interfaces:**
- Consumes: `_parse_uploads`, `_parse_analytics` (Task 4); `config.tokens_dir` (Task 1).
- Produces: `YouTubeConnector.authenticate()`, `.list_videos(since)`, `.fetch_metrics(video_ids)` funcionais, usando um `_build_services()` injetável pra testar sem rede.

- [ ] **Step 1: Adicionar deps**

Em `pyproject.toml`, no array `dependencies`, adicionar:

```
    "google-auth-oauthlib>=1.2",
    "google-api-python-client>=2.100",
```

Instalar: `.venv/bin/python -m pip install "google-auth-oauthlib>=1.2" "google-api-python-client>=2.100"`

- [ ] **Step 2: Teste que falha (list_videos/fetch_metrics via serviços mockados)**

Adicionar em `tests/test_insights_youtube.py`:

```python
class _FakeReq:
    def __init__(self, resp):
        self._resp = resp
    def execute(self):
        return self._resp


class _FakeData:
    """Mimetiza o cliente Data API v3: channels() e playlistItems()."""
    def channels(self):
        class C:
            def list(inner, **kw):
                return _FakeReq({"items": [{"contentDetails": {
                    "relatedPlaylists": {"uploads": "UP1"}}}]})
        return C()

    def playlistItems(self):
        class P:
            def list(inner, **kw):
                return _FakeReq({"items": [{
                    "contentDetails": {"videoId": "v1"},
                    "snippet": {"title": "T", "publishedAt": "2026-07-01T00:00:00Z",
                                "thumbnails": {"high": {"url": "u"}}},
                }], "nextPageToken": None})
        return P()


class _FakeAnalytics:
    def reports(self):
        class R:
            def query(inner, **kw):
                # devolve CTR só quando pedido, senão as métricas base
                if "impressions" in kw.get("metrics", ""):
                    return _FakeReq({"columnHeaders": [{"name": "video"},
                        {"name": "impressions"}, {"name": "impressionClickThroughRate"}],
                        "rows": [["v1", 5000, 0.061]]})
                return _FakeReq({"columnHeaders": [{"name": "video"}, {"name": "views"}],
                                 "rows": [["v1", 1000]]})
        return R()


def _connector_with_fakes():
    c = YouTubeConnector()
    c._data = _FakeData()
    c._analytics = _FakeAnalytics()
    return c


class TestYouTubeApiCalls:
    def test_list_videos(self):
        c = _connector_with_fakes()
        refs = c.list_videos()
        assert [r.platform_video_id for r in refs] == ["v1"]

    def test_fetch_metrics_merges_ctr(self):
        c = _connector_with_fakes()
        pts = c.fetch_metrics(["v1"])
        p = {x.platform_video_id: x for x in pts}["v1"]
        assert p.views == 1000
        assert p.reach == 5000
        assert p.ctr == 0.061
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py::TestYouTubeApiCalls -v`
Expected: FAIL — `NotImplementedError` em `list_videos`.

- [ ] **Step 4: Implementar o glue**

Em `auto_edit/insights/youtube.py`, adicionar imports no topo:

```python
import json
import os
from pathlib import Path

from auto_edit import config as cfg
```

Adicionar constantes perto do topo:

```python
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
_ANALYTICS_METRICS_STR = ",".join(_ANALYTICS_METRICS)
_CTR_METRICS_STR = ",".join(_CTR_METRICS)
```

Substituir os 3 stubs `NotImplementedError` da classe por:

```python
    def __init__(self) -> None:
        self._data = None
        self._analytics = None

    def _token_path(self) -> Path:
        return cfg.tokens_dir() / "youtube.json"

    def _credentials(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        token_path = self._token_path()
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret = os.environ.get("AUTO_EDIT_YT_CLIENT_SECRET")
            if not secret or not Path(secret).exists():
                raise RuntimeError(
                    "AUTO_EDIT_YT_CLIENT_SECRET não aponta pra um client secret OAuth. "
                    "Crie um projeto no Google Cloud, habilite YouTube Data API v3 + "
                    "YouTube Analytics API, crie um OAuth client 'Desktop app', baixe o "
                    "JSON e aponte AUTO_EDIT_YT_CLIENT_SECRET pra ele."
                )
            flow = InstalledAppFlow.from_client_secrets_file(secret, _SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
        token_path.chmod(0o600)
        return creds

    def _build_services(self) -> None:
        if self._data is not None and self._analytics is not None:
            return
        from googleapiclient.discovery import build
        creds = self._credentials()
        self._data = build("youtube", "v3", credentials=creds, cache_discovery=False)
        self._analytics = build("youtubeAnalytics", "v2", credentials=creds,
                                cache_discovery=False)

    def authenticate(self) -> None:
        self._credentials()

    def list_videos(self, since: str | None = None) -> list[VideoRef]:
        self._build_services()
        ch = self._data.channels().list(mine=True, part="contentDetails").execute()
        uploads = (ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"])
        refs: list[VideoRef] = []
        page = None
        while True:
            resp = self._data.playlistItems().list(
                playlistId=uploads, part="contentDetails,snippet",
                maxResults=50, pageToken=page,
            ).execute()
            refs.extend(_parse_uploads(resp.get("items", [])))
            page = resp.get("nextPageToken")
            if not page:
                break
        if since:
            refs = [r for r in refs if r.published_at >= since]
        return refs

    def fetch_metrics(self, video_ids: list[str]) -> list[MetricPoint]:
        self._build_services()
        points: dict[str, MetricPoint] = {}
        for batch in _chunks(video_ids, 200):
            flt = "video==" + ",".join(batch)
            base = self._analytics.reports().query(
                ids="channel==MINE", startDate="2005-01-01",
                endDate="2100-01-01", dimensions="video",
                metrics=_ANALYTICS_METRICS_STR, filters=flt,
            ).execute()
            for p in _parse_analytics(base.get("columnHeaders", []), base.get("rows", [])):
                points[p.platform_video_id] = p
            try:
                ctr = self._analytics.reports().query(
                    ids="channel==MINE", startDate="2005-01-01",
                    endDate="2100-01-01", dimensions="video",
                    metrics=_CTR_METRICS_STR, filters=flt,
                ).execute()
                for p in _parse_analytics(ctr.get("columnHeaders", []), ctr.get("rows", [])):
                    tgt = points.get(p.platform_video_id)
                    if tgt:
                        tgt.reach = p.reach
                        tgt.ctr = p.ctr
                        tgt.raw.update(p.raw)
            except Exception:
                pass  # CTR/impressions podem não estar disponíveis — degrada pra None
        return list(points.values())
```

Adicionar o helper no fim do módulo:

```python
def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
```

- [ ] **Step 5: Documentar env var no CLAUDE.md**

Na tabela de env vars do `CLAUDE.md`, adicionar:

```
| `AUTO_EDIT_YT_CLIENT_SECRET` | — | Caminho do JSON de OAuth client (Desktop) do Google Cloud, pro `auto-edit insights auth youtube` |
```

- [ ] **Step 6: Rodar e ver passar + suíte + lint**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py -v`
Expected: PASS
Run: `.venv/bin/python -m pytest tests/ -q` (nada quebrou)
Run: `.venv/bin/ruff check auto_edit/insights/youtube.py --select E,F,W --ignore E501`

- [ ] **Step 7: Commit**

```bash
git add auto_edit/insights/youtube.py pyproject.toml CLAUDE.md tests/test_insights_youtube.py
git commit -m "feat: youtube OAuth + chamadas Data/Analytics API"
```

---

### Task 6: Service (sync / link / report)

**Files:**
- Create: `auto_edit/insights/service.py`
- Test: `tests/test_insights_service.py`

**Interfaces:**
- Consumes: `store` (Task 2), `connector` (Task 3: `VideoRef`/`MetricPoint`/`detect_platform`/`get_connector`).
- Produces:
  - dataclasses `SyncResult(videos_seen: int, snapshots_written: int)`, `LinkResult(ok: bool, message: str, platform: str | None, video_id: str | None)`, `ReportRow(dict-like)`.
  - `sync(conn, connector, since=None) -> SyncResult`
  - `link(conn, url: str, workspace_path: str) -> LinkResult`
  - `build_report(conn, platform=None, by=None, top=None) -> list[dict]`

- [ ] **Step 1: Teste que falha**

Create `tests/test_insights_service.py`:

```python
"""Tests for auto_edit/insights/service.py — sync/link/report over fakes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights import store as st
from auto_edit.insights import service as svc
from auto_edit.insights.connector import VideoRef, MetricPoint


class _FakeConnector:
    platform = "youtube"
    def authenticate(self): pass
    def list_videos(self, since=None):
        return [VideoRef("v1", "T1", "https://youtu.be/v1", "th", "2026-07-01T00:00:00Z"),
                VideoRef("v2", "T2", "https://youtu.be/v2", "th", "2026-07-02T00:00:00Z")]
    def fetch_metrics(self, ids):
        return [MetricPoint("v1", views=100, ctr=0.05), MetricPoint("v2", views=50, ctr=0.09)]
    @staticmethod
    def video_id_from_url(url):
        return url.rsplit("/", 1)[-1] if "youtu" in url else None


def _conn(tmp_path):
    return st.connect(tmp_path / "i.db")


class TestSync:
    def test_sync_writes_videos_and_snapshots(self, tmp_path):
        conn = _conn(tmp_path)
        res = svc.sync(conn, _FakeConnector())
        assert res.videos_seen == 2 and res.snapshots_written == 2
        assert len(st.latest_snapshots(conn, "youtube")) == 2


class TestLink:
    def test_link_reads_template_from_metadata(self, tmp_path, monkeypatch):
        conn = _conn(tmp_path)
        svc.sync(conn, _FakeConnector())
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "metadata.json").write_text(json.dumps({"thumbnail": {"template": "gadget"}}))
        (ws / "pipeline.json").write_text(json.dumps({"context": "review nfc"}))
        monkeypatch.setattr(svc.connector, "detect_platform", lambda u: "youtube")
        monkeypatch.setattr(svc.connector, "get_connector",
                            lambda p: _FakeConnector())
        res = svc.link(conn, "https://youtu.be/v1", str(ws))
        assert res.ok
        row = [r for r in st.list_videos(conn, "youtube") if r["platform_video_id"] == "v1"][0]
        assert row["template"] == "gadget" and row["topic"] == "review nfc"

    def test_link_unknown_url(self, tmp_path, monkeypatch):
        conn = _conn(tmp_path)
        monkeypatch.setattr(svc.connector, "detect_platform", lambda u: None)
        res = svc.link(conn, "https://example.com/x", str(tmp_path))
        assert not res.ok and "plataforma" in res.message.lower()


class TestReport:
    def test_report_by_template_aggregates_linked(self, tmp_path, monkeypatch):
        conn = _conn(tmp_path)
        svc.sync(conn, _FakeConnector())
        st.link_video(conn, "youtube", "v1", workspace_path="/a", template="dev", topic=None)
        st.link_video(conn, "youtube", "v2", workspace_path="/b", template="dev", topic=None)
        rows = svc.build_report(conn, by="template")
        dev = [r for r in rows if r["template"] == "dev"][0]
        assert dev["videos"] == 2
        assert dev["views"] == 150  # soma
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_edit.insights.service'`

- [ ] **Step 3: Implementar**

Create `auto_edit/insights/service.py`:

```python
"""Orquestração de sync/link/report — lógica pura sobre store + connector."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from auto_edit.insights import connector, store


@dataclass
class SyncResult:
    videos_seen: int
    snapshots_written: int


@dataclass
class LinkResult:
    ok: bool
    message: str
    platform: str | None = None
    video_id: str | None = None


def sync(conn, conn_obj, since: str | None = None) -> SyncResult:
    videos = conn_obj.list_videos(since=since)
    for v in videos:
        store.upsert_video(
            conn, conn_obj.platform, v.platform_video_id,
            title=v.title, url=v.url, thumbnail_url=v.thumbnail_url,
            published_at=v.published_at,
        )
    points = conn_obj.fetch_metrics([v.platform_video_id for v in videos])
    written = 0
    for p in points:
        store.add_snapshot(conn, conn_obj.platform, p.platform_video_id, p.as_store_dict())
        written += 1
    return SyncResult(videos_seen=len(videos), snapshots_written=written)


def _read_workspace_meta(workspace_path: str) -> tuple[str | None, str | None]:
    ws = Path(workspace_path)
    template = topic = None
    meta = ws / "metadata.json"
    if meta.exists():
        try:
            d = json.loads(meta.read_text())
            template = (d.get("thumbnail") or {}).get("template")
            topic = d.get("topic")
        except Exception:
            pass
    if topic is None:
        pipe = ws / "pipeline.json"
        if pipe.exists():
            try:
                topic = json.loads(pipe.read_text()).get("context")
            except Exception:
                pass
    return template, topic


def link(conn, url: str, workspace_path: str) -> LinkResult:
    platform = connector.detect_platform(url)
    if not platform:
        return LinkResult(False, "URL não bate com nenhuma plataforma conhecida.")
    video_id = connector.get_connector(platform).video_id_from_url(url)
    if not video_id:
        return LinkResult(False, "Não consegui extrair o id do vídeo da URL.", platform)
    template, topic = _read_workspace_meta(workspace_path)
    ok = store.link_video(conn, platform, video_id,
                          workspace_path=workspace_path, template=template, topic=topic)
    if not ok:
        return LinkResult(False,
                          f"Vídeo {video_id} não está no store — rode `insights sync {platform}` antes.",
                          platform, video_id)
    return LinkResult(True, f"Linkado {platform}:{video_id} (template={template}, topic={topic}).",
                      platform, video_id)


def build_report(conn, platform: str | None = None, by: str | None = None,
                 top: int | None = None) -> list[dict]:
    rows = store.latest_snapshots(conn, platform)
    if by in ("template", "topic"):
        buckets: dict[str, dict] = {}
        for r in rows:
            key = r.get(by)
            if not key:
                continue
            b = buckets.setdefault(key, {by: key, "videos": 0, "views": 0,
                                          "_ctr": [], "_avp": []})
            b["videos"] += 1
            b["views"] += r.get("views") or 0
            if r.get("ctr") is not None:
                b["_ctr"].append(r["ctr"])
            if r.get("avg_view_pct") is not None:
                b["_avp"].append(r["avg_view_pct"])
        out = []
        for b in buckets.values():
            ctr = b.pop("_ctr"); avp = b.pop("_avp")
            b["ctr"] = round(sum(ctr) / len(ctr), 4) if ctr else None
            b["avg_view_pct"] = round(sum(avp) / len(avp), 2) if avp else None
            out.append(b)
        out.sort(key=lambda x: x["views"], reverse=True)
        return out[:top] if top else out
    rows.sort(key=lambda r: (r.get("views") or 0), reverse=True)
    return rows[:top] if top else rows
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_insights_service.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add auto_edit/insights/service.py tests/test_insights_service.py
git commit -m "feat: service do insights — sync, link, report"
```

---

### Task 7: CLI + montagem no app principal

**Files:**
- Create: `auto_edit/insights/cli.py`
- Modify: `auto_edit/insights/__init__.py` (exportar `insights_app`)
- Modify: `auto_edit/cli.py` (montar sub-app)
- Test: `tests/test_insights_cli.py`

**Interfaces:**
- Consumes: `service` (Task 6), `store` (Task 2), `connector` (Task 3), `config` (Task 1).
- Produces: `insights_app` (Typer) com comandos `auth`, `sync`, `link`, `report`; montado em `app.add_typer(insights_app, name="insights")`.

- [ ] **Step 1: Teste que falha**

Create `tests/test_insights_cli.py`:

```python
"""Tests for auto_edit/insights/cli.py — arg parsing / error paths via CliRunner."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights.cli import insights_app

runner = CliRunner()


class TestInsightsCli:
    def test_report_empty_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        result = runner.invoke(insights_app, ["report"])
        assert result.exit_code == 0

    def test_sync_unknown_platform_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        result = runner.invoke(insights_app, ["sync", "myspace"])
        assert result.exit_code != 0
        assert "myspace" in result.output or "desconhecida" in result.output.lower()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_edit.insights.cli'`

- [ ] **Step 3: Implementar CLI**

Create `auto_edit/insights/cli.py`:

```python
"""Comandos `auto-edit insights` — auth / sync / link / report."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from auto_edit import config as cfg
from auto_edit.insights import connector, service, store

insights_app = typer.Typer(
    name="insights",
    help="Ingestão de métricas das redes (YouTube). Read-only.",
    no_args_is_help=True,
)
console = Console()


def _open():
    return store.connect(cfg.insights_db_path())


@insights_app.command()
def auth(platform: str = typer.Argument("youtube")) -> None:
    """Autentica numa plataforma (OAuth) e guarda o token."""
    try:
        c = connector.get_connector(platform)
        c.authenticate()
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Autenticado em {platform}.[/green]")


@insights_app.command()
def sync(platform: str = typer.Argument("youtube"),
         since: str = typer.Option(None, "--since", help="ISO date YYYY-MM-DD")) -> None:
    """Puxa uploads + métricas do canal e grava no store."""
    try:
        c = connector.get_connector(platform)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    conn = _open()
    res = service.sync(conn, c, since=since)
    console.print(f"[green]{res.videos_seen} vídeos, {res.snapshots_written} snapshots.[/green]")


@insights_app.command()
def link(workspace_or_video: str = typer.Argument(...),
         url: str = typer.Argument(...)) -> None:
    """Linka um vídeo publicado ao workspace (marca template/topic)."""
    conn = _open()
    res = service.link(conn, url, workspace_or_video)
    color = "green" if res.ok else "red"
    console.print(f"[{color}]{res.message}[/{color}]")
    if not res.ok:
        raise typer.Exit(1)


@insights_app.command()
def report(platform: str = typer.Option(None, "-p", "--platform"),
           by: str = typer.Option(None, "--by", help="template|topic"),
           top: int = typer.Option(None, "--top")) -> None:
    """Mostra a performance (tabela)."""
    conn = _open()
    rows = service.build_report(conn, platform=platform, by=by, top=top)
    if not rows:
        console.print("[yellow]Sem dados. Rode `auto-edit insights sync` primeiro.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    if by in ("template", "topic"):
        table.add_column(by)
        for col in ("videos", "views", "ctr", "avg_view_pct"):
            table.add_column(col)
        for r in rows:
            table.add_row(str(r.get(by)), str(r.get("videos")), str(r.get("views")),
                          str(r.get("ctr")), str(r.get("avg_view_pct")))
    else:
        for col in ("title", "views", "watch_time_min", "avg_view_pct", "ctr", "likes"):
            table.add_column(col)
        for r in rows:
            table.add_row(str(r.get("title"))[:40], str(r.get("views")),
                          str(r.get("watch_time_min")), str(r.get("avg_view_pct")),
                          str(r.get("ctr")), str(r.get("likes")))
    console.print(table)
```

- [ ] **Step 4: Exportar e montar**

Substituir `auto_edit/insights/__init__.py` por:

```python
from auto_edit.insights.cli import insights_app

__all__ = ["insights_app"]
```

Em `auto_edit/cli.py`, adicionar o import junto aos outros sub-apps (perto da linha 21 `from auto_edit.plan import plan_app`):

```python
from auto_edit.insights import insights_app
```

E logo após `app.add_typer(ideas_app, name="ideas")` (linha ~39):

```python
app.add_typer(insights_app, name="insights")
```

- [ ] **Step 5: Rodar e ver passar + suíte + lint**

Run: `.venv/bin/python -m pytest tests/test_insights_cli.py -v`
Expected: PASS
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: tudo verde
Run: `.venv/bin/ruff check auto_edit/ tests/ --select E,F,W --ignore E501`
Expected: sem erros
Run: `.venv/bin/auto-edit insights --help` (confirma que montou)

- [ ] **Step 6: Commit**

```bash
git add auto_edit/insights/cli.py auto_edit/insights/__init__.py auto_edit/cli.py tests/test_insights_cli.py
git commit -m "feat: comandos auto-edit insights (auth/sync/link/report)"
```

---

## Self-Review

**Spec coverage:**
- §3 store → Task 2. ✓
- §4 connector/dataclasses/registry → Task 3. ✓
- §5 youtube (url, parse, OAuth, API) → Tasks 4 (puro) + 5 (glue). ✓
- §6 service (sync/link/report) → Task 6. ✓
- §7 CLI comandos → Task 7. ✓
- §8 config/deps/secrets → Task 1 (config), Task 5 (deps + CLAUDE.md env). ✓
- §9 testes → cada task tem testes; sem rede real (fakes/mocks). ✓
- Costura multi-plataforma (`platform` em tudo) → Tasks 2,3,6,7. ✓

**Placeholder scan:** Sem TBD/TODO. Todo step tem código/comando concreto. A ordem 3→4→5 é explícita (Task 3 nota que `get_connector` depende do stub da Task 4). ✓

**Type consistency:** `VideoRef`/`MetricPoint` definidos na Task 3, usados em 4/5/6. `sync(conn, conn_obj)` recebe um objeto com a interface `Connector`. `store.add_snapshot(point)` recebe `MetricPoint.as_store_dict()`. `build_report` retorna list[dict] consumida pela CLI. `latest_snapshots` faz o join videos+snapshot usado por `build_report` e pelo report por-vídeo. ✓

**Nota de execução:** rodar TODOS os pytest via `.venv/bin/python` (3.13); `python3` do sistema é 3.9 e quebra a coleta.
```
