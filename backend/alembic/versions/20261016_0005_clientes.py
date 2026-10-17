"""Create tenant-scoped customers.

Revision ID: 20261016_0005
Revises: 20261016_0004
Create Date: 2026-10-16 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_0005"
down_revision = "20261016_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cliente",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("razao_social", sa.String(length=255), nullable=False),
        sa.Column("nome_fantasia", sa.String(length=255), nullable=True),
        sa.Column("cnpj", sa.String(length=18), nullable=True),
        sa.Column("segmento", sa.String(length=40), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deletado_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.UniqueConstraint("organizacao_id", "cnpj", name="uq_cliente_organizacao_cnpj"),
    )
    op.create_index("ix_cliente_organizacao_id", "cliente", ["organizacao_id"], unique=False)
    op.create_index("ix_cliente_deletado_em", "cliente", ["deletado_em"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cliente_deletado_em", table_name="cliente")
    op.drop_index("ix_cliente_organizacao_id", table_name="cliente")
    op.drop_table("cliente")
