"""Canonical argument hashing for approval permits.

A permit is bound to the exact arguments it was approved for. We hash a stable
canonicalization of the arguments; a modified retry produces a different hash
and therefore cannot reuse an existing permit.

This is a deterministic, sorted-key JSON canonicalization (sufficient for
same-structure equality), not full RFC 8785 number canonicalization.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_args_hash(arguments: dict[str, Any] | None) -> str:
    material = json.dumps(
        arguments or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
