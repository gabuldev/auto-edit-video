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
            ctr = b.pop("_ctr")
            avp = b.pop("_avp")
            b["ctr"] = round(sum(ctr) / len(ctr), 4) if ctr else None
            b["avg_view_pct"] = round(sum(avp) / len(avp), 2) if avp else None
            out.append(b)
        out.sort(key=lambda x: x["views"], reverse=True)
        return out[:top] if top else out
    rows.sort(key=lambda r: (r.get("views") or 0), reverse=True)
    return rows[:top] if top else rows
