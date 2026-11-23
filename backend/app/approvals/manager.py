"""Persisted approval + execution lifecycle.

All state lives in PostgreSQL so it survives restarts. Key invariants:

- **One live request per operation** — the partial-unique index on
  ``(agent, server, tool, args_hash) WHERE status IN ('pending','approved')``
  means a retry never spawns a second pending row.
- **At-most-once dispatch** — a permit is consumed by an atomic
  ``UPDATE ... WHERE status='approved' RETURNING``; concurrent retries race and
  exactly one wins. ``executions.permit_id`` is unique as a second guard.
- **No exactly-once execution claim** — indeterminate outcomes become
  ``UNKNOWN`` for manual reconciliation; nothing is auto-retried.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import ApprovalRequest, Execution
from app.enums import ApprovalStatus, ExecutionState, Outcome

logger = logging.getLogger("wardenix.approvals")

_LIVE_STATUSES = (ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value)


def approval_to_dict(ar: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": str(ar.id),
        "correlation_id": str(ar.correlation_id),
        "agent_id": str(ar.agent_id),
        "server_id": str(ar.server_id),
        "tool": ar.tool,
        "args_redacted": ar.args_redacted,
        "risk_score": ar.risk_score,
        "risk_band": ar.risk_band,
        "status": ar.status,
        "created_at": ar.created_at.isoformat() if ar.created_at else None,
        "expires_at": ar.expires_at.isoformat() if ar.expires_at else None,
        "decided_at": ar.decided_at.isoformat() if ar.decided_at else None,
    }


class ApprovalManager:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        settings: Settings,
        notifier: Callable[[dict], None] | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._settings = settings
        self._notify = notifier or (lambda _event: None)

    # --- lookup ---
    async def find_live(
        self, agent_id: uuid.UUID, server_id: uuid.UUID, tool: str, args_hash: str
    ) -> ApprovalRequest | None:
        async with self._sm() as s:
            return await s.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.agent_id == agent_id,
                    ApprovalRequest.server_id == server_id,
                    ApprovalRequest.tool == tool,
                    ApprovalRequest.args_hash == args_hash,
                    ApprovalRequest.status.in_(_LIVE_STATUSES),
                )
            )

    @staticmethod
    def is_expired(ar: ApprovalRequest) -> bool:
        exp = ar.expires_at
        if exp is None:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return exp < datetime.now(UTC)

    # --- create ---
    async def create_pending(
        self,
        *,
        agent_id: uuid.UUID,
        server_id: uuid.UUID,
        tool: str,
        args_hash: str,
        args_redacted: dict,
        risk_score: int,
        risk_band: str,
    ) -> tuple[ApprovalRequest, bool]:
        """Create a pending request. Returns (request, created). If a live row
        already exists (race / rapid poll), returns the existing one, created=False."""
        correlation_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.approval_ttl_seconds)
        async with self._sm() as s:
            ar = ApprovalRequest(
                correlation_id=correlation_id,
                agent_id=agent_id,
                server_id=server_id,
                tool=tool,
                args_hash=args_hash,
                args_redacted=args_redacted,
                risk_score=risk_score,
                risk_band=risk_band,
                status=ApprovalStatus.PENDING.value,
                expires_at=expires_at,
            )
            s.add(ar)
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                existing = await self.find_live(agent_id, server_id, tool, args_hash)
                if existing is not None:
                    return existing, False
                raise
            await s.refresh(ar)
        self._notify({"type": "approval.pending", "approval": approval_to_dict(ar)})
        return ar, True

    # --- decisions (control plane) ---
    async def approve(
        self, approval_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> ApprovalRequest | None:
        return await self._decide(
            approval_id, ApprovalStatus.APPROVED, user_id, "approval.approved"
        )

    async def deny(
        self, approval_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> ApprovalRequest | None:
        return await self._decide(approval_id, ApprovalStatus.DENIED, user_id, "approval.denied")

    async def _decide(
        self,
        approval_id: uuid.UUID,
        new_status: ApprovalStatus,
        user_id: uuid.UUID | None,
        event: str,
    ) -> ApprovalRequest | None:
        async with self._sm() as s:
            row = await s.scalar(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.id == approval_id,
                    ApprovalRequest.status == ApprovalStatus.PENDING.value,
                )
                .values(status=new_status.value, decided_by=user_id, decided_at=func.now())
                .returning(ApprovalRequest)
            )
            await s.commit()
        if row is not None:
            self._notify({"type": event, "approval": approval_to_dict(row)})
        return row

    async def expire(self, approval_id: uuid.UUID) -> None:
        async with self._sm() as s:
            await s.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id == approval_id)
                .values(status=ApprovalStatus.EXPIRED.value)
            )
            await s.commit()

    # --- consume (atomic, single-use) ---
    async def consume(self, approval_id: uuid.UUID) -> bool:
        async with self._sm() as s:
            row = await s.scalar(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.id == approval_id,
                    ApprovalRequest.status == ApprovalStatus.APPROVED.value,
                )
                .values(status=ApprovalStatus.CONSUMED.value, consumed_at=func.now())
                .returning(ApprovalRequest.id)
            )
            await s.commit()
        return row is not None

    # --- executions ---
    async def create_execution(
        self, permit_id: uuid.UUID, correlation_id: uuid.UUID, idempotency_key: str | None
    ) -> Execution:
        async with self._sm() as s:
            ex = Execution(
                permit_id=permit_id,
                correlation_id=correlation_id,
                state=ExecutionState.AUTHORIZED.value,
                idempotency_key=idempotency_key,
            )
            s.add(ex)
            await s.commit()
            await s.refresh(ex)
            return ex

    async def set_execution_state(
        self,
        execution_id: uuid.UUID,
        state: ExecutionState,
        *,
        outcome: Outcome | None = None,
        dispatched: bool = False,
        finished: bool = False,
    ) -> None:
        values: dict[str, Any] = {"state": state.value}
        if outcome is not None:
            values["outcome"] = outcome.value
        if dispatched:
            values["dispatched_at"] = func.now()
        if finished:
            values["finished_at"] = func.now()
        async with self._sm() as s:
            await s.execute(update(Execution).where(Execution.id == execution_id).values(**values))
            await s.commit()

    # --- queries ---
    async def get(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        async with self._sm() as s:
            return await s.get(ApprovalRequest, approval_id)

    async def list_pending(self) -> list[ApprovalRequest]:
        async with self._sm() as s:
            return list(
                (
                    await s.execute(
                        select(ApprovalRequest)
                        .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
                        .order_by(ApprovalRequest.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )

    # --- startup recovery ---
    async def reconcile_orphaned_executions(self) -> dict[str, int]:
        """AUTHORIZED (never dispatched) -> NOT_DISPATCHED; EXECUTING (maybe
        dispatched) -> UNKNOWN. Neither is auto-retried on the consumed permit."""
        async with self._sm() as s:
            not_dispatched = await s.execute(
                update(Execution)
                .where(Execution.state == ExecutionState.AUTHORIZED.value)
                .values(
                    state=ExecutionState.NOT_DISPATCHED.value,
                    outcome=Outcome.ERROR.value,
                    finished_at=func.now(),
                )
            )
            unknown = await s.execute(
                update(Execution)
                .where(Execution.state == ExecutionState.EXECUTING.value)
                .values(
                    state=ExecutionState.UNKNOWN.value,
                    outcome=Outcome.UNKNOWN.value,
                    finished_at=func.now(),
                )
            )
            await s.commit()
        counts = {"not_dispatched": not_dispatched.rowcount, "unknown": unknown.rowcount}
        if counts["not_dispatched"] or counts["unknown"]:
            logger.warning("reconciled orphaned executions on startup: %s", counts)
        return counts

    async def expire_stale(self) -> int:
        async with self._sm() as s:
            res = await s.execute(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.status.in_(_LIVE_STATUSES),
                    ApprovalRequest.expires_at < func.now(),
                )
                .values(status=ApprovalStatus.EXPIRED.value)
            )
            await s.commit()
        return res.rowcount
