"""Import the CTR the YouTube Studio exports (Analytics → Advanced mode →
Export → "Table data.csv"), which the Analytics API does not give a channel:
impressions and impressions click-through rate are Studio-only (see
youtube.py). The rest of the metrics stay as the API sync left them.

Headers come in the Studio's language; matching is by keyword (English or
Portuguese, accents ignored), so a renamed or reordered column still lands.
The "Total" row and rows without a video id are skipped.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from auto_edit.insights import store

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class StudioCsvError(ValueError):
    pass


@dataclass
class CtrRow:
    video_id: str
    title: str = ""
    published_at: str | None = None
    impressions: int | None = None
    ctr: float | None = None  # percent, as the Studio shows it (4.5 = 4,5%)
    views: int | None = None
    avg_view_pct: float | None = None
    watch_time_min: float | None = None


@dataclass
class ImportResult:
    rows: int
    new_videos: int
    skipped: int


def _plain(text: str) -> str:
    flat = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(c for c in flat if unicodedata.category(c) != "Mn")


def _column(header: str) -> str | None:
    """Which field a Studio header is."""
    h = _plain(header)
    if "click-through" in h or "taxa de cliques" in h or h.startswith("ctr"):
        return "ctr"
    if "impress" in h:
        return "impressions"
    if h in ("content", "conteudo", "video", "video id", "id do video"):
        return "video_id"
    if "title" in h or "titulo" in h:
        return "title"
    if "publish" in h or "publicacao" in h:
        return "published_at"
    if "percentage viewed" in h or "porcentagem media" in h or "percentual medio" in h:
        return "avg_view_pct"
    if "watch time" in h or "tempo de exibicao" in h:
        return "watch_time_min"
    if h in ("views", "visualizacoes"):
        return "views"
    return None


def _number(raw: str) -> float | None:
    """'4.56', '4,56', '1,234', '1.234,5', '12 %' → float; '' → None."""
    s = (raw or "").strip().replace("%", "").replace(" ", "").replace(" ", "")
    if not s or s in ("-", "—"):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse(text: str) -> list[CtrRow]:
    """The video rows of a Studio CSV export (as text)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise StudioCsvError("CSV vazio") from exc
    cols = {i: _column(h) for i, h in enumerate(header)}
    if "video_id" not in cols.values():
        raise StudioCsvError("o CSV não tem a coluna do vídeo (Content / Conteúdo)")
    if "ctr" not in cols.values():
        raise StudioCsvError("o CSV não tem a coluna de CTR (Impressions click-through rate / "
                             "Taxa de cliques de impressões) — inclua essa métrica no export")
    rows: list[CtrRow] = []
    for line in reader:
        data = {cols[i]: v for i, v in enumerate(line) if cols.get(i)}
        vid = (data.get("video_id") or "").strip()
        if not VIDEO_ID.match(vid):
            continue  # the "Total" row, blank lines
        impressions = _number(data.get("impressions", ""))
        views = _number(data.get("views", ""))
        watch_h = _number(data.get("watch_time_min", ""))
        rows.append(CtrRow(
            video_id=vid,
            title=(data.get("title") or "").strip(),
            published_at=(data.get("published_at") or "").strip() or None,
            impressions=int(impressions) if impressions is not None else None,
            ctr=_number(data.get("ctr", "")),
            views=int(views) if views is not None else None,
            avg_view_pct=_number(data.get("avg_view_pct", "")),
            watch_time_min=watch_h * 60 if watch_h is not None else None,
        ))
    return rows


def _latest(conn, video_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM metric_snapshots WHERE platform = 'youtube' AND platform_video_id = ? "
        "ORDER BY fetched_at DESC, id DESC LIMIT 1", (video_id,),
    ).fetchone()
    return dict(row) if row else None


def import_rows(conn, rows: list[CtrRow], source: str = "") -> ImportResult:
    """One snapshot per video: CTR and impressions from the CSV, the other
    metrics carried over from the latest snapshot (the API's lifetime numbers
    beat the CSV's, which cover only the exported period) — the CSV only fills
    a metric the store doesn't have yet."""
    known = {v["platform_video_id"] for v in store.list_videos(conn, "youtube")}
    new = skipped = 0
    for r in rows:
        if r.ctr is None and r.impressions is None:
            skipped += 1
            continue
        if r.video_id not in known:
            store.upsert_video(conn, "youtube", r.video_id, title=r.title,
                               url=f"https://youtu.be/{r.video_id}", thumbnail_url="",
                               published_at=r.published_at)
            known.add(r.video_id)
            new += 1
        prev = _latest(conn, r.video_id) or {}
        point = {c: prev.get(c) for c in store._METRIC_COLS}
        point["ctr"] = r.ctr
        point["reach"] = r.impressions
        for field in ("views", "avg_view_pct", "watch_time_min"):
            if point.get(field) is None:
                point[field] = getattr(r, field)
        point["raw"] = {"source": "studio_csv", "file": source,
                        "impressions": r.impressions, "ctr_pct": r.ctr}
        store.add_snapshot(conn, "youtube", r.video_id, point)
    return ImportResult(rows=len(rows) - skipped, new_videos=new, skipped=skipped)


def import_file(conn, path: Path) -> ImportResult:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = Path(path).read_text(encoding="latin-1")
    return import_rows(conn, parse(text), source=Path(path).name)
