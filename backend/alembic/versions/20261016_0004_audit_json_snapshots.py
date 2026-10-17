"""Store structured audit snapshots as JSONB.

Revision ID: 20261016_0004
Revises: 20261014_0003
Create Date: 2026-10-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_0004"
down_revision = "20261014_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_log",
        "antes",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="to_jsonb(antes)",
    )
    op.alter_column(
        "audit_log",
        "depois",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="to_jsonb(depois)",
    )
    op.execute("UPDATE audit_log SET ts = CURRENT_TIMESTAMP WHERE ts IS NULL")
    op.alter_column(
        "audit_log",
        "ts",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.create_index(
        "ix_audit_log_organizacao_ts",
        "audit_log",
        ["organizacao_id", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_organizacao_ts", table_name="audit_log")
    op.alter_column(
        "audit_log",
        "ts",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "audit_log",
        "antes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="antes::text",
    )
    op.alter_column(
        "audit_log",
        "depois",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="depois::text",
    )
