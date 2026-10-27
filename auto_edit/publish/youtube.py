"""Publicar no YouTube: upload resumível do vídeo final + thumbnail.

A conexão com o YouTube é a mesma do `auto-edit insights`
(`auto_edit.youtube_auth`): um token, todos os escopos. O client secret OAuth
fica fora do repo (`AUTO_EDIT_YT_CLIENT_SECRET`).

Projeto do Google Cloud sem auditoria: o YouTube trava como privado todo vídeo
enviado pela API. Funciona, mas a publicação final é no Studio.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from auto_edit import youtube_auth
from auto_edit.chapters import description_with_chapters

SCOPES = youtube_auth.SCOPES

PRIVACY = ("private", "unlisted", "public")
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX_CHARS = 500
THUMB_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_CATEGORY = "28"  # Ciência e tecnologia
UPLOAD_CHUNK = 8 * 1024 * 1024

RECORD_NAME = "publish.json"


class PublishError(RuntimeError):
    """Erro de publicação mostrado pro usuário como está."""


# ── Defaults a partir do metadata ─────────────────────────────────────────────


def _hashtag(tag: str) -> str:
    return "#" + re.sub(r"\s+", "", tag.lstrip("#"))


def defaults(pipeline: dict, metadata: dict | None) -> dict:
    """Título, descrição e tags que o stage `metadata` já gerou.

    Long tem `youtube_title`/`youtube_description`/`tags`. Short tem
    `short_title`/`hook`/`hashtags`: a descrição vira o gancho + hashtags.
    """
    m = metadata or {}
    if pipeline.get("type") == "short":
        hashtags = [h for h in (m.get("hashtags") or []) if str(h).strip()]
        lines = [m.get("hook") or ""]
        if hashtags:
            lines.append(" ".join(_hashtag(str(h)) for h in hashtags))
        return {
            "title": (m.get("short_title") or "").strip(),
            "description": "\n\n".join(x for x in lines if x).strip(),
            "tags": [str(h).lstrip("#") for h in hashtags],
        }
    return {
        "title": (m.get("youtube_title") or "").strip(),
        "description": description_with_chapters(
            m.get("youtube_description") or "", m.get("chapters") or []
        ).strip(),
        "tags": [str(t) for t in (m.get("tags") or [])],
    }


def clean_tags(tags: list[str]) -> list[str]:
    """Sem '#', sem repetidas, e dentro do limite de 500 caracteres do YouTube
    (que conta a vírgula entre tags e as aspas de uma tag com espaço)."""
    out: list[str] = []
    seen: set[str] = set()
    used = 0
    for raw in tags:
        tag = str(raw).strip().lstrip("#").strip()
        if not tag or tag.lower() in seen:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + (1 if out else 0)
        if used + cost > TAGS_MAX_CHARS:
            break
        out.append(tag)
        seen.add(tag.lower())
        used += cost
    return out


def build_body(
    *,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    publish_at: str | None = None,
    language: str | None = None,
    category: str | None = None,
) -> dict:
    """O `body` do videos.insert, validado com as regras do YouTube."""
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        raise PublishError("o título está vazio")
    if len(title) > TITLE_MAX:
        raise PublishError(f"o título passa de {TITLE_MAX} caracteres ({len(title)})")
    if len(description.encode("utf-8")) > DESCRIPTION_MAX:
        raise PublishError(f"a descrição passa de {DESCRIPTION_MAX} bytes")
    for field, text in (("título", title), ("descrição", description)):
        if "<" in text or ">" in text:
            raise PublishError(f"o YouTube não aceita '<' nem '>' no {field}")
    if privacy not in PRIVACY:
        raise PublishError(f"visibilidade inválida: {privacy}")

    status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        # A API só agenda vídeo privado: ele vira público na hora marcada.
        when = _parse_when(publish_at)
        if when <= datetime.now(timezone.utc):
            raise PublishError("a data de agendamento já passou")
        status["privacyStatus"] = "private"
        status["publishAt"] = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    snippet: dict = {
        "title": title,
        "description": description,
        "tags": clean_tags(tags),
        "categoryId": category or os.environ.get("AUTO_EDIT_YT_CATEGORY", DEFAULT_CATEGORY),
    }
    if language:
        snippet["defaultLanguage"] = language
        snippet["defaultAudioLanguage"] = language
    return {"snippet": snippet, "status": status}


def _parse_when(value: str) -> datetime:
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PublishError(f"data de agendamento inválida: {value}") from None
    if when.tzinfo is None:
        raise PublishError("a data de agendamento precisa de fuso horário")
    return when.astimezone(timezone.utc)


# ── OAuth (shared with insights: auto_edit.youtube_auth) ─────────────────────

AuthError = youtube_auth.AuthError
token_path = youtube_auth.token_path
client_secret = youtube_auth.client_secret
client_config = youtube_auth.client_config
client_id = youtube_auth.client_id
save_client = youtube_auth.save_client
is_connected = youtube_auth.is_connected
needs_reconnect = youtube_auth.needs_reconnect
channel_title = youtube_auth.channel_title
disconnect = youtube_auth.disconnect
cancel_consent = youtube_auth.cancel_consent
consent_cancelled = youtube_auth.consent_cancelled


def credentials(*, interactive: bool = False):
    try:
        return youtube_auth.credentials(interactive=interactive)
    except youtube_auth.AuthError as exc:
        raise PublishError(str(exc)) from None


def connect() -> str | None:
    try:
        return youtube_auth.connect()
    except youtube_auth.AuthError as exc:
        raise PublishError(str(exc)) from None


def _service(creds=None):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds or credentials(), cache_discovery=False)


# ── Upload ────────────────────────────────────────────────────────────────────


def prepare_thumbnail(path: Path, workdir: Path) -> Path:
    """O YouTube recusa thumbnail acima de 2 MB: converte pra JPEG se passar."""
    if path.stat().st_size <= THUMB_MAX_BYTES:
        return path
    from PIL import Image

    out = workdir / "thumbnail_youtube.jpg"
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        for quality in (90, 80, 70, 60):
            rgb.save(out, "JPEG", quality=quality, optimize=True)
            if out.stat().st_size <= THUMB_MAX_BYTES:
                return out
    raise PublishError("a thumbnail não coube em 2 MB nem como JPEG")


def upload(
    video: Path,
    body: dict,
    *,
    thumbnail: Path | None = None,
    captions: Path | None = None,
    language: str | None = None,
    comment: str | None = None,
    on_progress: Callable[[float], None] = lambda pct: None,
    service=None,
) -> dict:
    """Envia o vídeo (upload resumível em pedaços) e, se houver, a thumbnail,
    a legenda (.srt, no idioma do vídeo) e o comentário pra fixar.

    Devolve {"video_id", "url", "warnings", "captions", "comment_id"}. Nada
    depois do vídeo desfaz o upload: thumbnail, legenda ou comentário recusado
    vira aviso (canal sem verificação por telefone não pode usar thumbnail
    personalizada; vídeo privado não aceita comentário).
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = service or _service()
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=UPLOAD_CHUNK, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status is not None:
                on_progress(status.progress())
    except HttpError as exc:
        raise PublishError(f"o YouTube recusou o upload: {_reason(exc)}") from None
    on_progress(1.0)

    video_id = response["id"]
    warnings: list[str] = []
    if thumbnail is not None:
        try:
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail), resumable=False),
            ).execute()
        except HttpError as exc:
            warnings.append(f"thumbnail não enviada: {_reason(exc)}")

    captions_sent = False
    if captions is not None:
        try:
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": language or "pt", "name": "", "isDraft": False}},
                media_body=MediaFileUpload(str(captions), mimetype="application/octet-stream", resumable=False),
            ).execute()
            captions_sent = True
        except HttpError as exc:
            warnings.append(f"legenda não enviada: {_reason(exc)}")

    comment_id = None
    if comment:
        try:
            resp = yt.commentThreads().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": comment}}}},
            ).execute()
            comment_id = resp.get("id")
        except HttpError as exc:
            warnings.append(
                f"comentário não postado: {_reason(exc)} (vídeo privado não aceita comentário — poste e fixe pelo Studio)"
            )
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "warnings": warnings,
        "captions": captions_sent,
        "comment_id": comment_id,
    }


def live_status(video_ids: list[str], *, service=None) -> dict[str, dict]:
    """Como os vídeos já enviados estão agora no YouTube: um programado vira
    público sozinho, e projeto sem auditoria trava o vídeo como privado.
    {id: {privacy, publish_at, upload_status}}; vídeo apagado não vem."""
    if not video_ids:
        return {}
    yt = service or _service()
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):  # the API takes 50 ids per call
        resp = yt.videos().list(part="status", id=",".join(video_ids[i:i + 50]), maxResults=50).execute()
        for item in resp.get("items") or []:
            st = item.get("status") or {}
            out[item["id"]] = {
                "privacy": st.get("privacyStatus"),
                "publish_at": st.get("publishAt"),
                "upload_status": st.get("uploadStatus"),
            }
    return out


def _reason(exc) -> str:
    try:
        err = json.loads(exc.content.decode("utf-8"))["error"]
        return err.get("message") or str(exc)
    except Exception:  # noqa: BLE001 - a mensagem crua ainda serve
        return str(exc)


# ── Registro no workspace ─────────────────────────────────────────────────────


def read_record(ws: Path) -> dict:
    try:
        data = json.loads((ws / RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# An upload finishing and a check of what's still on YouTube both rewrite
# publish.json: one at a time, or one would drop the other's change.
_record_lock = threading.Lock()


def _write_record(ws: Path, data: dict) -> None:
    (ws / RECORD_NAME).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_record(ws: Path, platform: str, entry: dict) -> dict:
    """Acrescenta uma publicação ao `publish.json` do workspace (histórico)."""
    with _record_lock:
        data = read_record(ws)
        data.setdefault(platform, []).append(
            {**entry, "published_at": datetime.now(timezone.utc).isoformat()}
        )
        _write_record(ws, data)
    return data


def on_youtube(entries: list[dict]) -> list[dict]:
    """Os envios que ainda estão no YouTube (sem a marca de `mark_gone`)."""
    return [e for e in entries if e.get("video_id") and not e.get("removed")]


def mark_gone(ws: Path, asked: set[str], found: set[str]) -> bool:
    """Grava no publish.json quais envios sumiram do YouTube (apagados lá):
    perguntados (`asked`) e não encontrados (`found`). Um que volta a aparecer
    (outra conta conectada antes, por exemplo) perde a marca. True se mudou."""
    with _record_lock:
        data = read_record(ws)
        changed = False
        for entry in data.get("youtube", []):
            vid = entry.get("video_id")
            if vid not in asked:
                continue
            gone = vid not in found
            if bool(entry.get("removed")) == gone:
                continue
            if gone:
                entry["removed"] = True
                entry["removed_at"] = datetime.now(timezone.utc).isoformat()
            else:
                entry.pop("removed", None)
                entry.pop("removed_at", None)
            changed = True
        if changed:
            _write_record(ws, data)
    return changed
