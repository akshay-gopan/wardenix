"""The Data Plane pipeline: identify → resolve → risk → policy → forward → audit.

Phase 1 is passthrough (policy always ALLOW) but the full shape is here: every
call is authenticated, resolved, risk-tagged, policy-evaluated, and produces a
chained **decision** event and a chained **outcome** event. Audit-write failure
on the decision aborts the call (fail-closed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from mcp.types import CallToolResult, TextContent, Tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.approvals.manager import ApprovalManager
from app.approvals.permits import canonical_args_hash
from app.audit.appender import AuditAppender
from app.config import Settings
from app.db.models import Agent, ApprovalRequest, MCPServer
from app.enums import ApprovalStatus, AuditEventType, Decision, ExecutionState, Outcome
from app.mcp_gateway.errors import (
    ArgsTooLarge,
    GatewayError,
    UnauthenticatedAgent,
    UnknownTool,
)
from app.mcp_gateway.registry import InvalidNamespacedName, make_namespaced, split_namespaced
from app.mcp_gateway.upstream import UpstreamManager
from app.policy.engine import EvaluationContext, evaluate
from app.risk.assessor import assess
from app.security.auth import hash_api_key
from app.security.redaction import redact

logger = logging.getLogger("wardenix.gateway")


def _error_result(code: str, message: str, structured: dict | None = None) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"[wardenix:{code}] {message}")],
        structured_content=structured,
        is_error=True,
    )


class Gateway:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        upstream: UpstreamManager,
        appender: AuditAppender,
        settings: Settings,
        manager: ApprovalManager,
    ) -> None:
        self._sm = sessionmaker
        self._upstream = upstream
        self._appender = appender
        self._settings = settings
        self._manager = manager
        self._semaphores: dict[uuid.UUID, asyncio.Semaphore] = {}

    def _sem(self, agent_id: uuid.UUID) -> asyncio.Semaphore:
        return self._semaphores.setdefault(
            agent_id, asyncio.Semaphore(self._settings.agent_concurrency)
        )

    async def authenticate(self, api_key: str | None) -> Agent:
        if not api_key:
            raise UnauthenticatedAgent("missing agent API key")
        key_hash = hash_api_key(api_key)
        async with self._sm() as session:
            agent = await session.scalar(
                select(Agent).where(Agent.api_key_hash == key_hash, Agent.enabled.is_(True))
            )
        if agent is None:
            raise UnauthenticatedAgent("invalid or disabled agent API key")
        return agent

    async def list_tools(self, agent: Agent) -> list[Tool]:
        """Aggregate + namespace tools across enabled upstreams (best-effort).

        Filtering here is UX only; every call is independently authorized.
        """
        async with self._sm() as session:
            servers = (
                (await session.execute(select(MCPServer).where(MCPServer.enabled.is_(True))))
                .scalars()
                .all()
            )
        out: list[Tool] = []
        for server in servers:
            try:
                tools = await self._upstream.list_tools(server)
            except GatewayError as exc:
                logger.warning("omitting upstream %s from tools/list: %s", server.name, exc)
                continue
            for tool in tools:
                out.append(
                    Tool(
                        name=make_namespaced(server.name, tool.name),
                        title=tool.title,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        output_schema=tool.output_schema,
                        annotations=tool.annotations,
                    )
                )
        return out

    async def call_tool(
        self, agent: Agent, namespaced_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        correlation_id = uuid.uuid4()
        arguments = arguments or {}

        # --- resolve ---
        try:
            server_name, tool_name = split_namespaced(namespaced_name)
        except InvalidNamespacedName:
            return await self._deny(
                correlation_id, agent, None, namespaced_name, {},
                UnknownTool(f"not a valid namespaced tool: {namespaced_name!r}"),
            )
        async with self._sm() as session:
            server = await session.scalar(
                select(MCPServer).where(
                    MCPServer.name == server_name, MCPServer.enabled.is_(True)
                )
            )
        if server is None:
            return await self._deny(
                correlation_id, agent, None, namespaced_name, {},
                UnknownTool(f"unknown or disabled server {server_name!r}"),
            )

        # --- argument size guard ---
        try:
            size = len(json.dumps(arguments, default=str).encode("utf-8"))
        except (TypeError, ValueError):
            return await self._deny(
                correlation_id, agent, server, namespaced_name, {},
                ArgsTooLarge("arguments are not serializable"),
            )
        redacted = redact(arguments)
        if size > self._settings.max_args_bytes:
            return await self._deny(
                correlation_id, agent, server, namespaced_name, redacted,
                ArgsTooLarge(f"arguments exceed {self._settings.max_args_bytes} bytes"),
            )

        # --- risk + policy ---
        risk = assess(server_name=server_name, tool_name=tool_name, arguments=arguments)
        ctx = EvaluationContext(
            agent_id=agent.id,
            agent_name=agent.name,
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            risk_band=risk.band,
        )
        async with self._sm() as session:
            policy = await evaluate(session, ctx)

        # --- audit decision (fail-closed) ---
        try:
            await self._appender.append(
                event_type=AuditEventType.DECISION,
                correlation_id=correlation_id,
                agent_id=agent.id,
                server_id=server.id,
                tool=namespaced_name,
                args_redacted=redacted,
                decision=policy.decision.value,
                matched_rule_id=policy.matched_rule_id,
                risk_score=risk.score,
                risk_band=risk.band.value,
                risk_signals=risk.signals,
            )
        except Exception:
            logger.exception("audit decision write failed; failing closed")
            return _error_result("internal_error", "could not record authorization decision")

        if policy.decision is Decision.DENY:
            await self._outcome(
                correlation_id, agent, server, namespaced_name, redacted, Outcome.DENIED
            )
            return _error_result("policy_denied", policy.message or "denied by policy")
        if policy.decision is Decision.REQUIRE_APPROVAL:
            return await self._handle_approval(
                agent=agent,
                server=server,
                tool_name=tool_name,
                namespaced_name=namespaced_name,
                arguments=arguments,
                redacted=redacted,
                risk=risk,
                policy=policy,
                decision_correlation_id=correlation_id,
            )

        # --- forward (ALLOW) ---
        t0 = time.monotonic()
        try:
            async with self._sem(agent.id):
                result = await self._upstream.call_tool(server, tool_name, arguments)
        except GatewayError as exc:
            latency = int((time.monotonic() - t0) * 1000)
            await self._outcome(
                correlation_id, agent, server, namespaced_name, redacted, Outcome.ERROR, latency
            )
            return _error_result(exc.code, exc.public_message)

        latency = int((time.monotonic() - t0) * 1000)
        outcome = Outcome.ERROR if result.is_error else Outcome.SUCCESS
        await self._outcome(
            correlation_id, agent, server, namespaced_name, redacted, outcome, latency
        )
        return result

    # --- approval workflow (persisted one-time permit) ---
    async def _handle_approval(
        self,
        *,
        agent: Agent,
        server: MCPServer,
        tool_name: str,
        namespaced_name: str,
        arguments: dict[str, Any],
        redacted: dict,
        risk: Any,
        policy: Any,
        decision_correlation_id: uuid.UUID,
    ) -> CallToolResult:
        args_hash = canonical_args_hash(arguments)
        live = await self._manager.find_live(agent.id, server.id, tool_name, args_hash)
        if live is not None and ApprovalManager.is_expired(live):
            await self._manager.expire(live.id)
            live = None

        if live is None:
            ar, _created = await self._manager.create_pending(
                agent_id=agent.id,
                server_id=server.id,
                tool=tool_name,
                args_hash=args_hash,
                args_redacted=redacted,
                risk_score=risk.score,
                risk_band=risk.band.value,
            )
            return self._approval_required_result(ar)

        if live.status == ApprovalStatus.PENDING.value:
            return self._approval_required_result(live)

        # live.status == approved -> this is the post-approval retry.
        consumed = await self._manager.consume(live.id)
        if not consumed:
            # lost the race (concurrent retry already consumed it) -> replay reject
            return _error_result("replay_rejected", "this approval has already been used")
        return await self._execute_with_permit(
            agent, server, tool_name, namespaced_name, arguments, redacted, live,
            decision_correlation_id,
        )

    def _approval_required_result(self, ar: ApprovalRequest) -> CallToolResult:
        return _error_result(
            "approval_required",
            f"human approval required (approval_id={ar.id}); re-send the identical call "
            "once approved",
            structured={
                "status": "approval_required",
                "approval_id": str(ar.id),
                "risk_band": ar.risk_band,
                "expires_at": ar.expires_at.isoformat() if ar.expires_at else None,
            },
        )

    async def _execute_with_permit(
        self,
        agent: Agent,
        server: MCPServer,
        tool_name: str,
        namespaced_name: str,
        arguments: dict[str, Any],
        redacted: dict,
        approval: ApprovalRequest,
        corr: uuid.UUID,
    ) -> CallToolResult:
        execution = await self._manager.create_execution(
            permit_id=approval.id,
            correlation_id=approval.correlation_id,
            idempotency_key=str(approval.correlation_id),
        )
        # Persist EXECUTING *before* dispatch so a crash is detectable on restart.
        await self._manager.set_execution_state(
            execution.id, ExecutionState.EXECUTING, dispatched=True
        )

        t0 = time.monotonic()
        try:
            async with self._sem(agent.id):
                result = await self._upstream.call_tool(server, tool_name, arguments)
        except GatewayError:
            # Timeout or transport error: the upstream MAY have executed. Never
            # auto-retry; record UNKNOWN for manual reconciliation.
            latency = int((time.monotonic() - t0) * 1000)
            await self._manager.set_execution_state(
                execution.id, ExecutionState.UNKNOWN, outcome=Outcome.UNKNOWN, finished=True
            )
            await self._outcome(
                corr, agent, server, namespaced_name, redacted, Outcome.UNKNOWN, latency
            )
            return _error_result(
                "execution_unknown",
                "upstream outcome is unknown; recorded for manual reconciliation (not retried)",
            )

        latency = int((time.monotonic() - t0) * 1000)
        if result.is_error:
            await self._manager.set_execution_state(
                execution.id, ExecutionState.FAILED, outcome=Outcome.ERROR, finished=True
            )
            await self._outcome(
                corr, agent, server, namespaced_name, redacted, Outcome.ERROR, latency
            )
        else:
            await self._manager.set_execution_state(
                execution.id, ExecutionState.SUCCEEDED, outcome=Outcome.SUCCESS, finished=True
            )
            await self._outcome(
                corr, agent, server, namespaced_name, redacted, Outcome.SUCCESS, latency
            )
        return result

    # --- helpers ---
    async def _deny(
        self,
        correlation_id: uuid.UUID,
        agent: Agent,
        server: MCPServer | None,
        tool: str,
        redacted: dict,
        err: GatewayError,
    ) -> CallToolResult:
        try:
            await self._appender.append(
                event_type=AuditEventType.DECISION,
                correlation_id=correlation_id,
                agent_id=agent.id,
                server_id=server.id if server else None,
                tool=tool,
                args_redacted=redacted,
                decision=Decision.DENY.value,
                outcome=None,
            )
            await self._outcome(correlation_id, agent, server, tool, redacted, Outcome.DENIED)
        except Exception:
            logger.exception("audit write failed during deny")
        return _error_result(err.code, err.public_message)

    async def _outcome(
        self,
        correlation_id: uuid.UUID,
        agent: Agent,
        server: MCPServer | None,
        tool: str,
        redacted: dict,
        outcome: Outcome,
        latency_ms: int | None = None,
    ) -> None:
        try:
            await self._appender.append(
                event_type=AuditEventType.OUTCOME,
                correlation_id=correlation_id,
                agent_id=agent.id,
                server_id=server.id if server else None,
                tool=tool,
                args_redacted=redacted,
                outcome=outcome.value,
                latency_ms=latency_ms,
            )
        except Exception:
            logger.exception("audit outcome write failed (already executed)")
