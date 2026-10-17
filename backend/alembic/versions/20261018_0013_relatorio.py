"""Create report versions.

Revision ID: 20261018_0013
Revises: 20261018_0012
Create Date: 2026-10-18 00:13:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261018_0013"
down_revision = "20261018_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relatorio",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnostico_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("arquivo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("gerado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "gerado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.ForeignKeyConstraint(["diagnostico_id"], ["diagnostico.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["arquivo_id"], ["arquivo.id"]),
        sa.ForeignKeyConstraint(["gerado_por"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagnostico_id", "versao", name="uq_relatorio_diagnostico_versao"),
    )
    op.create_index("ix_relatorio_organizacao_id", "relatorio", ["organizacao_id"])
    op.create_index("ix_relatorio_diagnostico_id", "relatorio", ["diagnostico_id"])


def downgrade() -> None:
    op.drop_table("relatorio")
