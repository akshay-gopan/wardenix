"""Audit read + chain-verification (viewer+)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_viewer
from app.audit.appender import verify_chain
from app.db.models import AuditEvent
from app.db.session import get_session, get_sessionmaker

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(require_viewer)])


def _event_dict(e: AuditEvent) -> dict:
    return {
        "seq": e.seq,
        "correlation_id": str(e.correlation_id),
        "ts": e.ts.isoformat() if e.ts else None,
        "event_type": e.event_type,
        "agent_id": str(e.agent_id) if e.agent_id else None,
        "server_id": str(e.server_id) if e.server_id else None,
        "tool": e.tool,
        "args_redacted": e.args_redacted,
        "decision": e.decision,
        "risk_score": e.risk_score,
        "risk_band": e.risk_band,
        "risk_signals": e.risk_signals,
        "outcome": e.outcome,
        "latency_ms": e.latency_ms,
    }


@router.get("")
async def list_events(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, ge=1, le=1000),
    before_seq: int | None = Query(None, description="return events with seq < this (paging)"),
    correlation_id: uuid.UUID | None = None,
) -> list[dict]:
    stmt = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    if before_seq is not None:
        stmt = stmt.where(AuditEvent.seq < before_seq)
    if correlation_id is not None:
        stmt = stmt.where(AuditEvent.correlation_id == correlation_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_event_dict(e) for e in rows]


@router.get("/verify")
async def verify() -> dict:
    """Walk the hash chain and report OK or the first breakage."""
    return await verify_chain(get_sessionmaker())
