"""Policy engine: condition matching, precedence matrix, fail-closed, default-deny."""

from __future__ import annotations

import uuid

import pytest

from app.db.models import Policy, Rule
from app.enums import Decision, RiskBand
from app.policy.engine import EvaluationContext, evaluate, rule_matches


def _ctx(**over) -> EvaluationContext:
    base = dict(
        agent_id=uuid.uuid4(),
        agent_name="agent-a",
        server_name="fs",
        tool_name="read_file",
        arguments={},
        risk_band=RiskBand.LOW,
    )
    base.update(over)
    return EvaluationContext(**base)


async def _seed(sessionmaker, rules: list[dict]) -> None:
    async with sessionmaker() as s:
        policy = Policy(name="p", default_action="deny")
        s.add(policy)
        await s.commit()
        await s.refresh(policy)
        for r in rules:
            s.add(
                Rule(
                    policy_id=policy.id,
                    action=r["action"],
                    conditions=r.get("conditions", {}),
                    priority=r.get("priority", 100),
                    enabled=r.get("enabled", True),
                    message=r.get("message"),
                )
            )
        await s.commit()


# --------------------------------------------------------------------------- #
# Pure matching
# --------------------------------------------------------------------------- #
def test_empty_conditions_match_everything():
    assert rule_matches({}, _ctx()) is True
    assert rule_matches(None, _ctx()) is True


def test_agent_server_tool_globs():
    c = {"servers": ["fs*"], "tools": ["read_*"], "agents": ["agent-a"]}
    assert rule_matches(c, _ctx()) is True
    assert rule_matches(c, _ctx(server_name="net")) is False
    assert rule_matches(c, _ctx(tool_name="delete_file")) is False
    assert rule_matches(c, _ctx(agent_name="other")) is False


def test_min_risk_band():
    c = {"min_risk_band": "high"}
    assert rule_matches(c, _ctx(risk_band=RiskBand.CRITICAL)) is True
    assert rule_matches(c, _ctx(risk_band=RiskBand.HIGH)) is True
    assert rule_matches(c, _ctx(risk_band=RiskBand.MEDIUM)) is False


def test_arg_matchers():
    assert (
        rule_matches(
            {"args": [{"key": "mode", "op": "equals", "value": "rw"}]},
            _ctx(arguments={"mode": "rw"}),
        )
        is True
    )
    assert (
        rule_matches({"args": [{"key": "a.b", "op": "exists"}]}, _ctx(arguments={"a": {"b": 1}}))
        is True
    )
    assert (
        rule_matches(
            {"args": [{"key": "x", "op": "in", "value": [1, 2]}]}, _ctx(arguments={"x": 2})
        )
        is True
    )
    assert (
        rule_matches(
            {"args": [{"key": "p", "op": "regex", "value": r"^/etc/"}]},
            _ctx(arguments={"p": "/etc/passwd"}),
        )
        is True
    )
    assert (
        rule_matches(
            {"args": [{"key": "p", "op": "regex", "value": r"^/etc/"}]},
            _ctx(arguments={"p": "/home/x"}),
        )
        is False
    )


# --------------------------------------------------------------------------- #
# Precedence matrix (DENY > REQUIRE_APPROVAL > ALLOW > default DENY)
# --------------------------------------------------------------------------- #
async def test_default_deny_when_no_rules(sessionmaker):
    async with sessionmaker() as s:
        result = await evaluate(s, _ctx())
    assert result.decision is Decision.DENY


@pytest.mark.parametrize(
    "actions,expected",
    [
        (["allow"], Decision.ALLOW),
        (["allow", "deny"], Decision.DENY),
        (["allow", "require_approval"], Decision.REQUIRE_APPROVAL),
        (["allow", "require_approval", "deny"], Decision.DENY),
        (["require_approval"], Decision.REQUIRE_APPROVAL),
        ([], Decision.DENY),  # default
    ],
)
async def test_precedence_matrix(sessionmaker, actions, expected):
    await _seed(sessionmaker, [{"action": a, "conditions": {}} for a in actions])
    async with sessionmaker() as s:
        result = await evaluate(s, _ctx())
    assert result.decision is expected


async def test_non_matching_rule_falls_through_to_default_deny(sessionmaker):
    await _seed(sessionmaker, [{"action": "allow", "conditions": {"servers": ["other"]}}])
    async with sessionmaker() as s:
        result = await evaluate(s, _ctx(server_name="fs"))
    assert result.decision is Decision.DENY


async def test_disabled_rule_ignored(sessionmaker):
    await _seed(sessionmaker, [{"action": "allow", "conditions": {}, "enabled": False}])
    async with sessionmaker() as s:
        result = await evaluate(s, _ctx())
    assert result.decision is Decision.DENY


# --------------------------------------------------------------------------- #
# Fail-closed
# --------------------------------------------------------------------------- #
async def test_bad_regex_condition_fails_closed(sessionmaker):
    # An allow rule whose regex is invalid must not fail open.
    bad = {"args": [{"key": "p", "op": "regex", "value": "(unclosed"}]}
    await _seed(sessionmaker, [{"action": "allow", "conditions": bad}])
    async with sessionmaker() as s:
        result = await evaluate(s, _ctx(arguments={"p": "anything"}))
    assert result.decision is Decision.DENY
    assert "fail-closed" in (result.message or "")
