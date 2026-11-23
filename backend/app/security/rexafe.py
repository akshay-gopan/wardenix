"""ReDoS-safe regex for policy conditions.

Policy regexes are operator-supplied, so they must not be able to hang the Data
Plane. We use ``google-re2`` (linear-time automaton, no catastrophic
backtracking), validate patterns at save time, and cap both pattern and input
length. ``re`` is deliberately NOT used — it holds the GIL during matching, so a
timeout cannot interrupt a catastrophic pattern.
"""

from __future__ import annotations

from functools import lru_cache

import re2

MAX_PATTERN_LEN = 512
MAX_INPUT_LEN = 65_536


class UnsafeRegex(ValueError):
    """Raised when a policy regex pattern is rejected at validation time."""


@lru_cache(maxsize=1024)
def _compile(pattern: str):
    return re2.compile(pattern)


def validate_pattern(pattern: str) -> None:
    """Validate a pattern at save time. Raises :class:`UnsafeRegex` if rejected."""
    if not isinstance(pattern, str):
        raise UnsafeRegex("pattern must be a string")
    if len(pattern) > MAX_PATTERN_LEN:
        raise UnsafeRegex(f"pattern exceeds {MAX_PATTERN_LEN} characters")
    try:
        _compile(pattern)
    except Exception as exc:  # noqa: BLE001 - re2 raises various error types
        raise UnsafeRegex(f"invalid regex: {exc}") from exc


def search(pattern: str, text: str) -> bool:
    """Return True if ``pattern`` matches anywhere in ``text`` (linear time)."""
    if len(pattern) > MAX_PATTERN_LEN:
        raise UnsafeRegex(f"pattern exceeds {MAX_PATTERN_LEN} characters")
    if len(text) > MAX_INPUT_LEN:
        text = text[:MAX_INPUT_LEN]
    return bool(_compile(pattern).search(text))
