"""Create arquivo, fatura, fatura_item and extracao tables.

Revision ID: 20261017_0008
Revises: 20261016_0007
Create Date: 2026-10-17 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261017_0008"
down_revision = "20261016_0007"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def _id() -> sa.Column[object]:
    return sa.Column("id", UUID, primary_key=True, nullable=False, default=uuid4)


def _tenant() -> sa.Column[object]:
    return sa.Column("organizacao_id", UUID, sa.ForeignKey("organizacao.id"), nullable=False)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "arquivo",
        _id(),
        _tenant(),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("nome_original", sa.String(255)),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("tamanho_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("criado_por", UUID, sa.ForeignKey("usuario.id")),
        *_timestamps(),
        sa.UniqueConstraint("organizacao_id", "sha256", name="uq_arquivo_org_sha256"),
    )
    op.create_index("ix_arquivo_organizacao_id", "arquivo", ["organizacao_id"])

    numeric_columns = [
        ("dc_ponta_kw", 14, 3),
        ("dc_fora_ponta_kw", 14, 3),
        ("dc_unica_kw", 14, 3),
        ("dm_ponta_kw", 14, 3),
        ("dm_fora_ponta_kw", 14, 3),
        ("consumo_ponta_kwh", 16, 3),
        ("consumo_fora_ponta_kwh", 16, 3),
        ("reativo_ponta_kvarh", 16, 3),
        ("reativo_fora_ponta_kvarh", 16, 3),
        ("fator_potencia", 5, 4),
        ("icms_aliquota", 7, 6),
        ("pis_aliquota", 7, 6),
        ("cofins_aliquota", 7, 6),
        ("valor_total", 16, 2),
    ]
    op.create_table(
        "fatura",
        _id(),
        _tenant(),
        sa.Column("uc_id", UUID, sa.ForeignKey("unidade_consumidora.id")),
        sa.Column("arquivo_id", UUID, sa.ForeignKey("arquivo.id")),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("origem", sa.String(16)),
        sa.Column("mes_referencia", sa.Date()),
        sa.Column("leitura_anterior", sa.Date()),
        sa.Column("leitura_atual", sa.Date()),
        sa.Column("dias_faturados", sa.Integer()),
        sa.Column("vencimento", sa.Date()),
        sa.Column("dados_extraidos", postgresql.JSONB()),
        sa.Column("confianca_minima", sa.Numeric(4, 3)),
        sa.Column("alertas", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("distribuidora_detectada_id", UUID, sa.ForeignKey("distribuidora.id")),
        sa.Column("hint_usado", sa.String(64)),
        *[sa.Column(name, sa.Numeric(p, s)) for name, p, s in numeric_columns[:-1]],
        sa.Column("bandeira", sa.String(24)),
        sa.Column("valor_total", sa.Numeric(16, 2)),
        sa.Column("validada_por", UUID, sa.ForeignKey("usuario.id")),
        sa.Column("validada_em", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("uc_id", "mes_referencia", name="uq_fatura_uc_mes"),
        sa.UniqueConstraint("organizacao_id", "idempotency_key", name="uq_fatura_org_idempotency"),
        sa.CheckConstraint(
            "status IN ('ENVIADA', 'EXTRAINDO', 'EXTRAIDA', 'EM_REVISAO', "
            "'VALIDADA', 'DIAGNOSTICADA', 'FALHA_EXTRACAO')",
            name="ck_fatura_status",
        ),
        sa.CheckConstraint(
            "origem IS NULL OR origem IN ('PDF_NATIVO', 'PDF_ESCANEADO', 'IMAGEM', 'MANUAL')",
            name="ck_fatura_origem",
        ),
    )
    op.create_index("ix_fatura_organizacao_id", "fatura", ["organizacao_id"])
    op.create_index("ix_fatura_uc_id", "fatura", ["uc_id"])

    op.create_table(
        "fatura_item",
        _id(),
        _tenant(),
        sa.Column("fatura_id", UUID, sa.ForeignKey("fatura.id"), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("descricao", sa.String(255), nullable=False),
        sa.Column("categoria", sa.String(40), nullable=False),
        sa.Column("posto", sa.String(16)),
        sa.Column("unidade", sa.String(16)),
        sa.Column("quantidade", sa.Numeric(18, 6)),
        sa.Column("tarifa_unitaria", sa.Numeric(18, 8)),
        sa.Column("valor", sa.Numeric(16, 2), nullable=False),
    )
    op.create_index("ix_fatura_item_organizacao_id", "fatura_item", ["organizacao_id"])
    op.create_index("ix_fatura_item_fatura_id", "fatura_item", ["fatura_id"])

    op.create_table(
        "extracao",
        _id(),
        _tenant(),
        sa.Column("fatura_id", UUID, sa.ForeignKey("fatura.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("modelo", sa.String(80), nullable=False),
        sa.Column("prompt_versao", sa.String(32), nullable=False),
        sa.Column("hint_usado", sa.String(64)),
        sa.Column("metodo", sa.String(16), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo_estimado", sa.Numeric(12, 6), nullable=False),
        sa.Column("latencia_ms", sa.Integer(), nullable=False),
        sa.Column("resultado", postgresql.JSONB(), nullable=False),
        sa.Column("validacoes", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_extracao_organizacao_id", "extracao", ["organizacao_id"])
    op.create_index("ix_extracao_fatura_id", "extracao", ["fatura_id"])


def downgrade() -> None:
    op.drop_table("extracao")
    op.drop_table("fatura_item")
    op.drop_table("fatura")
    op.drop_table("arquivo")
