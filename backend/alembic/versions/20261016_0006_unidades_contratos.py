"""Create consumer units and demand contracts.

Revision ID: 20261016_0006
Revises: 20261016_0005
Create Date: 2026-10-16 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_0006"
down_revision = "20261016_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unidade_consumidora",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("distribuidora_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("codigo_uc", sa.String(length=80), nullable=False),
        sa.Column("apelido", sa.String(length=255), nullable=True),
        sa.Column("uf", sa.String(length=2), nullable=False),
        sa.Column("municipio", sa.String(length=120), nullable=False),
        sa.Column("subgrupo", sa.String(length=8), nullable=False),
        sa.Column("tipo_rede", sa.String(length=16), nullable=False),
        sa.Column("ambiente", sa.String(length=16), nullable=False),
        sa.Column("tensao_kv", sa.Numeric(14, 3), nullable=True),
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
        sa.ForeignKeyConstraint(["cliente_id"], ["cliente.id"]),
        sa.ForeignKeyConstraint(["distribuidora_id"], ["distribuidora.id"]),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.UniqueConstraint(
            "distribuidora_id",
            "codigo_uc",
            "organizacao_id",
            name="uq_unidade_distribuidora_codigo_organizacao",
        ),
        sa.CheckConstraint(
            "subgrupo IN ('A1', 'A2', 'A3', 'A3a', 'A4', 'AS')",
            name="ck_unidade_subgrupo",
        ),
        sa.CheckConstraint(
            "tipo_rede IN ('AEREA', 'SUBTERRANEA')",
            name="ck_unidade_tipo_rede",
        ),
        sa.CheckConstraint(
            "(subgrupo = 'AS' AND tipo_rede = 'SUBTERRANEA') OR subgrupo <> 'AS'",
            name="ck_unidade_as_subterranea",
        ),
        sa.CheckConstraint(
            "ambiente IN ('CATIVO', 'LIVRE')",
            name="ck_unidade_ambiente",
        ),
    )
    op.create_index("ix_unidade_consumidora_cliente_id", "unidade_consumidora", ["cliente_id"])
    op.create_index(
        "ix_unidade_consumidora_distribuidora_id",
        "unidade_consumidora",
        ["distribuidora_id"],
    )
    op.create_index(
        "ix_unidade_consumidora_organizacao_id",
        "unidade_consumidora",
        ["organizacao_id"],
    )
    op.create_index(
        "ix_unidade_consumidora_deletado_em",
        "unidade_consumidora",
        ["deletado_em"],
    )

    op.create_table(
        "contrato_demanda",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("uc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modalidade", sa.String(length=16), nullable=False),
        sa.Column("demanda_ponta_kw", sa.Numeric(14, 3), nullable=True),
        sa.Column("demanda_fora_ponta_kw", sa.Numeric(14, 3), nullable=True),
        sa.Column("demanda_unica_kw", sa.Numeric(14, 3), nullable=True),
        sa.Column("vigencia_inicio", sa.Date(), nullable=False),
        sa.Column("vigencia_fim", sa.Date(), nullable=True),
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
        sa.ForeignKeyConstraint(["uc_id"], ["unidade_consumidora.id"]),
        sa.CheckConstraint(
            "modalidade IN ('AZUL', 'VERDE', 'CONVENCIONAL')",
            name="ck_contrato_modalidade",
        ),
        sa.CheckConstraint(
            "(modalidade = 'AZUL' AND demanda_ponta_kw IS NOT NULL "
            "AND demanda_fora_ponta_kw IS NOT NULL AND demanda_unica_kw IS NULL) "
            "OR (modalidade IN ('VERDE', 'CONVENCIONAL') "
            "AND demanda_unica_kw IS NOT NULL AND demanda_ponta_kw IS NULL "
            "AND demanda_fora_ponta_kw IS NULL)",
            name="ck_contrato_demanda_por_modalidade",
        ),
        sa.CheckConstraint(
            "(demanda_ponta_kw IS NULL OR demanda_ponta_kw >= 30) "
            "AND (demanda_fora_ponta_kw IS NULL OR demanda_fora_ponta_kw >= 30) "
            "AND (demanda_unica_kw IS NULL OR demanda_unica_kw >= 30)",
            name="ck_contrato_demanda_minima",
        ),
        sa.CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_contrato_vigencia",
        ),
    )
    op.create_index("ix_contrato_demanda_uc_id", "contrato_demanda", ["uc_id"])


def downgrade() -> None:
    op.drop_index("ix_contrato_demanda_uc_id", table_name="contrato_demanda")
    op.drop_table("contrato_demanda")
    op.drop_index("ix_unidade_consumidora_deletado_em", table_name="unidade_consumidora")
    op.drop_index("ix_unidade_consumidora_organizacao_id", table_name="unidade_consumidora")
    op.drop_index("ix_unidade_consumidora_distribuidora_id", table_name="unidade_consumidora")
    op.drop_index("ix_unidade_consumidora_cliente_id", table_name="unidade_consumidora")
    op.drop_table("unidade_consumidora")
