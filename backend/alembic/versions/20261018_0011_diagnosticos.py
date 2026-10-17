"""Create diagnostics and findings.

Revision ID: 20261018_0011
Revises: 20261018_0010
Create Date: 2026-10-18 00:11:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261018_0011"
down_revision = "20261018_0010"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "diagnostico",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("escopo", sa.String(16), nullable=False),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fim", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), server_default="RASCUNHO", nullable=False),
        sa.Column("versao_motor", sa.String(16), nullable=False),
        sa.Column("insumos_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("parametros_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("resultado", postgresql.JSONB(), nullable=False),
        sa.Column("economia_mensal_estimada", sa.Numeric(16, 2), nullable=False),
        sa.Column("economia_anual_estimada", sa.Numeric(16, 2), nullable=False),
        sa.Column("criado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revisado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revisado_em", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("escopo IN ('FATURA_UNICA', 'HISTORICO')", name="ck_diagnostico_escopo"),
        sa.CheckConstraint(
            "status IN ('RASCUNHO', 'REVISADO', 'PUBLICADO', 'STALE')",
            name="ck_diagnostico_status",
        ),
        sa.CheckConstraint("periodo_fim >= periodo_inicio", name="ck_diagnostico_periodo"),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.ForeignKeyConstraint(["uc_id"], ["unidade_consumidora.id"]),
        sa.ForeignKeyConstraint(["criado_por"], ["usuario.id"]),
        sa.ForeignKeyConstraint(["revisado_por"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organizacao_id", "idempotency_key", name="uq_diagnostico_org_idempotency"
        ),
    )
    op.create_index("ix_diagnostico_organizacao_id", "diagnostico", ["organizacao_id"])
    op.create_index(
        "ix_diagnostico_organizacao_uc",
        "diagnostico",
        ["organizacao_id", "uc_id", "periodo_inicio"],
    )
    op.create_table(
        "diagnostico_achado",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnostico_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(48), nullable=False),
        sa.Column("severidade", sa.String(8), nullable=False),
        sa.Column("titulo", sa.String(255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("economia_anual", sa.Numeric(16, 2), nullable=True),
        sa.Column("recomendacao", sa.Text(), nullable=False),
        sa.Column("evidencias", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("premissas", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("trace", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "severidade IN ('INFO', 'BAIXA', 'MEDIA', 'ALTA')",
            name="ck_diagnostico_achado_severidade",
        ),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.ForeignKeyConstraint(["diagnostico_id"], ["diagnostico.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnostico_achado_organizacao_id", "diagnostico_achado", ["organizacao_id"]
    )
    op.create_index(
        "ix_diagnostico_achado_diagnostico_id", "diagnostico_achado", ["diagnostico_id"]
    )


def downgrade() -> None:
    op.drop_table("diagnostico_achado")
    op.drop_table("diagnostico")
