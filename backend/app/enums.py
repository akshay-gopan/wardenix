"""Domain enums, stored as their string ``.value`` in the database.

Using string-backed enums (rather than native PostgreSQL enum types) keeps
migrations simple and makes values forward-compatible without ``ALTER TYPE``.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    APPROVER = "approver"
    VIEWER = "viewer"


class Transport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


class Decision(StrEnum):
    """Outcome of policy evaluation and the effect of a rule."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CONSUMED = "consumed"
    DENIED = "denied"
    EXPIRED = "expired"


class ExecutionState(StrEnum):
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"


class AuditEventType(StrEnum):
    DECISION = "decision"
    OUTCOME = "outcome"


class Outcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
