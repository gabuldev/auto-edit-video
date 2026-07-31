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


class TestDeriveKind:
    def test_short_and_long(self):
        assert svc._derive_kind(60) == "short"
        assert svc._derive_kind(180) == "short"
        assert svc._derive_kind(181) == "long"
        assert svc._derive_kind(None) is None


class TestPerformanceBrief:
    def _seed(self, conn, vid, dur, ret, views):
        st.upsert_video(conn, "youtube", vid, title=f"T{vid}", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=dur)
        st.add_snapshot(conn, "youtube", vid,
                        {"avg_view_pct": ret, "views": views})

    def test_filters_by_kind_and_orders(self, tmp_path):
        conn = st.connect(tmp_path / "b.db")
        # 3 shorts + 1 long
        self._seed(conn, "s1", 30, 80.0, 100)
        self._seed(conn, "s2", 40, 50.0, 200)
        self._seed(conn, "s3", 50, 65.0, 150)
        self._seed(conn, "l1", 600, 40.0, 999)
        brief = svc.performance_brief(conn, kind="short", top=2, bottom=1)
        assert "T s1" not in brief  # título é "Ts1"
        assert "Ts1" in brief and "Ts2" in brief  # melhor e pior entram
        assert "Tl1" not in brief  # long fica de fora
        # melhor retenção (s1, 80%) aparece antes do pior (s2, 50%)
        assert brief.index("Ts1") < brief.index("Ts2")

    def test_empty_when_small_sample(self, tmp_path):
        conn = st.connect(tmp_path / "s.db")
        self._seed(conn, "s1", 30, 80.0, 100)
        self._seed(conn, "s2", 40, 50.0, 200)  # só 2 shorts (< 3)
        assert svc.performance_brief(conn, kind="short") == ""

    def test_ignores_rows_without_metrics(self, tmp_path):
        conn = st.connect(tmp_path / "n.db")
        # vídeo sem snapshot / sem duração não entra
        st.upsert_video(conn, "youtube", "x", title="X", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=None)
        assert svc.performance_brief(conn, kind="short") == ""
