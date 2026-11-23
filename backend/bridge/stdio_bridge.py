"""Wardenix stdio bridge.

Lets a stdio-only MCP client (e.g. Claude Desktop / Claude Code) talk to the
Wardenix gateway, which speaks Streamable HTTP. The bridge also makes the
persisted approval workflow *transparent*: when a ``tools/call`` comes back as
``approval_required``, the bridge polls the approval's status over the Control
Plane REST API and, once approved, re-issues the identical call so the client
experiences a single (if slow) call.

Run:
    python -m bridge.stdio_bridge --url http://localhost:8000/mcp \\
        --api-base http://localhost:8000 --api-key wrdx_...

(API key may also be supplied via the ``WARDENIX_API_KEY`` environment variable.)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import mcp.types as mt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

TERMINAL_STATUSES = {"approved", "denied", "expired", "consumed"}


async def resolve_call(
    do_call: Callable[[], Awaitable[Any]],
    get_status: Callable[[str], Awaitable[str]],
    *,
    interval: float,
    deadline: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """Issue a tool call; if it returns ``approval_required``, poll the approval
    status and re-issue once approved. Returns the final tool result.

    Pure w.r.t. its injected ``do_call``/``get_status``/``sleep``/``clock`` so the
    retry logic is unit-testable without a live gateway.
    """
    result = await do_call()
    structured = getattr(result, "structured_content", None) or {}
    if structured.get("status") != "approval_required":
        return result

    approval_id = structured.get("approval_id")
    end = clock() + deadline
    while clock() < end:
        status = await get_status(approval_id)
        if status == "approved":
            return await do_call()  # consumes the permit + executes exactly once
        if status in ("denied", "expired", "consumed"):
            return result  # surface the pending/denied info to the client
        await sleep(interval)
    return result  # timed out waiting for a human decision


def _build_bridge_server(
    session: ClientSession,
    http: httpx.AsyncClient,
    api_base: str,
    *,
    interval: float,
    deadline: float,
) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> mt.ListToolsResult:
        return await session.list_tools()

    async def get_status(approval_id: str) -> str:
        resp = await http.get(f"{api_base}/api/approvals/{approval_id}")
        if resp.status_code != 200:
            return "unknown"
        return resp.json().get("status", "unknown")

    async def on_call_tool(ctx: Any, params: Any) -> mt.CallToolResult:
        async def do_call() -> mt.CallToolResult:
            return await session.call_tool(params.name, params.arguments or {})

        return await resolve_call(do_call, get_status, interval=interval, deadline=deadline)

    return Server(
        "wardenix-bridge",
        version="0.1.0",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def _run(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.environ.get("WARDENIX_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(args.url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                bridge = _build_bridge_server(
                    session,
                    http,
                    args.api_base,
                    interval=args.poll_interval,
                    deadline=args.timeout,
                )
                async with stdio_server() as (r, w):
                    await bridge.run(r, w, bridge.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description="Wardenix stdio↔HTTP bridge")
    parser.add_argument("--url", required=True, help="Gateway Streamable HTTP /mcp URL")
    parser.add_argument(
        "--api-base", default=None, help="Control Plane base URL (defaults to --url without /mcp)"
    )
    parser.add_argument("--api-key", default=None, help="Agent API key (or WARDENIX_API_KEY)")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if args.api_base is None:
        args.api_base = args.url.rsplit("/mcp", 1)[0] or args.url
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
