"""Password hashing, API-key hashing, and JWT helpers.

- User passwords: Argon2id (salted, slow) — never reversible, verified per login.
- Agent API keys: high-entropy random tokens stored as SHA-256 (fast,
  deterministic lookup by hash). A pepper from the app secret is mixed in so a
  leaked DB alone cannot be brute-forced against weak keys.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import get_settings

_ph = PasswordHasher()

API_KEY_PREFIX = "wrdx_"


# --- user passwords ---------------------------------------------------------
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# --- agent API keys ---------------------------------------------------------
def generate_api_key() -> str:
    """Return a fresh opaque API key (shown to the operator exactly once)."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    pepper = get_settings().jwt_secret.encode()
    return hashlib.sha256(pepper + api_key.encode()).hexdigest()


# --- JWT --------------------------------------------------------------------
def create_access_token(subject: str, role: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
