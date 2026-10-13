"""Initial schema for organizations and users.

Revision ID: 20261011_0001
Revises:
Create Date: 2026-10-11 00:00:00.000000
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20261011_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizacao",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            default=uuid4,
        ),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("cnpj", sa.String(length=18), nullable=True),
        sa.Column("logo_arquivo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cor_primaria", sa.String(length=32), nullable=True),
        sa.Column("responsavel_tecnico_nome", sa.String(length=255), nullable=True),
        sa.Column("responsavel_tecnico_crea", sa.String(length=64), nullable=True),
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
    )
    op.create_index(op.f("ix_organizacao_id"), "organizacao", ["id"], unique=False)

    op.create_table(
        "usuario",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            default=uuid4,
        ),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("senha_hash", sa.String(length=255), nullable=False),
        sa.Column("papel", sa.String(length=32), nullable=False, server_default="ADMIN"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ultimo_login_em", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
    )
    op.create_index(op.f("ix_usuario_email"), "usuario", ["email"], unique=True)
    op.create_index(
        op.f("ix_usuario_organizacao_id"),
        "usuario",
        ["organizacao_id"],
        unique=False,
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            default=uuid4,
        ),
        sa.Column("organizacao_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acao", sa.String(length=255), nullable=False),
        sa.Column("entidade", sa.String(length=120), nullable=False),
        sa.Column("entidade_id", sa.String(length=64), nullable=True),
        sa.Column("antes", sa.Text(), nullable=True),
        sa.Column("depois", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organizacao_id"], ["organizacao.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
    )
    op.create_index(
        op.f("ix_audit_log_organizacao_id"),
        "audit_log",
        ["organizacao_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_log_usuario_id"),
        "audit_log",
        ["usuario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_usuario_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_organizacao_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_usuario_organizacao_id"), table_name="usuario")
    op.drop_index(op.f("ix_usuario_email"), table_name="usuario")
    op.drop_table("usuario")
    op.drop_index(op.f("ix_organizacao_id"), table_name="organizacao")
    op.drop_table("organizacao")
