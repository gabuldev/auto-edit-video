"""Access to the engine from other devices on the local network (#145).

Off by default. When on, a second listener (default port 8761, all
interfaces) serves the same API over TLS, and every request there needs a
device token: ``Authorization: Bearer <token>``. The localhost listener (8760,
what the desktop app and the CLI use) is untouched and needs no token.

- **TLS**: a self-signed certificate made on first use (``~/.auto-edit/lan``).
  No CA vouches for it, so the phone pins its SHA-256 fingerprint, which comes
  in the pairing QR code.
- **Pairing**: the desktop asks for a pairing (``POST /api/lan/pairing``, only
  from this machine) and shows the QR: address, port, a one-time code (5 min)
  and the fingerprint. The phone sends the code to ``POST /api/pair`` (the one
  route the LAN listener serves without a token) and gets its own token.
- **Devices**: saved with the token's SHA-256 only, never the token. Revoking
  one deletes it; its next request gets 401.
- **mDNS**: announced as ``_autoedit._tcp.local.`` (with the fingerprint) when
  ``zeroconf`` is installed, so the phone finds the computer without typing
  an IP. Without it everything else works.

The management routes (``/api/lan*``) answer only on localhost: a paired
phone can't pair more devices or revoke others.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from auto_edit import config as cfg

DEFAULT_PORT = 8761
PAIR_TTL = 300  # seconds a pairing code lives
PAIR_MAX_FAILS = 10  # wrong codes before the pairing is dropped
SERVICE = "_autoedit._tcp.local."
NAME_LIMIT = 60

# environ keys the guard sets for the Flask app.
ENV_LAN = "auto_edit.lan"
ENV_DEVICE = "auto_edit.device"


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def lan_addresses() -> list[str]:
    """This machine's IPv4 addresses on the network, the routed one first."""
    found: list[str] = []
    try:  # the address the default route uses (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.")]


def ensure_certificate(folder: Path) -> tuple[Path, Path, str]:
    """(cert.pem, key.pem, SHA-256 fingerprint), made on first use."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    if not (cert_path.is_file() and key_path.is_file()):
        folder.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Auto-Edit")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("auto-edit.local")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        try:
            key_path.chmod(0o600)
        except OSError:  # pragma: no cover - Windows
            pass
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    return cert_path, key_path, hashlib.sha256(der).hexdigest()


class LanError(ValueError):
    pass


class Lan:
    """The LAN listener, its devices and the pairing in progress."""

    def __init__(self, folder: Path | None = None):
        self._folder = folder
        self._lock = threading.RLock()
        self._app = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._zeroconf = None
        self._error: str | None = None
        self._pairing: dict | None = None
        self._fingerprint: str | None = None

    # ── storage ──
    @property
    def folder(self) -> Path:
        return self._folder or (cfg.home_dir() / "lan")

    def _config(self) -> dict:
        data = _read_json(self.folder / "lan.json", {})
        data = data if isinstance(data, dict) else {}
        port = data.get("port")
        return {
            "enabled": bool(data.get("enabled")),
            "port": port if isinstance(port, int) and 1024 <= port <= 65535 else DEFAULT_PORT,
        }

    def _devices(self) -> list[dict]:
        data = _read_json(self.folder / "devices.json", [])
        return [d for d in data if isinstance(d, dict) and d.get("id") and d.get("token_sha256")] if isinstance(data, list) else []

    def _save_devices(self, devices: list[dict]) -> None:
        _write_json(self.folder / "devices.json", devices)

    def fingerprint(self) -> str:
        if self._fingerprint is None:
            self._fingerprint = ensure_certificate(self.folder)[2]
        return self._fingerprint

    # ── state ──
    def state(self) -> dict:
        with self._lock:
            conf = self._config()
            return {
                "enabled": conf["enabled"],
                "running": self._server is not None,
                "port": conf["port"],
                "addresses": lan_addresses(),
                "fingerprint": self.fingerprint() if conf["enabled"] else None,
                "mdns": self._zeroconf is not None,
                "error": self._error,
                "devices": [
                    {k: d.get(k) for k in ("id", "name", "created_at", "last_seen")}
                    for d in self._devices()
                ],
            }

    def configure(self, enabled: bool | None = None, port: int | None = None) -> dict:
        with self._lock:
            conf = self._config()
            if port is not None:
                if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
                    raise LanError("porta inválida (use de 1024 a 65535)")
                conf["port"] = port
            if enabled is not None:
                conf["enabled"] = bool(enabled)
            _write_json(self.folder / "lan.json", conf)
            self.stop()
            if conf["enabled"]:
                self.start()
            else:
                self._pairing = None
            return self.state()

    # ── devices ──
    def pairing(self) -> dict:
        """A new one-time code (replaces the previous one) and the QR's link."""
        with self._lock:
            conf = self._config()
            if not conf["enabled"]:
                raise LanError("ligue o acesso pela rede antes de parear")
            code = secrets.token_urlsafe(16)
            expires = _now() + PAIR_TTL
            self._pairing = {"code_sha256": _hash(code), "expires": expires, "fails": 0}
            addresses = lan_addresses()
            host = addresses[0] if addresses else None
            fp = self.fingerprint()
            query = {"host": host or "", "port": conf["port"], "code": code, "fp": fp,
                     "name": socket.gethostname()}
            return {
                "code": code,
                "expires_at": _iso(expires),
                "host": host,
                "port": conf["port"],
                "fingerprint": fp,
                "url": "autoedit://pair?" + urlencode(query),
            }

    def redeem(self, code: str, name: str) -> dict:
        """The pairing code for a device token; LanError if it's wrong or old."""
        with self._lock:
            p = self._pairing
            if not p or _now() > p["expires"]:
                self._pairing = None
                raise LanError("código expirado: gere outro QR no computador")
            if not isinstance(code, str) or not hmac.compare_digest(_hash(code), p["code_sha256"]):
                p["fails"] += 1
                if p["fails"] >= PAIR_MAX_FAILS:
                    self._pairing = None
                raise LanError("código inválido")
            self._pairing = None  # one use
            token = secrets.token_urlsafe(32)
            name = (name.strip() if isinstance(name, str) else "")[:NAME_LIMIT] or "Aparelho"
            device = {
                "id": secrets.token_hex(6),
                "name": name,
                "token_sha256": _hash(token),
                "created_at": _iso(_now()),
                "last_seen": None,
            }
            devices = self._devices()
            devices.append(device)
            self._save_devices(devices)
            return {"token": token, "device_id": device["id"], "name": name}

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            devices = self._devices()
            kept = [d for d in devices if d["id"] != device_id]
            if len(kept) == len(devices):
                return False
            self._save_devices(kept)
            return True

    def check(self, token: str | None) -> dict | None:
        """The device a token belongs to (None: unknown or revoked)."""
        if not token:
            return None
        digest = _hash(token)
        with self._lock:
            devices = self._devices()
            for d in devices:
                if hmac.compare_digest(d["token_sha256"], digest):
                    now = _now()
                    last = d.get("_seen_ts") or 0
                    if now - last > 60:  # last_seen, at most once a minute on disk
                        d["last_seen"] = _iso(now)
                        d["_seen_ts"] = now
                        self._save_devices(devices)
                    return d
        return None

    # ── listener ──
    def bind(self, app) -> None:
        """The Flask app the LAN listener serves (behind the token guard)."""
        self._app = app

    def start_if_enabled(self) -> None:
        if self._config()["enabled"]:
            self.start()

    def start(self) -> None:
        from werkzeug.serving import make_server

        with self._lock:
            if self._server is not None or self._app is None:
                return
            conf = self._config()
            self._error = None
            try:
                cert, key, fp = ensure_certificate(self.folder)
                self._fingerprint = fp
                server = make_server("0.0.0.0", conf["port"], Guard(self, self._app), threaded=True,
                                     ssl_context=(str(cert), str(key)))
            except SystemExit:  # werkzeug exits when the port is taken
                self._error = f"a porta {conf['port']} já está em uso: escolha outra"
                return
            except Exception as exc:  # no cryptography, no permission...
                self._error = f"não deu pra ouvir na porta {conf['port']}: {exc}"
                return
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, name="auto-edit-lan", daemon=True)
            self._thread.start()
            self._announce(conf["port"], fp)

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
            self._unannounce()
        if server is not None:
            server.shutdown()
            server.server_close()

    def _announce(self, port: int, fp: str) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            return
        try:
            from auto_edit import __version__

            addresses = lan_addresses()
            host = socket.gethostname().split(".")[0] or "auto-edit"
            info = ServiceInfo(
                SERVICE,
                f"Auto-Edit {host}.{SERVICE}",
                addresses=[socket.inet_aton(ip) for ip in addresses],
                port=port,
                properties={"fp": fp, "v": __version__, "name": host},
                server=f"{host}.local.",
            )
            zc = Zeroconf()
            zc.register_service(info)
            self._zeroconf = (zc, info)
        except Exception:  # mDNS is a convenience: the QR has the address
            self._zeroconf = None

    def _unannounce(self) -> None:
        if self._zeroconf is None:
            return
        zc, info = self._zeroconf
        self._zeroconf = None
        try:
            zc.unregister_service(info)
            zc.close()
        except Exception:  # pragma: no cover
            pass


def _deny(start_response, status: str, error: str):
    body = json.dumps({"error": error}).encode()
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                            ("WWW-Authenticate", "Bearer")])
    return [body]


class Guard:
    """WSGI middleware of the LAN listener: a device token on every request."""

    def __init__(self, lan: Lan, app):
        self.lan = lan
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO") or ""
        environ[ENV_LAN] = True
        if path.startswith("/api/lan"):
            return _deny(start_response, "403 Forbidden", "só no computador do motor")
        if path == "/api/pair":
            return self.app(environ, start_response)
        auth = environ.get("HTTP_AUTHORIZATION") or ""
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else None
        device = self.lan.check(token)
        if device is None:
            return _deny(start_response, "401 Unauthorized", "aparelho não pareado")
        environ[ENV_DEVICE] = device["id"]
        return self.app(environ, start_response)


manager = Lan()
