"""Audit hash-chain: determinism, append+verify, and tamper detection."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.audit.appender import AuditAppender, verify_chain
from app.audit.chain import GENESIS_HASH, build_payload, compute_entry_hash
from app.enums import AuditEventType


def _sample_payload(**over):
    base = dict(
        correlation_id=uuid.UUID(int=1),
        ts=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC),
        event_type="decision",
        agent_id=None,
        server_id=None,
        tool="fake.echo",
        args_redacted={"b": 2, "a": 1},
        decision="allow",
        matched_rule_id=None,
        risk_score=0,
        risk_band="low",
        risk_signals={},
        outcome=None,
        latency_ms=None,
    )
    base.update(over)
    return build_payload(**base)


def test_hash_is_deterministic_and_order_independent():
    # key order in args must not change the hash (canonical JSON sorts keys)
    h1 = compute_entry_hash(_sample_payload(args_redacted={"a": 1, "b": 2}), GENESIS_HASH)
    h2 = compute_entry_hash(_sample_payload(args_redacted={"b": 2, "a": 1}), GENESIS_HASH)
    assert h1 == h2


def test_hash_changes_with_prev():
    h1 = compute_entry_hash(_sample_payload(), GENESIS_HASH)
    h2 = compute_entry_hash(_sample_payload(), "a" * 64)
    assert h1 != h2


async def test_append_and_verify_ok(sessionmaker):
    appender = AuditAppender(sessionmaker)
    cid = uuid.uuid4()
    await appender.append(event_type=AuditEventType.DECISION, correlation_id=cid, decision="allow")
    await appender.append(
        event_type=AuditEventType.OUTCOME, correlation_id=cid, outcome="success", latency_ms=5
    )
    await appender.append(event_type=AuditEventType.DECISION, correlation_id=uuid.uuid4())

    result = await verify_chain(sessionmaker)
    assert result["ok"] is True
    assert result["count"] == 3


async def test_verify_detects_tampering(sessionmaker):
    appender = AuditAppender(sessionmaker)
    cid = uuid.uuid4()
    await appender.append(event_type=AuditEventType.DECISION, correlation_id=cid, decision="allow")
    await appender.append(event_type=AuditEventType.DECISION, correlation_id=cid, decision="allow")

    # Tamper by bypassing the append-only trigger (owner-only operation).
    async with sessionmaker() as s:
        await s.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only"))
        await s.execute(
            text(
                "UPDATE audit_events SET decision='deny' "
                "WHERE seq=(SELECT min(seq) FROM audit_events)"
            )
        )
        await s.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))
        await s.commit()

    result = await verify_chain(sessionmaker)
    assert result["ok"] is False
    assert result["first_bad_seq"] is not None
