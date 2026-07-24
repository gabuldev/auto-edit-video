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
