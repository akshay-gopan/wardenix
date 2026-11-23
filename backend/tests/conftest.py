"""Test harness: an isolated ``wardenix_test`` database with the real schema and
triggers, reset per test, plus an in-process fake upstream MCP server.

Requires the compose Postgres reachable on localhost:5432 (``docker compose up db``).
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

# Configure test environment BEFORE importing the application.
PG_USER = os.environ.get("POSTGRES_USER", "wardenix")
PG_PW = os.environ.get("POSTGRES_PASSWORD", "wardenix_dev_pw_change_me")
PG_HOST = os.environ.get("POSTGRES_HOST_TEST", "localhost")
PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
TEST_DB = "wardenix_test"

os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{PG_USER}:{PG_PW}@{PG_HOST}:{PG_PORT}/{TEST_DB}"
os.environ["WARDENIX_JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long-000"
os.environ["WARDENIX_UPSTREAM_TIMEOUT_SECONDS"] = "1"

import anyio  # noqa: E402
import asyncpg  # noqa: E402
import mcp.types as mt  # noqa: E402
import pytest_asyncio  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.approvals.manager import ApprovalManager  # noqa: E402
from app.audit.appender import AuditAppender  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.models import Agent, Base, MCPServer, Policy, Rule  # noqa: E402
from app.enums import Transport  # noqa: E402
from app.mcp_gateway.proxy import Gateway  # noqa: E402
from app.mcp_gateway.upstream import UpstreamManager  # noqa: E402
from app.security.auth import generate_api_key, hash_api_key  # noqa: E402

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION wardenix_audit_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
END;
$$;
"""
_TRIGGER_ROW = """
CREATE TRIGGER audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION wardenix_audit_append_only();
"""
_TRIGGER_TRUNC = """
CREATE TRIGGER audit_events_no_truncate
BEFORE TRUNCATE ON audit_events
FOR EACH STATEMENT EXECUTE FUNCTION wardenix_audit_append_only();
"""


def _create_test_db() -> None:
    async def go() -> None:
        conn = await asyncpg.connect(
            host=PG_HOST, port=int(PG_PORT), user=PG_USER, password=PG_PW, database="postgres"
        )
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        finally:
            await conn.close()

    asyncio.run(go())


_create_test_db()


@pytest_asyncio.fixture
async def sessionmaker() -> async_sessionmaker:
    """Fresh engine + clean schema (with real triggers) per test."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_TRIGGER_FN))
        await conn.execute(text(_TRIGGER_ROW))
        await conn.execute(text(_TRIGGER_TRUNC))
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sm
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
def fake_upstream() -> Server:
    """In-process upstream exposing echo / slow / boom tools."""

    async def on_list_tools(ctx, params):
        return mt.ListToolsResult(
            tools=[
                mt.Tool(
                    name="echo",
                    description="echo text back",
                    input_schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                ),
                mt.Tool(name="slow", description="sleeps", input_schema={"type": "object"}),
                mt.Tool(name="boom", description="raises", input_schema={"type": "object"}),
            ]
        )

    async def on_call_tool(ctx, params):
        if params.name == "slow":
            await anyio.sleep(3)
            return mt.CallToolResult(content=[mt.TextContent(type="text", text="done")])
        if params.name == "boom":
            raise RuntimeError("upstream exploded")
        args = params.arguments or {}
        return mt.CallToolResult(
            content=[mt.TextContent(type="text", text=f"echo: {args.get('text')}")],
            is_error=False,
        )

    return Server(
        "fake-upstream",
        version="0.0.1",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


@pytest_asyncio.fixture
async def seeded(sessionmaker, fake_upstream) -> SimpleNamespace:
    get_settings.cache_clear()
    settings = get_settings()
    upstream = UpstreamManager(settings)
    appender = AuditAppender(sessionmaker)
    events: list[dict] = []
    manager = ApprovalManager(sessionmaker, settings, notifier=events.append)
    gateway = Gateway(sessionmaker, upstream, appender, settings, manager)

    api_key = generate_api_key()
    async with sessionmaker() as s:
        agent = Agent(name="test-agent", api_key_hash=hash_api_key(api_key))
        server = MCPServer(name="fake", transport=Transport.STDIO.value, command="unused")
        # Engine is default-deny, so forwarding tests need an explicit allow-all rule.
        policy = Policy(name="allow-all", default_action="deny")
        s.add_all([agent, server, policy])
        await s.commit()
        await s.refresh(agent)
        await s.refresh(server)
        await s.refresh(policy)
        s.add(Rule(policy_id=policy.id, priority=100, action="allow", conditions={}))
        await s.commit()

    upstream.register_inprocess(server.id, fake_upstream)
    try:
        yield SimpleNamespace(
            gateway=gateway,
            agent=agent,
            server=server,
            api_key=api_key,
            sessionmaker=sessionmaker,
            upstream=upstream,
            appender=appender,
            manager=manager,
            events=events,
            settings=settings,
        )
    finally:
        await upstream.aclose()
