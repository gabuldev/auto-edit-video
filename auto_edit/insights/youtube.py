"""Connector YouTube: OAuth + Data API v3 + Analytics API v2."""
from __future__ import annotations

import re
from datetime import date
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
# NOTE: impressions/impressionClickThroughRate NÃO existem na Analytics API de
# canal — são exclusivos do YouTube Studio (ou content owner). reach/ctr ficam
# None no YouTube; podem ser preenchidos por outra plataforma (ex: IG).

_SHORTS_RE = re.compile(r"/shorts/([A-Za-z0-9_-]+)")

_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _parse_duration(iso: str) -> int | None:
    m = _DURATION_RE.match(iso or "")
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


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

    def _credentials(self):
        # One YouTube connection for publish + insights (auto_edit.youtube_auth).
        # Interactive: `insights auth`/`sync` open the browser when needed.
        from auto_edit import youtube_auth

        try:
            return youtube_auth.credentials(interactive=True)
        except youtube_auth.AuthError as exc:
            raise RuntimeError(str(exc)) from None

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

    def _fetch_durations(self, ids: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for batch in _chunks(ids, 50):
            resp = self._data.videos().list(
                part="contentDetails", id=",".join(batch), maxResults=50,
            ).execute()
            for it in resp.get("items", []):
                dur = _parse_duration(
                    it.get("contentDetails", {}).get("duration", ""))
                if dur is not None:
                    out[it["id"]] = dur
        return out

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
        durations = self._fetch_durations([r.platform_video_id for r in refs])
        for r in refs:
            r.duration_sec = durations.get(r.platform_video_id)
        if since:
            refs = [r for r in refs if r.published_at >= since]
        return refs

    def fetch_retention(self, video_id: str) -> list[dict]:
        """The audience retention curve of one video (~100 points).

        Empty while YouTube hasn't computed it yet (first hours after
        publishing, or too few views).
        """
        self._build_services()
        resp = self._analytics.reports().query(
            ids="channel==MINE", startDate="2005-01-01", endDate=date.today().isoformat(),
            dimensions="elapsedVideoTimeRatio",
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            filters=f"video=={video_id}",
        ).execute()
        return parse_retention(resp.get("columnHeaders", []), resp.get("rows", []))

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


def parse_retention(headers: list[dict], rows: list[list]) -> list[dict]:
    """Analytics rows → [{ratio, watch, relative}] (fractions, not percents)."""
    names = [h.get("name") for h in headers]
    idx = {n: i for i, n in enumerate(names)}
    if "elapsedVideoTimeRatio" not in idx or "audienceWatchRatio" not in idx:
        return []
    out = []
    for row in rows:
        out.append({
            "ratio": row[idx["elapsedVideoTimeRatio"]],
            "watch": row[idx["audienceWatchRatio"]],
            "relative": row[idx["relativeRetentionPerformance"]] if "relativeRetentionPerformance" in idx else None,
        })
    return out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
