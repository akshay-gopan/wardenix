"""Policy + rule management with YAML import/export. Read: viewer+. Write: admin.

Rule regex conditions are validated at save time with the ReDoS-safe engine.
"""

from __future__ import annotations

import uuid

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_viewer
from app.db.models import Policy, Rule
from app.db.session import get_session
from app.schemas import (
    PolicyCreate,
    PolicyUpdate,
    RuleCreate,
    RuleUpdate,
    policy_dict,
    rule_dict,
)
from app.security.rexafe import UnsafeRegex, validate_pattern

router = APIRouter(prefix="/api/policies", tags=["policies"])


def _validate_conditions(conditions: dict) -> None:
    for matcher in (conditions or {}).get("args", []) or []:
        if matcher.get("op") == "regex":
            try:
                validate_pattern(str(matcher.get("value", "")))
            except UnsafeRegex as exc:
                raise HTTPException(status_code=400, detail=f"unsafe regex: {exc}") from exc


async def _rules_for(session: AsyncSession, policy_id: uuid.UUID) -> list[Rule]:
    return list(
        (
            await session.execute(
                select(Rule).where(Rule.policy_id == policy_id).order_by(Rule.priority)
            )
        )
        .scalars()
        .all()
    )


# --- policies ---
@router.get("", dependencies=[Depends(require_viewer)])
async def list_policies(session: AsyncSession = Depends(get_session)) -> list[dict]:
    policies = (await session.execute(select(Policy).order_by(Policy.name))).scalars().all()
    return [policy_dict(p, await _rules_for(session, p.id)) for p in policies]


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def create_policy(body: PolicyCreate, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.scalar(select(Policy).where(Policy.name == body.name)):
        raise HTTPException(status_code=409, detail="policy name already exists")
    policy = Policy(
        name=body.name, enabled=body.enabled, default_action=body.default_action.value
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy_dict(policy, [])


@router.patch("/{policy_id}", dependencies=[Depends(require_admin)])
async def update_policy(
    policy_id: uuid.UUID, body: PolicyUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    policy = await session.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="policy not found")
    data = body.model_dump(exclude_unset=True)
    if "default_action" in data and data["default_action"] is not None:
        policy.default_action = data["default_action"].value
    if "name" in data and data["name"] is not None:
        policy.name = data["name"]
    if "enabled" in data and data["enabled"] is not None:
        policy.enabled = data["enabled"]
    await session.commit()
    await session.refresh(policy)
    return policy_dict(policy, await _rules_for(session, policy.id))


@router.delete("/{policy_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_policy(policy_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    policy = await session.get(Policy, policy_id)
    if policy is not None:
        await session.delete(policy)
        await session.commit()


# --- rules ---
@router.post("/rules", status_code=201, dependencies=[Depends(require_admin)])
async def create_rule(body: RuleCreate, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Policy, body.policy_id) is None:
        raise HTTPException(status_code=404, detail="policy not found")
    _validate_conditions(body.conditions)
    rule = Rule(
        policy_id=body.policy_id,
        priority=body.priority,
        enabled=body.enabled,
        conditions=body.conditions,
        action=body.action.value,
        message=body.message,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule_dict(rule)


@router.patch("/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def update_rule(
    rule_id: uuid.UUID, body: RuleUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("conditions") is not None:
        _validate_conditions(data["conditions"])
        rule.conditions = data["conditions"]
    if data.get("action") is not None:
        rule.action = data["action"].value
    for field in ("priority", "enabled", "message"):
        if field in data and data[field] is not None:
            setattr(rule, field, data[field])
    await session.commit()
    await session.refresh(rule)
    return rule_dict(rule)


@router.delete("/rules/{rule_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_rule(rule_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    rule = await session.get(Rule, rule_id)
    if rule is not None:
        await session.delete(rule)
        await session.commit()


# --- YAML import / export ---
@router.get("/export", dependencies=[Depends(require_viewer)])
async def export_yaml(session: AsyncSession = Depends(get_session)) -> Response:
    policies = (await session.execute(select(Policy).order_by(Policy.name))).scalars().all()
    doc = {
        "policies": [
            {
                "name": p.name,
                "enabled": p.enabled,
                "default_action": p.default_action,
                "rules": [
                    {
                        "priority": r.priority,
                        "enabled": r.enabled,
                        "action": r.action,
                        "message": r.message,
                        "conditions": r.conditions,
                    }
                    for r in await _rules_for(session, p.id)
                ],
            }
            for p in policies
        ]
    }
    return Response(content=yaml.safe_dump(doc, sort_keys=False), media_type="application/x-yaml")


@router.post("/import", dependencies=[Depends(require_admin)])
async def import_yaml(
    body: str = Body(..., media_type="text/plain"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        doc = yaml.safe_load(body) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {exc}") from exc
    created = 0
    for pdef in doc.get("policies", []):
        existing = await session.scalar(select(Policy).where(Policy.name == pdef["name"]))
        if existing is not None:
            await session.delete(existing)  # replace-by-name
            await session.flush()
        policy = Policy(
            name=pdef["name"],
            enabled=pdef.get("enabled", True),
            default_action=pdef.get("default_action", "deny"),
        )
        session.add(policy)
        await session.flush()
        for rdef in pdef.get("rules", []):
            _validate_conditions(rdef.get("conditions", {}))
            session.add(
                Rule(
                    policy_id=policy.id,
                    priority=rdef.get("priority", 100),
                    enabled=rdef.get("enabled", True),
                    conditions=rdef.get("conditions", {}),
                    action=rdef["action"],
                    message=rdef.get("message"),
                )
            )
        created += 1
    await session.commit()
    return {"imported_policies": created}
