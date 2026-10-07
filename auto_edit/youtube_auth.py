"""Uma conexão só com o YouTube, usada pelo publish e pelo insights.

Um token (`tokens/youtube.json`) com todos os escopos que o auto-edit usa:
enviar vídeo, mandar legenda, ler o canal e ler o Analytics (retenção).
Antes eram dois tokens com escopos diferentes, e cada um precisava do seu
consentimento.

App OAuth do Google em modo "Testing" emite refresh token que **expira em 7
dias**. Token vencido ou revogado não vira traceback: o arquivo é apagado e o
erro diz pra conectar de novo. Pra parar de expirar, publique o app OAuth
("In production") no Google Cloud — mesmo sem verificação.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from auto_edit import config as cfg

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # legendas (captions.insert)
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_NAME = "youtube.json"
CHANNEL_NAME = "youtube.channel.json"
# The OAuth client survives an expired token: reconnecting needs it.
CLIENT_NAME = "youtube.client.json"
# Tokens de antes da unificação: só servem pra achar o OAuth client.
LEGACY_TOKENS = ("youtube_publish.json",)


class AuthError(RuntimeError):
    """Sem conexão válida com o YouTube; a mensagem diz o que fazer."""


def token_path() -> Path:
    return cfg.tokens_dir() / TOKEN_NAME


def client_secret() -> Path | None:
    raw = os.environ.get("AUTO_EDIT_YT_CLIENT_SECRET")
    if raw and Path(raw).expanduser().is_file():
        return Path(raw).expanduser()
    return None


def client_config() -> dict | None:
    """O OAuth client pro consentimento: o JSON de AUTO_EDIT_YT_CLIENT_SECRET
    ou, sem ele, o client de um token que já existe (o mesmo app Desktop)."""
    secret = client_secret()
    if secret is not None:
        return json.loads(secret.read_text(encoding="utf-8"))
    for name in (CLIENT_NAME, TOKEN_NAME, *LEGACY_TOKENS):
        try:
            token = json.loads((cfg.tokens_dir() / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if token.get("client_id") and token.get("client_secret"):
            return {
                "installed": {
                    "client_id": token["client_id"],
                    "client_secret": token["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": token.get("token_uri") or "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
    return None


def _granted() -> set[str]:
    try:
        token = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    scopes = token.get("scopes") or []
    return set(scopes.split() if isinstance(scopes, str) else scopes)


def missing_scopes() -> list[str]:
    """Escopos que o token salvo não tem (token antigo, de antes de um recurso novo)."""
    granted = _granted()
    return [s for s in SCOPES if s not in granted]


def is_connected() -> bool:
    return token_path().exists() and not missing_scopes()


def needs_reconnect() -> bool:
    """Há um token, mas sem algum escopo que o auto-edit precisa agora."""
    return token_path().exists() and bool(missing_scopes())


def channel_title() -> str | None:
    try:
        return json.loads((cfg.tokens_dir() / CHANNEL_NAME).read_text(encoding="utf-8")).get("title")
    except (OSError, ValueError):
        return None


def _forget() -> None:
    for name in (TOKEN_NAME, CHANNEL_NAME):
        (cfg.tokens_dir() / name).unlink(missing_ok=True)


def credentials(*, interactive: bool = False):
    """Credenciais válidas, renovando o token se preciso.

    `interactive` abre o navegador pro consentimento quando falta token ou
    escopo (bloqueia até autorizar). Sem ele, isso é AuthError.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if is_connected():
        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
        if creds.valid:
            return creds
        if creds.refresh_token:  # expired, or stored without an access token
            try:
                creds.refresh(Request())
            except RefreshError:
                # 7-day expiry of Testing-mode apps, or access revoked.
                _forget()
                creds = None
                if not interactive:
                    raise AuthError(
                        "A conexão com o YouTube expirou. Conecte de novo "
                        "(no app, ou `auto-edit publish auth youtube`)."
                    ) from None
        else:
            creds = None

    if creds is None:
        if not interactive:
            if needs_reconnect():
                raise AuthError("O YouTube precisa ser reconectado pra liberar as permissões novas.")
            raise AuthError("YouTube não conectado. Conecte a conta primeiro.")
        config = client_config()
        if config is None:
            raise AuthError(
                "Falta o OAuth client do Google: no Google Cloud, habilite a YouTube Data "
                "API v3 e a YouTube Analytics API, crie um OAuth client 'Desktop app', "
                "baixe o JSON e aponte AUTO_EDIT_YT_CLIENT_SECRET pra ele."
            )
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_config(config, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)

    path = token_path()
    path.write_text(creds.to_json())
    path.chmod(0o600)
    _remember_client(creds)
    return creds


def _remember_client(creds) -> None:
    if not (getattr(creds, "client_id", None) and getattr(creds, "client_secret", None)):
        return
    path = cfg.tokens_dir() / CLIENT_NAME
    path.write_text(json.dumps({
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": getattr(creds, "token_uri", None),
    }), encoding="utf-8")
    path.chmod(0o600)


def connect() -> str | None:
    """OAuth no navegador; guarda o nome do canal e o devolve."""
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=credentials(interactive=True), cache_discovery=False)
    items = yt.channels().list(mine=True, part="snippet").execute().get("items") or []
    title = items[0]["snippet"]["title"] if items else None
    path = cfg.tokens_dir() / CHANNEL_NAME
    path.write_text(json.dumps({"title": title}), encoding="utf-8")
    path.chmod(0o600)
    for legacy in LEGACY_TOKENS:
        (cfg.tokens_dir() / legacy).unlink(missing_ok=True)
    return title


def disconnect() -> None:
    _forget()
