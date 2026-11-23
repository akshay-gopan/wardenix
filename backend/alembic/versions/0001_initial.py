"""initial schema

Creates all core tables from the ORM metadata, then installs the DB-level
append-only guard on ``audit_events`` (a BEFORE UPDATE/DELETE trigger that
rejects every mutation, for any role including the table owner).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.models import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION wardenix_audit_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
END;
$$;
"""

_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION wardenix_audit_append_only();
"""

# Row-level triggers do not fire on TRUNCATE, so guard it separately at the
# statement level — otherwise the audit log could be wiped wholesale.
_NO_TRUNCATE_TRIGGER = """
CREATE TRIGGER audit_events_no_truncate
BEFORE TRUNCATE ON audit_events
FOR EACH STATEMENT EXECUTE FUNCTION wardenix_audit_append_only();
"""


def upgrade() -> None:
    bind = op.get_bind()
    # The initial migration materializes the full ORM metadata (single source of
    # truth). Subsequent migrations are incremental autogenerate diffs.
    Base.metadata.create_all(bind=bind)
    op.execute(_APPEND_ONLY_FN)
    op.execute(_APPEND_ONLY_TRIGGER)
    op.execute(_NO_TRUNCATE_TRIGGER)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS wardenix_audit_append_only();")
    Base.metadata.drop_all(bind=bind)
