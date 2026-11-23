"""Hash-chain primitives for the tamper-evident audit log.

Each audit row's ``entry_hash`` commits to its own content *and* the previous
row's hash, so any edit, deletion, or reordering breaks the chain from that
point on. The same :func:`build_payload` is used when appending and when
verifying, so the two sides hash identical material.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = "0" * 64


def _json_default(o: Any) -> Any:
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, datetime):
        return o.astimezone(UTC).isoformat()
    raise TypeError(f"not canonicalizable: {type(o)!r}")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), default=_json_default, ensure_ascii=False
    )


def build_payload(
    *,
    correlation_id: uuid.UUID,
    ts: datetime,
    event_type: str,
    agent_id: uuid.UUID | None,
    server_id: uuid.UUID | None,
    tool: str | None,
    args_redacted: dict | None,
    decision: str | None,
    matched_rule_id: uuid.UUID | None,
    risk_score: int | None,
    risk_band: str | None,
    risk_signals: dict | None,
    outcome: str | None,
    latency_ms: int | None,
) -> dict[str, Any]:
    """Build the exact dict that gets hashed for an audit row.

    Must be identical at append time and verify time.
    """
    return {
        "correlation_id": correlation_id,
        "ts": ts,
        "event_type": event_type,
        "agent_id": agent_id,
        "server_id": server_id,
        "tool": tool,
        "args_redacted": args_redacted or {},
        "decision": decision,
        "matched_rule_id": matched_rule_id,
        "risk_score": risk_score,
        "risk_band": risk_band,
        "risk_signals": risk_signals or {},
        "outcome": outcome,
        "latency_ms": latency_ms,
    }


def compute_entry_hash(payload: dict[str, Any], prev_hash: str) -> str:
    material = canonical_json({"payload": payload, "prev": prev_hash})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
