"""End-to-end Data Plane passthrough tests against the in-process fake upstream."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit.appender import verify_chain
from app.db.models import AuditEvent, Policy, Rule
from app.enums import AuditEventType, Outcome
from app.mcp_gateway.errors import UnauthenticatedAgent


async def test_authenticate_valid_and_invalid(seeded):
    agent = await seeded.gateway.authenticate(seeded.api_key)
    assert agent.id == seeded.agent.id
    with pytest.raises(UnauthenticatedAgent):
        await seeded.gateway.authenticate("wrdx_wrong")
    with pytest.raises(UnauthenticatedAgent):
        await seeded.gateway.authenticate(None)


async def test_list_tools_namespaced(seeded):
    tools = await seeded.gateway.list_tools(seeded.agent)
    names = {t.name for t in tools}
    assert "fake.echo" in names
    assert "fake.slow" in names


async def test_call_tool_allow_flow_audits_decision_and_outcome(seeded):
    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "hi"})
    assert result.is_error is False
    assert "echo: hi" in result.content[0].text

    async with seeded.sessionmaker() as s:
        rows = (await s.execute(select(AuditEvent).order_by(AuditEvent.seq))).scalars().all()
    types = [r.event_type for r in rows]
    assert AuditEventType.DECISION.value in types
    assert AuditEventType.OUTCOME.value in types
    outcome_row = next(r for r in rows if r.event_type == AuditEventType.OUTCOME.value)
    assert outcome_row.outcome == Outcome.SUCCESS.value
    # decision + outcome share one correlation id
    assert len({r.correlation_id for r in rows}) == 1

    chain = await verify_chain(seeded.sessionmaker)
    assert chain["ok"] is True


async def test_unknown_server_denied(seeded):
    result = await seeded.gateway.call_tool(seeded.agent, "ghost.tool", {})
    assert result.is_error is True
    assert "wardenix:unknown_tool" in result.content[0].text


async def test_invalid_namespaced_name_denied(seeded):
    result = await seeded.gateway.call_tool(seeded.agent, "notnamespaced", {})
    assert result.is_error is True


async def test_upstream_timeout_is_structured_error(seeded):
    result = await seeded.gateway.call_tool(seeded.agent, "fake.slow", {})
    assert result.is_error is True
    assert "wardenix:upstream_timeout" in result.content[0].text

    async with seeded.sessionmaker() as s:
        rows = (await s.execute(select(AuditEvent))).scalars().all()
    assert any(r.outcome == Outcome.ERROR.value for r in rows)


async def test_upstream_error_is_structured_error(seeded):
    result = await seeded.gateway.call_tool(seeded.agent, "fake.boom", {})
    assert result.is_error is True
    assert "wardenix:upstream_error" in result.content[0].text


async def test_args_too_large_denied(seeded):
    big = {"blob": "x" * (seeded.settings.max_args_bytes + 10)}
    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", big)
    assert result.is_error is True
    assert "wardenix:args_too_large" in result.content[0].text


async def test_policy_deny_blocks_call_independently(seeded):
    """A DENY rule blocks a direct call and never reaches the upstream, regardless
    of tools/list visibility or the allow-all rule (DENY precedence)."""
    # The echo tool is listed and allowed by the allow-all rule...
    tools = await seeded.gateway.list_tools(seeded.agent)
    assert "fake.echo" in {t.name for t in tools}

    # ...but a DENY rule on that tool must win.
    async with seeded.sessionmaker() as s:
        policy_id = (await s.execute(select(Policy.id))).scalar_one()
        s.add(
            Rule(
                policy_id=policy_id,
                priority=1,
                action="deny",
                conditions={"tools": ["echo"]},
                message="echo is forbidden",
            )
        )
        await s.commit()

    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "hi"})
    assert result.is_error is True
    assert "wardenix:policy_denied" in result.content[0].text
    # upstream never produced a success outcome for this call
    async with seeded.sessionmaker() as s:
        outcomes = [
            r.outcome
            for r in (await s.execute(select(AuditEvent))).scalars().all()
            if r.event_type == AuditEventType.OUTCOME.value
        ]
    assert Outcome.SUCCESS.value not in outcomes


async def test_require_approval_returns_structured_pending(seeded):
    async with seeded.sessionmaker() as s:
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

    result = await seeded.gateway.call_tool(seeded.agent, "fake.echo", {"text": "hi"})
    assert result.is_error is True
    assert "wardenix:approval_required" in result.content[0].text
    # the decision is recorded as require_approval
    async with seeded.sessionmaker() as s:
        decisions = [
            r.decision
            for r in (await s.execute(select(AuditEvent))).scalars().all()
            if r.event_type == AuditEventType.DECISION.value
        ]
    assert "require_approval" in decisions
