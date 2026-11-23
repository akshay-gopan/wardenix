"""SQLAlchemy ORM models for Wardenix.

Enum-typed columns store the string ``.value`` (see :mod:`app.enums`). The
``audit_events`` table is append-only and tamper-evident (hash-chained); its
immutability is enforced at the DB level by a trigger created in the initial
migration, independent of these ORM definitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Identity & access
# --------------------------------------------------------------------------- #
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Agent(Base, TimestampMixin):
    """A caller identity. Authenticated via a hashed API key."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# --------------------------------------------------------------------------- #
# Upstream MCP servers & discovered tools
# --------------------------------------------------------------------------- #
class MCPServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)  # stdio | http
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # stdio transport
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    args: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    env: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # never logged

    # http transport
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # never logged

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    health: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)

    tools: Mapped[list[Tool]] = relationship(back_populates="server", cascade="all, delete-orphan")


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_tool_server_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sensitivity_tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    server: Mapped[MCPServer] = relationship(back_populates="tools")


# --------------------------------------------------------------------------- #
# Policies & rules
# --------------------------------------------------------------------------- #
class Policy(Base, TimestampMixin):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_action: Mapped[str] = mapped_column(String(32), default="deny", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    rules: Mapped[list[Rule]] = relationship(back_populates="policy", cascade="all, delete-orphan")


class Rule(Base, TimestampMixin):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # AND-ed condition set (agent/server/tool/arg matchers/min risk band)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # allow|deny|require_approval
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    policy: Mapped[Policy] = relationship(back_populates="rules")


# --------------------------------------------------------------------------- #
# Approvals & executions
# --------------------------------------------------------------------------- #
class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"
    __table_args__ = (
        # No duplicate *live* request for the same operation: retries of an
        # already pending/approved call never spawn a second row.
        Index(
            "uq_approval_live_op",
            "agent_id",
            "server_id",
            "tool",
            "args_hash",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
        Index(
            "ix_approval_lookup",
            "agent_id",
            "server_id",
            "tool",
            "args_hash",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(255), nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    args_redacted: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # One execution per permit ⇒ at-most-once dispatch.
    permit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="authorized", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Tamper-evident audit log (append-only; enforced by DB trigger)
# --------------------------------------------------------------------------- #
class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_correlation", "correlation_id"),
        Index("ix_audit_ts", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # decision | outcome
    agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    tool: Mapped[str | None] = mapped_column(String(255), nullable=True)
    args_redacted: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    matched_rule_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_signals: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
