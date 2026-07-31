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
  duration_sec      INTEGER,
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


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    if "duration_sec" not in cols:
        conn.execute("ALTER TABLE videos ADD COLUMN duration_sec INTEGER")
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def upsert_video(conn, platform, platform_video_id, *, title, url,
                 thumbnail_url, published_at, duration_sec=None) -> None:
    conn.execute(
        """
        INSERT INTO videos (platform, platform_video_id, title, url,
                            thumbnail_url, published_at, duration_sec, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_video_id) DO UPDATE SET
          title = excluded.title,
          url = excluded.url,
          thumbnail_url = excluded.thumbnail_url,
          published_at = excluded.published_at,
          duration_sec = COALESCE(excluded.duration_sec, videos.duration_sec)
        """,
        (platform, platform_video_id, title, url, thumbnail_url,
         published_at, duration_sec, _now()),
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
