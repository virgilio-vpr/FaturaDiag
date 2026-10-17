"""Create ACL simulations and diagnostic notes.

Revision ID: 20261018_0012
Revises: 20261018_0011
Create Date: 2026-10-18 00:12:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261018_0012"
down_revision = "20261018_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("diagnostico", sa.Column("notas", sa.Text(), nullable=True))
    op.create_table(
        "simulacao_acl",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnostico_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cenario", sa.String(16), nullable=False),
        sa.Column("premissas", postgresql.JSONB(), nullable=False),
        sa.Column("resultado", postgresql.JSONB(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cenario IN ('CONSERVADOR', 'BASE', 'OTIMISTA')", name="ck_simulacao_acl_cenario"
        ),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.ForeignKeyConstraint(["diagnostico_id"], ["diagnostico.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulacao_acl_organizacao_id", "simulacao_acl", ["organizacao_id"])
    op.create_index("ix_simulacao_acl_diagnostico_id", "simulacao_acl", ["diagnostico_id"])


def downgrade() -> None:
    op.drop_table("simulacao_acl")
    op.drop_column("diagnostico", "notas")
