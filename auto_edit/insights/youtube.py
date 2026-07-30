"""Connector YouTube: OAuth + Data API v3 + Analytics API v2."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auto_edit import config as cfg
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
# NOTE: impressions/impressionClickThroughRate NÃO existem na Analytics API de
# canal — são exclusivos do YouTube Studio (ou content owner). reach/ctr ficam
# None no YouTube; podem ser preenchidos por outra plataforma (ex: IG).

_SHORTS_RE = re.compile(r"/shorts/([A-Za-z0-9_-]+)")

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
_ANALYTICS_METRICS_STR = ",".join(_ANALYTICS_METRICS)


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
        # Analytics API rejeita end-date no futuro — usa hoje.
        end_date = date.today().isoformat()
        points: dict[str, MetricPoint] = {}
        for batch in _chunks(video_ids, 200):
            flt = "video==" + ",".join(batch)
            base = self._analytics.reports().query(
                ids="channel==MINE", startDate="2005-01-01",
                endDate=end_date, dimensions="video",
                metrics=_ANALYTICS_METRICS_STR, filters=flt,
            ).execute()
            for p in _parse_analytics(base.get("columnHeaders", []), base.get("rows", [])):
                points[p.platform_video_id] = p
        return list(points.values())


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
