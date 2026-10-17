"""Add authentication lockout and refresh-session state.

Revision ID: 20261014_0002
Revises: 20261011_0001
Create Date: 2026-10-14 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_0002"
down_revision = "20261011_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuario",
        sa.Column(
            "login_falhas_consecutivas",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "usuario",
        sa.Column("bloqueado_ate", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auth_session",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            default=uuid4,
        ),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("versao_token", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revogada_em", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_auth_session_usuario_id"), "auth_session", ["usuario_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_session_usuario_id"), table_name="auth_session")
    op.drop_table("auth_session")
    op.drop_column("usuario", "bloqueado_ate")
    op.drop_column("usuario", "login_falhas_consecutivas")
