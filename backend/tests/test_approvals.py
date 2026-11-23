"""Persisted approval workflow: permit lifecycle, retry re-evaluation, replay,
modified-arg, UNKNOWN outcomes, and restart recovery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import ApprovalRequest, Execution, Policy, Rule
from app.enums import ApprovalStatus, ExecutionState, Outcome
from app.mcp_gateway.proxy import Gateway


async def _add_rule(seeded, action: str, tool: str = "echo", priority: int = 1) -> None:
    async with seeded.sessionmaker() as s:
        policy_id = (await s.execute(select(Policy.id))).scalar_one()
        s.add(
            Rule(
                policy_id=policy_id,
                priority=priority,
                action=action,
                conditions={"tools": [tool]},
            )
        )
        await s.commit()


def _structured(result):
    return result.structured_content or {}


# --------------------------------------------------------------------------- #
# Pending creation + de-duplication
# --------------------------------------------------------------------------- #
async def test_require_approval_creates_single_pending_on_repeat(seeded):
    await _add_rule(seeded, "require_approval")

    r1 = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "hi"})
    r2 = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "hi"})  # poll/retry
    assert _structured(r1)["status"] == "approval_required"
    assert _structured(r2)["approval_id"] == _structured(r1)["approval_id"]

    async with seeded.sessionmaker() as s:
        rows = (await s.execute(select(ApprovalRequest))).scalars().all()
    assert len(rows) == 1  # partial-unique: no duplicate pending
    assert rows[0].status == ApprovalStatus.PENDING.value
    # a WS pending event fired exactly once
    assert sum(1 for e in seeded.events if e["type"] == "approval.pending") == 1


async def test_modified_args_create_separate_pending(seeded):
    await _add_rule(seeded, "require_approval")
    r1 = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "a"})
    r2 = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "b"})
    assert _structured(r1)["approval_id"] != _structured(r2)["approval_id"]


# --------------------------------------------------------------------------- #
# Approve -> retry executes exactly once (at-most-once dispatch)
# --------------------------------------------------------------------------- #
async def test_approve_then_retry_executes_once(seeded):
    await _add_rule(seeded, "require_approval")
    pending = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "go"})
    approval_id = _structured(pending)["approval_id"]

    approved = await seeded.manager.approve(uuid.UUID(approval_id))
    assert approved is not None

    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "go"})
    assert result.is_error is False
    assert "echo: go" in result.content[0].text

    async with seeded.sessionmaker() as s:
        ar = await s.get(ApprovalRequest, uuid.UUID(approval_id))
        execs = (await s.execute(select(Execution))).scalars().all()
    assert ar.status == ApprovalStatus.CONSUMED.value
    assert len(execs) == 1
    assert execs[0].state == ExecutionState.SUCCEEDED.value


async def test_consume_is_single_use_replay_rejected(seeded):
    await _add_rule(seeded, "require_approval")
    pending = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "x"})
    approval_id = uuid.UUID(_structured(pending)["approval_id"])
    await seeded.manager.approve(approval_id)

    assert await seeded.manager.consume(approval_id) is True
    assert await seeded.manager.consume(approval_id) is False  # replay rejected


# --------------------------------------------------------------------------- #
# Retry re-evaluates policy: a new DENY overrides an existing approval
# --------------------------------------------------------------------------- #
async def test_new_deny_overrides_existing_approval(seeded):
    await _add_rule(seeded, "require_approval", priority=5)
    pending = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "q"})
    await seeded.manager.approve(uuid.UUID(_structured(pending)["approval_id"]))

    # Operator adds a DENY rule before the agent retries.
    await _add_rule(seeded, "deny", priority=1)

    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "q"})
    assert result.is_error is True
    assert "wardenix:policy_denied" in result.content[0].text
    # permit was not consumed; nothing executed
    async with seeded.sessionmaker() as s:
        execs = (await s.execute(select(Execution))).scalars().all()
    assert execs == []


# --------------------------------------------------------------------------- #
# UNKNOWN outcomes
# --------------------------------------------------------------------------- #
async def test_upstream_timeout_after_approval_is_unknown(seeded):
    await _add_rule(seeded, "require_approval", tool="slow")
    pending = await seeded.gateway.call_tool(seeded.agent, "fake.slow", {})
    await seeded.manager.approve(uuid.UUID(_structured(pending)["approval_id"]))

    result = await seeded.gateway.call_tool(seeded.agent, "fake.slow", {})
    assert result.is_error is True
    assert "wardenix:execution_unknown" in result.content[0].text

    async with seeded.sessionmaker() as s:
        execs = (await s.execute(select(Execution))).scalars().all()
    assert execs[0].state == ExecutionState.UNKNOWN.value
    assert execs[0].outcome == Outcome.UNKNOWN.value


# --------------------------------------------------------------------------- #
# Restart recovery
# --------------------------------------------------------------------------- #
async def test_restart_reconciles_orphaned_executions(seeded):
    # Fabricate orphaned executions as if a crash left them mid-flight.
    async with seeded.sessionmaker() as s:
        ar1 = ApprovalRequest(
            agent_id=seeded.agent.id, server_id=seeded.server.id, tool="echo",
            args_hash="h1", status=ApprovalStatus.CONSUMED.value,
            expires_at=datetime.now(UTC),
        )
        ar2 = ApprovalRequest(
            agent_id=seeded.agent.id, server_id=seeded.server.id, tool="echo",
            args_hash="h2", status=ApprovalStatus.CONSUMED.value,
            expires_at=datetime.now(UTC),
        )
        s.add_all([ar1, ar2])
        await s.commit()
        await s.refresh(ar1)
        await s.refresh(ar2)
        s.add(Execution(permit_id=ar1.id, correlation_id=ar1.correlation_id,
                        state=ExecutionState.AUTHORIZED.value))
        s.add(Execution(permit_id=ar2.id, correlation_id=ar2.correlation_id,
                        state=ExecutionState.EXECUTING.value))
        await s.commit()

    counts = await seeded.manager.reconcile_orphaned_executions()
    assert counts == {"not_dispatched": 1, "unknown": 1}

    async with seeded.sessionmaker() as s:
        states = {e.state for e in (await s.execute(select(Execution))).scalars().all()}
    assert ExecutionState.NOT_DISPATCHED.value in states
    assert ExecutionState.UNKNOWN.value in states


async def test_restart_midapproval_then_approve_still_works(seeded):
    await _add_rule(seeded, "require_approval")
    pending = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "survive"})
    approval_id = uuid.UUID(_structured(pending)["approval_id"])

    # Simulate a restart: brand-new gateway instance over the same DB.
    fresh_gateway = Gateway(
        seeded.sessionmaker, seeded.upstream, seeded.appender, seeded.settings, seeded.manager
    )
    await seeded.manager.approve(approval_id)
    result = await fresh_gateway.call_tool(seeded.agent, "fake.echo", {"text": "survive"})
    assert result.is_error is False
    assert "echo: survive" in result.content[0].text
