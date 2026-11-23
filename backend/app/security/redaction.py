"""Argument redaction for audit records and approval displays.

Key-name based redaction (case-insensitive substring match). Wardenix never
stores raw tool arguments that look like secrets; redaction is applied before
anything is written to the audit log or shown in the approval queue.
"""

from __future__ import annotations

from typing import Any

REDACTED = "***REDACTED***"

_DEFAULT_SENSITIVE = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "access_key",
        "secret_key",
        "private_key",
        "credential",
        "credentials",
        "session",
        "cookie",
        "ssn",
    }
)


def _is_sensitive(key: str, sensitive: frozenset[str]) -> bool:
    k = key.lower()
    return any(s in k for s in sensitive)


def redact(value: Any, *, extra_keys: frozenset[str] | None = None) -> Any:
    """Return a redacted deep copy of ``value`` (dicts/lists/scalars)."""
    sensitive = _DEFAULT_SENSITIVE | (extra_keys or frozenset())
    return _redact(value, sensitive)


def _redact(value: Any, sensitive: frozenset[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive(k, sensitive):
                out[k] = REDACTED
            else:
                out[k] = _redact(v, sensitive)
        return out
    if isinstance(value, list):
        return [_redact(v, sensitive) for v in value]
    return value
