"""Deterministic, offline risk scoring.

Scans the tool name and (recursively) the string arguments and keys for signal
classes, each with a fixed weight. The total maps to a band. Fully
deterministic and reproducible — the contributing signals are returned and
stored in the audit log for explainability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.enums import RiskBand

# --- signal vocabularies (lowercased) ---
_DESTRUCTIVE = frozenset(
    {
        "delete", "remove", "destroy", "drop", "truncate", "purge", "wipe",
        "erase", "format", "kill", "terminate", "overwrite", "rmdir", "unlink",
    }
)
_SECRET_KEYS = frozenset(
    {
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "authorization", "access_key", "secret_key", "private_key",
        "credential", "credentials", "ssn",
    }
)
_NETWORK_KEYS = frozenset({"url", "uri", "endpoint", "host", "hostname", "webhook"})
_BROAD_TOKENS = frozenset({"--force", "-f", "--recursive", "-r", "--all", "force"})

_WEIGHTS = {
    "destructive": 3,
    "secret_key": 2,
    "path": 2,
    "network": 1,
    "broad_scope": 2,
}

_PATH_RE = re.compile(r"(^/|\.\./|^[A-Za-z]:\\\\|/etc/|/root/|~/)")
_URL_RE = re.compile(r"^(https?|ftp|file)://", re.IGNORECASE)
# Split identifiers into words on any non-alphanumeric (so "delete_file" -> delete, file).
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RiskResult:
    score: int
    band: RiskBand
    signals: dict[str, Any] = field(default_factory=dict)


def _band_for(score: int) -> RiskBand:
    if score <= 0:
        return RiskBand.LOW
    if score <= 2:
        return RiskBand.MEDIUM
    if score <= 4:
        return RiskBand.HIGH
    return RiskBand.CRITICAL


def _walk(value: Any, keys: list[str], strings: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                keys.append(k)
            _walk(v, keys, strings)
    elif isinstance(value, list):
        for v in value:
            _walk(v, keys, strings)
    elif isinstance(value, str):
        strings.append(value)


def assess(*, server_name: str, tool_name: str, arguments: dict[str, Any]) -> RiskResult:
    keys: list[str] = []
    strings: list[str] = []
    _walk(arguments or {}, keys, strings)

    signals: dict[str, list[str]] = {}

    # destructive verbs in the tool name or any string argument
    name_tokens = set(_WORD_RE.findall(tool_name.lower()))
    destructive = sorted(name_tokens & _DESTRUCTIVE)
    for s in strings:
        destructive += sorted(set(_WORD_RE.findall(s.lower())) & _DESTRUCTIVE)
    if destructive:
        signals["destructive"] = sorted(set(destructive))

    secret = sorted({k for k in keys if k.lower() in _SECRET_KEYS})
    if secret:
        signals["secret_key"] = secret

    paths = sorted({s for s in strings if _PATH_RE.search(s)})
    if paths:
        signals["path"] = paths[:10]

    network = sorted({k for k in keys if k.lower() in _NETWORK_KEYS})
    network += sorted({s for s in strings if _URL_RE.search(s)})
    if network:
        signals["network"] = sorted(set(network))[:10]

    broad = sorted({s for s in strings if s.lower() in _BROAD_TOKENS or "*" in s})
    if broad:
        signals["broad_scope"] = broad[:10]

    score = sum(_WEIGHTS[name] for name in signals)
    return RiskResult(score=score, band=_band_for(score), signals=signals)
