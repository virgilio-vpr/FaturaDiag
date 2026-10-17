"""Add identification columns (UC code, subgroup, modality, network type) to fatura.

Revision ID: 20261018_0009
Revises: 20261017_0008
Create Date: 2026-10-18 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261018_0009"
down_revision = "20261017_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fatura", sa.Column("codigo_uc", sa.String(80)))
    op.add_column("fatura", sa.Column("subgrupo", sa.String(8)))
    op.add_column("fatura", sa.Column("modalidade", sa.String(16)))
    op.add_column("fatura", sa.Column("tipo_rede", sa.String(16)))


def downgrade() -> None:
    op.drop_column("fatura", "tipo_rede")
    op.drop_column("fatura", "modalidade")
    op.drop_column("fatura", "subgrupo")
    op.drop_column("fatura", "codigo_uc")
