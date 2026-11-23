"""Single-writer, hash-chained audit appender + chain verification.

All appends serialize through one in-process lock so the chain stays linear
(single gateway instance for the MVP; a multi-instance deployment would use a
``pg_advisory_xact_lock`` instead). The appender uses its own short-lived
session so audit writes do not roll back with a request transaction.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit.chain import GENESIS_HASH, build_payload, compute_entry_hash
from app.db.models import AuditEvent
from app.enums import AuditEventType


class AuditAppender:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker
        self._lock = asyncio.Lock()

    async def append(
        self,
        *,
        event_type: AuditEventType,
        correlation_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        server_id: uuid.UUID | None = None,
        tool: str | None = None,
        args_redacted: dict | None = None,
        decision: str | None = None,
        matched_rule_id: uuid.UUID | None = None,
        risk_score: int | None = None,
        risk_band: str | None = None,
        risk_signals: dict | None = None,
        outcome: str | None = None,
        latency_ms: int | None = None,
    ) -> AuditEvent:
        async with self._lock:
            async with self._sm() as session:
                prev_hash = await session.scalar(
                    select(AuditEvent.entry_hash).order_by(AuditEvent.seq.desc()).limit(1)
                )
                prev_hash = prev_hash or GENESIS_HASH
                ts = datetime.now(UTC)
                payload = build_payload(
                    correlation_id=correlation_id,
                    ts=ts,
                    event_type=event_type.value,
                    agent_id=agent_id,
                    server_id=server_id,
                    tool=tool,
                    args_redacted=args_redacted,
                    decision=decision,
                    matched_rule_id=matched_rule_id,
                    risk_score=risk_score,
                    risk_band=risk_band,
                    risk_signals=risk_signals,
                    outcome=outcome,
                    latency_ms=latency_ms,
                )
                entry_hash = compute_entry_hash(payload, prev_hash)
                row = AuditEvent(
                    correlation_id=correlation_id,
                    ts=ts,
                    event_type=event_type.value,
                    agent_id=agent_id,
                    server_id=server_id,
                    tool=tool,
                    args_redacted=args_redacted or {},
                    decision=decision,
                    matched_rule_id=matched_rule_id,
                    risk_score=risk_score,
                    risk_band=risk_band,
                    risk_signals=risk_signals or {},
                    outcome=outcome,
                    latency_ms=latency_ms,
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row


async def verify_chain(sessionmaker: async_sessionmaker) -> dict:
    """Walk the chain in ``seq`` order, recomputing each hash.

    Returns ``{"ok": True, "count": n}`` or the first breakage found.
    """
    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(AuditEvent).order_by(AuditEvent.seq.asc())))
            .scalars()
            .all()
        )

    prev_hash = GENESIS_HASH
    for row in rows:
        if row.prev_hash != prev_hash:
            return {
                "ok": False,
                "first_bad_seq": row.seq,
                "reason": "prev_hash does not match prior entry_hash (break or reorder)",
            }
        payload = build_payload(
            correlation_id=row.correlation_id,
            ts=row.ts,
            event_type=row.event_type,
            agent_id=row.agent_id,
            server_id=row.server_id,
            tool=row.tool,
            args_redacted=row.args_redacted,
            decision=row.decision,
            matched_rule_id=row.matched_rule_id,
            risk_score=row.risk_score,
            risk_band=row.risk_band,
            risk_signals=row.risk_signals,
            outcome=row.outcome,
            latency_ms=row.latency_ms,
        )
        if compute_entry_hash(payload, prev_hash) != row.entry_hash:
            return {
                "ok": False,
                "first_bad_seq": row.seq,
                "reason": "entry_hash mismatch (row content tampered)",
            }
        prev_hash = row.entry_hash

    return {"ok": True, "count": len(rows)}
