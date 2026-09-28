"""Secrets: encrypted credential storage, password hashing, signed tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet

from .config import settings


def _derive(secret: str) -> bytes:
    """Accept a Fernet key as-is, or turn any other secret string into one."""
    raw = secret.strip().encode()
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _key() -> bytes:
    if settings.SECRET_KEY:
        return _derive(settings.SECRET_KEY)
    if settings.DATABASE_URL:
        # A generated key would be lost on every restart of a cloud server, making saved logins unreadable.
        raise RuntimeError("SECRET_KEY must be set when DATABASE_URL is used (any long random string).")
    # Local dev fallback: persist a generated key next to the SQLite database.
    kf = Path(settings.DATABASE_PATH).parent / "secret.key" if settings.DATABASE_PATH != ":memory:" else None
    if kf and kf.exists():
        return kf.read_bytes().strip()
    k = Fernet.generate_key()
    if kf:
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_bytes(k)
    settings.SECRET_KEY = k.decode()
    return k


_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def encrypt_json(data: dict) -> str:
    return fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    return json.loads(fernet().decrypt(token.encode()).decode())


# ---- passwords (PBKDF2-SHA256, 310k iterations) ----
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 310_000)
    return f"pbkdf2${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(s), 310_000)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


# ---- signed tokens (sessions, shareable report links) ----
def _mac(payload: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(_key(), payload, hashlib.sha256).digest()).decode().rstrip("=")


def sign(data: dict, ttl_seconds: int) -> str:
    body = dict(data, exp=int(time.time()) + ttl_seconds)
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_mac(raw.encode())}"


def unsign(token: str) -> dict | None:
    try:
        raw, mac = token.rsplit(".", 1)
        if not hmac.compare_digest(mac, _mac(raw.encode())):
            return None
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if body.get("exp", 0) < time.time():
            return None
        return body
    except Exception:
        return None


def random_state() -> str:
    return secrets.token_urlsafe(24)
