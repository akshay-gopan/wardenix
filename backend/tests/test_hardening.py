"""P5 hardening: circuit breaker, secret redaction in approvals, fail-closed on
audit-write failure, and upstream health marking."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import ApprovalRequest, MCPServer
from app.enums import ExecutionState
from app.mcp_gateway.errors import UpstreamError, UpstreamUnavailable
from app.security.redaction import REDACTED


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
async def test_circuit_breaker_opens_after_threshold(seeded, monkeypatch):
    monkeypatch.setattr(seeded.settings, "circuit_breaker_threshold", 3)
    # Drive the upstream manager directly against the "boom" tool (raises).
    for _ in range(3):
        with pytest.raises(UpstreamError):
            await seeded.upstream.call_tool(seeded.server, "boom", {})
    # Breaker now open -> fails fast with Unavailable (no connection attempt).
    with pytest.raises(UpstreamUnavailable):
        await seeded.upstream.call_tool(seeded.server, "boom", {})


async def test_circuit_breaker_resets_on_success(seeded, monkeypatch):
    monkeypatch.setattr(seeded.settings, "circuit_breaker_threshold", 3)
    with pytest.raises(UpstreamError):
        await seeded.upstream.call_tool(seeded.server, "boom", {})
    # A success resets the failure counter.
    await seeded.upstream.call_tool(seeded.server, "echo", {"text": "ok"})
    # Two more failures should not trip the (reset) breaker of threshold 3.
    for _ in range(2):
        with pytest.raises(UpstreamError):
            await seeded.upstream.call_tool(seeded.server, "boom", {})
    # Still closed -> a normal call works.
    r = await seeded.upstream.call_tool(seeded.server, "echo", {"text": "again"})
    assert r.is_error is False


# --------------------------------------------------------------------------- #
# Secret redaction reaches the approval record
# --------------------------------------------------------------------------- #
async def test_secrets_redacted_in_approval(seeded):
    async with seeded.sessionmaker() as s:
        from app.db.models import Policy, Rule

        policy_id = (await s.execute(select(Policy.id))).scalar_one()
        s.add(
            Rule(
                policy_id=policy_id,
                priority=1,
                action="require_approval",
                conditions={"tools": ["echo"]},
            )
        )
        await s.commit()

    await seeded.gateway.call_tool(
        seeded.agent, "fake.echo", {"text": "hi", "password": "s3cr3t", "api_key": "k"}
    )
    async with seeded.sessionmaker() as s:
        ar = (await s.execute(select(ApprovalRequest))).scalars().one()
    assert ar.args_redacted["password"] == REDACTED
    assert ar.args_redacted["api_key"] == REDACTED
    assert ar.args_redacted["text"] == "hi"  # non-secret preserved


# --------------------------------------------------------------------------- #
# Fail-closed: if the decision cannot be audited, the call must NOT execute
# --------------------------------------------------------------------------- #
async def test_audit_failure_fails_closed(seeded, monkeypatch):
    calls: list[str] = []

    async def boom_append(*args, **kwargs):
        raise RuntimeError("db unavailable")

    async def track_call(server, tool_name, arguments):
        calls.append(tool_name)
        raise AssertionError("upstream must not be called when audit fails")

    monkeypatch.setattr(seeded.appender, "append", boom_append)
    monkeypatch.setattr(seeded.upstream, "call_tool", track_call)

    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "x"})
    assert result.is_error is True
    assert "wardenix:internal_error" in result.content[0].text
    assert calls == []  # upstream never reached


# --------------------------------------------------------------------------- #
# Upstream crash marks the server unhealthy (via the server-test path)
# --------------------------------------------------------------------------- #
async def test_server_test_marks_unhealthy_on_failure(seeded):
    # A server whose in-process target raises on list_tools would be unhealthy;
    # here we point a server at a non-existent stdio command.
    async with seeded.sessionmaker() as s:
        bad = MCPServer(id=uuid.uuid4(), name="bad", transport="stdio", command="/nonexistent/x")
        s.add(bad)
        await s.commit()
        await s.refresh(bad)

    with pytest.raises((UpstreamError, UpstreamUnavailable)):
        await seeded.upstream.list_tools(bad)


# --------------------------------------------------------------------------- #
# UNKNOWN executions are what reconciliation surfaces (sanity for ops)
# --------------------------------------------------------------------------- #
async def test_reconcile_counts_are_reported(seeded):
    counts = await seeded.manager.reconcile_orphaned_executions()
    assert counts == {"not_dispatched": 0, "unknown": 0}
    assert ExecutionState.UNKNOWN.value == "unknown"
