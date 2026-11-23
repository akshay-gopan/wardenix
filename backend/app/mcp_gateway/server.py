"""Agent-facing MCP server: low-level handlers wired to the gateway pipeline.

Agents authenticate with an API key sent as ``Authorization: Bearer <key>`` or
``X-Wardenix-Api-Key``. Unauthenticated requests are rejected (fail-closed).
"""

from __future__ import annotations

from typing import Any

from mcp import MCPError
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, ListToolsResult

from app.mcp_gateway.errors import UnauthenticatedAgent
from app.mcp_gateway.proxy import Gateway

AUTH_ERROR_CODE = -32001


def _extract_api_key(request: Any) -> str | None:
    if request is None:
        return None
    headers = request.headers
    auth = headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get("x-wardenix-api-key")


def build_gateway_server(
    gateway: Gateway, *, name: str = "wardenix-gateway", version: str = "0.1.0"
) -> Server:
    async def _auth(ctx: ServerRequestContext):
        try:
            return await gateway.authenticate(_extract_api_key(ctx.request))
        except UnauthenticatedAgent as exc:
            raise MCPError(AUTH_ERROR_CODE, exc.public_message) from exc

    async def on_list_tools(ctx: ServerRequestContext, params: Any) -> ListToolsResult:
        agent = await _auth(ctx)
        tools = await gateway.list_tools(agent)
        return ListToolsResult(tools=tools)

    async def on_call_tool(ctx: ServerRequestContext, params: Any) -> CallToolResult:
        agent = await _auth(ctx)
        return await gateway.call_tool(agent, params.name, params.arguments or {})

    return Server(
        name,
        version=version,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
