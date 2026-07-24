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
