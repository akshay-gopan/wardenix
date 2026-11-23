"""Request/response schemas and ORM→dict serializers for the Control Plane API."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.enums import Decision, Transport, UserRole


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: UserRole = UserRole.VIEWER


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    meta: dict[str, Any] = Field(default_factory=dict)


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport: Transport
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class ServerUpdate(BaseModel):
    enabled: bool | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    tags: list[str] | None = None


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    default_action: Decision = Decision.DENY


class PolicyUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    default_action: Decision | None = None


class RuleCreate(BaseModel):
    policy_id: uuid.UUID
    priority: int = 100
    enabled: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    action: Decision
    message: str | None = None


class RuleUpdate(BaseModel):
    priority: int | None = None
    enabled: bool | None = None
    conditions: dict[str, Any] | None = None
    action: Decision | None = None
    message: str | None = None


# --------------------------------------------------------------------------- #
# Serializers (ORM -> dict)
# --------------------------------------------------------------------------- #
def user_dict(u) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def agent_dict(a) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "enabled": a.enabled,
        "meta": a.meta,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def server_dict(s) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "transport": s.transport,
        "enabled": s.enabled,
        "command": s.command,
        "args": s.args,
        "url": s.url,
        "tags": s.tags,
        "health": s.health,
        # env/headers intentionally omitted (never exposed)
    }


def policy_dict(p, rules: list | None = None) -> dict:
    out = {
        "id": str(p.id),
        "name": p.name,
        "enabled": p.enabled,
        "default_action": p.default_action,
        "version": p.version,
    }
    if rules is not None:
        out["rules"] = [rule_dict(r) for r in rules]
    return out


def rule_dict(r) -> dict:
    return {
        "id": str(r.id),
        "policy_id": str(r.policy_id),
        "priority": r.priority,
        "enabled": r.enabled,
        "conditions": r.conditions,
        "action": r.action,
        "message": r.message,
    }
