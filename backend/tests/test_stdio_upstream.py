"""Real stdio upstream integration: the gateway spawns an actual subprocess MCP
server and proxies through it (covers the stdio transport path)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest_asyncio

from app.approvals.manager import ApprovalManager
from app.audit.appender import AuditAppender, verify_chain
from app.config import get_settings
from app.db.models import Agent, MCPServer, Policy, Rule
from app.enums import Transport
from app.mcp_gateway.proxy import Gateway
from app.mcp_gateway.upstream import UpstreamManager
from app.security.auth import generate_api_key, hash_api_key

_ECHO_SERVER = str(Path(__file__).parent / "echo_stdio_server.py")


@pytest_asyncio.fixture
async def stdio_seeded(sessionmaker):
    get_settings.cache_clear()
    settings = get_settings()
    upstream = UpstreamManager(settings)
    manager = ApprovalManager(sessionmaker, settings)
    gateway = Gateway(sessionmaker, upstream, AuditAppender(sessionmaker), settings, manager)

    api_key = generate_api_key()
    async with sessionmaker() as s:
        agent = Agent(name="stdio-agent", api_key_hash=hash_api_key(api_key))
        server = MCPServer(
            name="estdio",
            transport=Transport.STDIO.value,
            command=sys.executable,
            args=[_ECHO_SERVER],
        )
        policy = Policy(name="allow-all", default_action="deny")
        s.add_all([agent, server, policy])
        await s.commit()
        await s.refresh(agent)
        await s.refresh(policy)
        s.add(Rule(policy_id=policy.id, priority=100, action="allow", conditions={}))
        await s.commit()
    try:
        yield gateway, agent
    finally:
        await upstream.aclose()


async def test_stdio_upstream_list_and_call(stdio_seeded, sessionmaker):
    gateway, agent = stdio_seeded

    tools = await gateway.list_tools(agent)
    assert "estdio.echo" in {t.name for t in tools}

    result = await gateway.call_tool(agent, "estdio.echo", {"text": "over-stdio"})
    assert result.is_error is False
    assert "stdio-echo: over-stdio" in result.content[0].text

    assert (await verify_chain(sessionmaker))["ok"] is True
