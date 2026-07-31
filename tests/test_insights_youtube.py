"""Tests for auto_edit/insights/youtube.py — pure parsing only, no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights.youtube import (
    YouTubeConnector,
    _parse_uploads,
    _parse_analytics,
    _parse_duration,
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


class TestParseDuration:
    def test_minutes_seconds(self):
        assert _parse_duration("PT1M30S") == 90

    def test_seconds_only(self):
        assert _parse_duration("PT45S") == 45

    def test_hours(self):
        assert _parse_duration("PT1H2M3S") == 3723

    def test_garbage(self):
        assert _parse_duration("banana") is None


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

    def videos(self):
        class V:
            def list(inner, **kw):
                return _FakeReq({"items": [
                    {"id": "v1", "contentDetails": {"duration": "PT2M10S"}}]})
        return V()


class _FakeAnalytics:
    def reports(self):
        class R:
            def query(inner, **kw):
                # impressions/CTR não existem na API de canal — só as métricas base
                assert "impressions" not in kw.get("metrics", "")
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

    def test_list_videos_enriches_duration(self):
        c = _connector_with_fakes()
        refs = c.list_videos()
        assert refs[0].duration_sec == 130  # PT2M10S

    def test_fetch_metrics_base_only(self):
        c = _connector_with_fakes()
        pts = c.fetch_metrics(["v1"])
        p = {x.platform_video_id: x for x in pts}["v1"]
        assert p.views == 1000
        # reach/ctr não existem na API de canal — ficam None
        assert p.reach is None
        assert p.ctr is None
