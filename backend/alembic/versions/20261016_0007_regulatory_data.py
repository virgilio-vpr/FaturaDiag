"""Create tariff, regulatory parameter, and distributor hint tables.

Revision ID: 20261016_0007
Revises: 20261016_0006
Create Date: 2026-10-16 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_0007"
down_revision = "20261016_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tarifa",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("distribuidora_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subgrupo", sa.String(length=8), nullable=False),
        sa.Column("modalidade", sa.String(length=16), nullable=False),
        sa.Column("posto", sa.String(length=16), nullable=False),
        sa.Column("componente", sa.String(length=24), nullable=False),
        sa.Column("unidade", sa.String(length=16), nullable=False),
        sa.Column("valor", sa.Numeric(18, 6), nullable=False),
        sa.Column("vigencia_inicio", sa.Date(), nullable=False),
        sa.Column("vigencia_fim", sa.Date(), nullable=True),
        sa.Column("resolucao_homologatoria", sa.String(length=255), nullable=True),
        sa.Column("fonte", sa.Text(), nullable=False),
        sa.Column(
            "importado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["distribuidora_id"], ["distribuidora.id"]),
        sa.UniqueConstraint(
            "distribuidora_id",
            "subgrupo",
            "modalidade",
            "posto",
            "componente",
            "vigencia_inicio",
            name="uq_tarifa_versao",
        ),
        sa.CheckConstraint(
            "modalidade IN ('AZUL', 'VERDE', 'CONVENCIONAL')",
            name="ck_tarifa_modalidade",
        ),
        sa.CheckConstraint("posto IN ('PONTA', 'FORA_PONTA', 'UNICO')", name="ck_tarifa_posto"),
        sa.CheckConstraint(
            "componente IN ('TUSD_DEMANDA', 'TUSD_CONSUMO', 'TE_CONSUMO')",
            name="ck_tarifa_componente",
        ),
        sa.CheckConstraint("unidade IN ('RS_KW', 'RS_MWH')", name="ck_tarifa_unidade"),
        sa.CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_tarifa_vigencia",
        ),
    )
    op.create_index("ix_tarifa_distribuidora_id", "tarifa", ["distribuidora_id"])

    op.create_table(
        "bandeira_tarifaria",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("mes_referencia", sa.Date(), nullable=False),
        sa.Column("bandeira", sa.String(length=16), nullable=False),
        sa.Column("adicional_rs_mwh", sa.Numeric(18, 6), nullable=False),
        sa.Column("fonte", sa.Text(), nullable=False),
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
            "bandeira IN ('VERDE', 'AMARELA', 'VERMELHA_1', 'VERMELHA_2')",
            name="ck_bandeira_tarifaria_bandeira",
        ),
    )

    op.create_table(
        "parametro_regulatorio",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("chave", sa.String(length=120), nullable=False),
        sa.Column("valor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vigencia_inicio", sa.Date(), nullable=False),
        sa.Column("vigencia_fim", sa.Date(), nullable=True),
        sa.Column("fonte", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="VALIDAR", nullable=False),
        sa.Column("validado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validado_em", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["validado_por"], ["usuario.id"]),
        sa.UniqueConstraint("chave", "vigencia_inicio", name="uq_parametro_regulatorio_versao"),
        sa.CheckConstraint(
            "status IN ('VALIDADO', 'VALIDAR')",
            name="ck_parametro_regulatorio_status",
        ),
        sa.CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_parametro_regulatorio_vigencia",
        ),
    )

    op.create_table(
        "hint_distribuidora",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4
        ),
        sa.Column("distribuidora_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("versao", sa.String(length=32), nullable=False),
        sa.Column("arquivo_md", sa.Text(), nullable=False),
        sa.Column("vigencia_inicio", sa.Date(), nullable=False),
        sa.Column("vigencia_fim", sa.Date(), nullable=True),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(["distribuidora_id"], ["distribuidora.id"]),
        sa.UniqueConstraint("distribuidora_id", "versao", name="uq_hint_distribuidora_versao"),
        sa.CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_hint_distribuidora_vigencia",
        ),
    )
    op.create_index(
        "ix_hint_distribuidora_distribuidora_id",
        "hint_distribuidora",
        ["distribuidora_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hint_distribuidora_distribuidora_id", table_name="hint_distribuidora")
    op.drop_table("hint_distribuidora")
    op.drop_table("parametro_regulatorio")
    op.drop_table("bandeira_tarifaria")
    op.drop_index("ix_tarifa_distribuidora_id", table_name="tarifa")
    op.drop_table("tarifa")
