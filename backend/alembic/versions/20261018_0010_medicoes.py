"""Create tenant-scoped interval measurements.

Revision ID: 20261018_0010
Revises: 20261018_0009
Create Date: 2026-10-18 00:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261018_0010"
down_revision = "20261018_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medicao_intervalo",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ts_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intervalo_min", sa.Integer(), nullable=False),
        sa.Column("kwh_ativo", sa.Numeric(18, 6), nullable=False),
        sa.Column("kvarh_indutivo", sa.Numeric(18, 6), nullable=True),
        sa.Column("kvarh_capacitivo", sa.Numeric(18, 6), nullable=True),
        sa.Column("fonte", sa.String(24), nullable=False),
        sa.Column("arquivo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("intervalo_min IN (5, 15, 60)", name="ck_medicao_intervalo_min"),
        sa.CheckConstraint("kwh_ativo >= 0", name="ck_medicao_kwh_nao_negativo"),
        sa.CheckConstraint(
            "(kvarh_indutivo IS NULL OR kvarh_indutivo >= 0) "
            "AND (kvarh_capacitivo IS NULL OR kvarh_capacitivo >= 0)",
            name="ck_medicao_reativo_nao_negativo",
        ),
        sa.CheckConstraint(
            "fonte IN ('DISTRIBUIDORA', 'MEDIDOR_PARALELO')",
            name="ck_medicao_fonte",
        ),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uc_id"], ["unidade_consumidora.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["arquivo_id"], ["arquivo.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uc_id", "ts_inicio", name="uq_medicao_uc_inicio"),
    )
    op.create_index(
        "ix_medicao_organizacao_uc_ts",
        "medicao_intervalo",
        ["organizacao_id", "uc_id", "ts_inicio"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_medicao_organizacao_uc_ts", table_name="medicao_intervalo")
    op.drop_table("medicao_intervalo")
