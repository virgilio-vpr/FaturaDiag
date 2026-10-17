"""Add global distributor and national-holiday catalogs.

Revision ID: 20261014_0003
Revises: 20261014_0002
Create Date: 2026-10-14 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_0003"
down_revision = "20261014_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distribuidora",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("sigla", sa.String(length=40), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("cnpj", sa.String(length=18), nullable=True),
        sa.Column("codigo_aneel", sa.String(length=32), nullable=True),
        sa.Column("ufs", postgresql.ARRAY(sa.String(length=2)), nullable=False),
        sa.Column("ponta_inicio", sa.Time(), nullable=True),
        sa.Column("ponta_fim", sa.Time(), nullable=True),
        sa.Column("ponta_status", sa.String(length=16), server_default="VALIDAR", nullable=False),
        sa.Column("tem_hint", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint(
            "ponta_status IN ('VALIDAR', 'VALIDADO')",
            name="ck_distribuidora_ponta_status",
        ),
        sa.CheckConstraint(
            "(ponta_inicio IS NULL AND ponta_fim IS NULL) "
            "OR (ponta_inicio IS NOT NULL AND ponta_fim IS NOT NULL)",
            name="ck_distribuidora_ponta_window",
        ),
        sa.UniqueConstraint("sigla", name="uq_distribuidora_sigla"),
    )
    op.create_table(
        "feriado_nacional",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=False),
        sa.Column("vale_para_ponta", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.UniqueConstraint("data", name="uq_feriado_nacional_data"),
    )


def downgrade() -> None:
    op.drop_table("feriado_nacional")
    op.drop_table("distribuidora")
