"""Deterministic policy evaluation with fixed precedence and fail-closed behavior.

All enabled rules (across enabled policies) are matched against the call; then a
single decision is chosen by precedence:

    explicit DENY  >  REQUIRE_APPROVAL  >  explicit ALLOW  >  default (DENY)

Any error during evaluation (bad/oversized regex, malformed condition, DB
failure) results in **DENY** — the engine never fails open. ``tools/list``
filtering is UX only; this runs on every call regardless of list visibility.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Policy, Rule
from app.enums import Decision, RiskBand
from app.security.rexafe import search as regex_search

logger = logging.getLogger("wardenix.policy")

_BAND_ORDER = {RiskBand.LOW: 0, RiskBand.MEDIUM: 1, RiskBand.HIGH: 2, RiskBand.CRITICAL: 3}
_MISSING = object()


@dataclass(frozen=True)
class EvaluationContext:
    agent_id: uuid.UUID
    agent_name: str
    server_name: str
    tool_name: str
    arguments: dict
    risk_band: RiskBand


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    matched_rule_id: uuid.UUID | None = None
    message: str | None = None


# --------------------------------------------------------------------------- #
# Condition matching (pure; raises on malformed input so the caller can fail closed)
# --------------------------------------------------------------------------- #
def _resolve_path(arguments: dict, dotted: str) -> Any:
    cur: Any = arguments
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _match_arg(matcher: dict, arguments: dict) -> bool:
    key = matcher["key"]
    op = matcher["op"]
    value = _resolve_path(arguments, key)

    if op == "exists":
        return value is not _MISSING
    if value is _MISSING:
        return False
    if op == "equals":
        return value == matcher["value"]
    if op == "in":
        return value in matcher["value"]
    if op == "contains":
        target = matcher["value"]
        if isinstance(value, str):
            return str(target) in value
        if isinstance(value, (list, tuple, set)):
            return target in value
        return False
    if op == "regex":
        return regex_search(matcher["value"], str(value))
    raise ValueError(f"unknown argument operator {op!r}")


def rule_matches(conditions: dict | None, ctx: EvaluationContext) -> bool:
    conditions = conditions or {}

    agents = conditions.get("agents")
    if agents is not None and ctx.agent_name not in agents:
        return False

    servers = conditions.get("servers")
    if servers is not None and not any(fnmatchcase(ctx.server_name, g) for g in servers):
        return False

    tools = conditions.get("tools")
    if tools is not None and not any(fnmatchcase(ctx.tool_name, g) for g in tools):
        return False

    min_band = conditions.get("min_risk_band")
    if min_band is not None:
        if _BAND_ORDER[ctx.risk_band] < _BAND_ORDER[RiskBand(min_band)]:
            return False

    for matcher in conditions.get("args", []) or []:
        if not _match_arg(matcher, ctx.arguments):
            return False

    return True


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
async def evaluate(session: AsyncSession, ctx: EvaluationContext) -> PolicyResult:
    try:
        return await _evaluate(session, ctx)
    except Exception:
        logger.exception("policy evaluation failed; failing closed (DENY)")
        return PolicyResult(Decision.DENY, None, "policy evaluation error (fail-closed)")


async def _evaluate(session: AsyncSession, ctx: EvaluationContext) -> PolicyResult:
    stmt = (
        select(Rule)
        .join(Policy, Rule.policy_id == Policy.id)
        .where(Policy.enabled.is_(True), Rule.enabled.is_(True))
        .order_by(Rule.priority.asc())
    )
    rules = (await session.execute(stmt)).scalars().all()
    matched = [r for r in rules if rule_matches(r.conditions, ctx)]

    def first(action: Decision) -> Rule | None:
        return next((r for r in matched if r.action == action.value), None)

    deny = first(Decision.DENY)
    if deny is not None:
        return PolicyResult(Decision.DENY, deny.id, deny.message or "denied by policy")

    approval = first(Decision.REQUIRE_APPROVAL)
    if approval is not None:
        return PolicyResult(
            Decision.REQUIRE_APPROVAL, approval.id, approval.message or "approval required"
        )

    allow = first(Decision.ALLOW)
    if allow is not None:
        return PolicyResult(Decision.ALLOW, allow.id, allow.message or "allowed by policy")

    default = get_settings().default_action
    return PolicyResult(default, None, f"no matching rule (default: {default.value})")
