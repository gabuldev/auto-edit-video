"""One YouTube connection for publish + insights: scopes, legacy tokens, the
OAuth client surviving an expired token, and expiry turning into "reconnect"."""
import json

import pytest

from auto_edit import config as cfg
from auto_edit import youtube_auth as ya


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
    monkeypatch.delenv("AUTO_EDIT_YT_CLIENT_SECRET", raising=False)
    return tmp_path


def _token(scopes, name=ya.TOKEN_NAME):
    (cfg.tokens_dir() / name).write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "cid", "client_secret": "cs",
        "token_uri": "https://oauth2.googleapis.com/token", "scopes": scopes,
    }), encoding="utf-8")


def test_full_token_is_connected(home):
    _token(ya.SCOPES)
    assert ya.is_connected() and not ya.needs_reconnect() and ya.missing_scopes() == []


def test_old_readonly_token_needs_reconnect(home):
    """The insights token from before: no upload, no captions."""
    _token(["https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly"])
    assert not ya.is_connected()
    assert ya.needs_reconnect()
    assert "https://www.googleapis.com/auth/youtube.upload" in ya.missing_scopes()


def test_no_token(home):
    assert not ya.is_connected() and not ya.needs_reconnect()
    with pytest.raises(ya.AuthError, match="não conectado"):
        ya.credentials()


def test_partial_token_without_browser_says_reconnect(home):
    _token(["https://www.googleapis.com/auth/youtube.readonly"])
    with pytest.raises(ya.AuthError, match="reconectado"):
        ya.credentials()


def test_client_config_from_legacy_publish_token(home):
    _token(["x"], name="youtube_publish.json")
    assert ya.client_config()["installed"]["client_id"] == "cid"


def test_client_survives_an_expired_token(home, monkeypatch):
    """Testing-mode apps: refresh tokens die after 7 days. The token goes, the
    client stays, so reconnecting works without downloading the JSON again."""
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    _token(ya.SCOPES)
    ya._remember_client(Credentials(token="t", client_id="cid", client_secret="cs", token_uri="u"))

    def expired(*a, **k):
        creds = Credentials(token=None, refresh_token="r", client_id="cid", client_secret="cs",
                            token_uri="https://oauth2.googleapis.com/token", scopes=ya.SCOPES)

        def boom(request):
            raise RefreshError("invalid_grant")
        creds.refresh = boom
        return creds

    monkeypatch.setattr(Credentials, "from_authorized_user_file", staticmethod(expired))
    with pytest.raises(ya.AuthError, match="expirou"):
        ya.credentials()
    assert not ya.token_path().exists()
    assert ya.client_config()["installed"]["client_secret"] == "cs"


def test_env_client_secret_wins(home, tmp_path, monkeypatch):
    secret = tmp_path / "cs.json"
    secret.write_text(json.dumps({"installed": {"client_id": "env"}}), encoding="utf-8")
    monkeypatch.setenv("AUTO_EDIT_YT_CLIENT_SECRET", str(secret))
    _token(ya.SCOPES)
    assert ya.client_config()["installed"]["client_id"] == "env"


def test_disconnect_keeps_the_client(home):
    _token(ya.SCOPES)
    (cfg.tokens_dir() / ya.CLIENT_NAME).write_text(json.dumps({"client_id": "cid", "client_secret": "cs"}), encoding="utf-8")
    ya.disconnect()
    assert not ya.token_path().exists()
    assert ya.client_config() is not None
