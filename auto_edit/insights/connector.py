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
    duration_sec: int | None = None


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
