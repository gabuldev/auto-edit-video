"""Tests for auto_edit/insights — config paths, store CRUD."""
from __future__ import annotations

import sqlite3 as _sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit import config as cfg
from auto_edit.insights import store as st


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


class TestDurationColumn:
    def test_migrate_adds_column_to_old_db(self, tmp_path):
        # db pré-existente SEM duration_sec
        path = tmp_path / "old.db"
        raw = _sqlite3.connect(str(path))
        raw.execute(
            "CREATE TABLE videos (platform TEXT, platform_video_id TEXT, "
            "title TEXT, url TEXT, thumbnail_url TEXT, published_at TEXT, "
            "workspace_path TEXT, template TEXT, topic TEXT, linked_at TEXT, "
            "created_at TEXT, PRIMARY KEY (platform, platform_video_id))"
        )
        raw.commit()
        raw.close()
        conn = st.connect(path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
        assert "duration_sec" in cols

    def test_upsert_stores_and_preserves_duration(self, tmp_path):
        conn = st.connect(tmp_path / "d.db")
        st.upsert_video(conn, "youtube", "v1", title="A", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=90)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 90
        # re-sync sem duração NÃO apaga
        st.upsert_video(conn, "youtube", "v1", title="A2", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=None)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 90
        # re-sync com nova duração atualiza
        st.upsert_video(conn, "youtube", "v1", title="A3", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=200)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 200
