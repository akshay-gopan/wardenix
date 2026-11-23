"""Upstream MCP connection manager.

Connects to an upstream server (stdio, HTTP, or an in-process ``Server`` for
tests) using the high-level ``mcp.Client``. HTTP upstreams pass an SSRF check
before connecting. Every operation is bounded by the configured per-call
timeout using anyio's ``fail_after`` (cancel-scope safe).

Connections are opened and closed within a single call (same task). This avoids
the anyio pitfall of entering an async context in one task and exiting it in
another — which corrupts cancel scopes under a concurrent HTTP server. Pooling
would require an owner-task design and is deferred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anyio
from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, Tool

from app.config import Settings
from app.db.models import MCPServer
from app.enums import Transport
from app.mcp_gateway.errors import UpstreamError, UpstreamTimeout, UpstreamUnavailable
from app.security.ssrf import SsrfError, validate_http_url

logger = logging.getLogger("wardenix.upstream")


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: float | None = None


class UpstreamManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._inprocess: dict[UUID, Any] = {}
        self._breakers: dict[UUID, _Breaker] = {}

    def register_inprocess(self, server_id: UUID, server_obj: Any) -> None:
        """Test hook: register an in-process Server as an upstream target."""
        self._inprocess[server_id] = server_obj

    # --- circuit breaker ---
    def _breaker(self, server_id: UUID) -> _Breaker:
        return self._breakers.setdefault(server_id, _Breaker())

    def _check_breaker(self, server: MCPServer) -> None:
        b = self._breaker(server.id)
        if b.opened_at is None:
            return
        if time.monotonic() - b.opened_at < self._settings.circuit_breaker_cooldown_seconds:
            raise UpstreamUnavailable(
                f"upstream {server.name!r} circuit open (too many recent failures)"
            )
        # cooldown elapsed -> half-open: allow a trial by resetting the timer
        b.opened_at = None

    def _record(self, server_id: UUID, ok: bool) -> None:
        b = self._breaker(server_id)
        if ok:
            b.failures = 0
            b.opened_at = None
            return
        b.failures += 1
        if b.failures >= self._settings.circuit_breaker_threshold:
            b.opened_at = time.monotonic()

    def _target(self, server: MCPServer) -> Any:
        if server.id in self._inprocess:
            return self._inprocess[server.id]
        if server.transport == Transport.STDIO.value:
            if not server.command:
                raise UpstreamUnavailable("stdio upstream has no command configured")
            return StdioServerParameters(
                command=server.command,
                args=list(server.args or []),
                env=dict(server.env) if server.env else None,
            )
        if server.transport == Transport.HTTP.value:
            if not server.url:
                raise UpstreamUnavailable("http upstream has no url configured")
            try:
                validate_http_url(
                    server.url,
                    allowlist=self._settings.ssrf_allowlist_list or None,
                    allow_private=self._settings.ssrf_allow_private,
                )
            except SsrfError as exc:
                raise UpstreamUnavailable(f"upstream rejected by SSRF guard: {exc}") from exc
            return server.url
        raise UpstreamUnavailable(f"unknown transport {server.transport!r}")

    async def list_tools(self, server: MCPServer) -> list[Tool]:
        self._check_breaker(server)
        target = self._target(server)
        try:
            with anyio.fail_after(self._settings.upstream_timeout_seconds):
                async with Client(target) as client:
                    result = await client.list_tools()
                    self._record(server.id, ok=True)
                    return list(result.tools)
        except (TimeoutError, anyio.ClosedResourceError) as exc:
            self._record(server.id, ok=False)
            raise UpstreamTimeout(f"upstream {server.name!r} timed out listing tools") from exc
        except UpstreamUnavailable:
            raise
        except Exception as exc:
            self._record(server.id, ok=False)
            raise UpstreamError(f"upstream {server.name!r} failed to list tools") from exc

    async def call_tool(
        self, server: MCPServer, tool_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        self._check_breaker(server)
        target = self._target(server)
        try:
            with anyio.fail_after(self._settings.upstream_timeout_seconds):
                async with Client(target) as client:
                    result = await client.call_tool(tool_name, arguments)
                    self._record(server.id, ok=True)
                    return result
        except (TimeoutError, anyio.ClosedResourceError) as exc:
            self._record(server.id, ok=False)
            raise UpstreamTimeout(
                f"upstream {server.name!r} timed out calling {tool_name!r}"
            ) from exc
        except UpstreamUnavailable:
            raise
        except Exception as exc:
            self._record(server.id, ok=False)
            raise UpstreamError(f"upstream {server.name!r} failed calling {tool_name!r}") from exc

    async def aclose(self) -> None:
        # No persistent connections to close (connections are per-call).
        return None
