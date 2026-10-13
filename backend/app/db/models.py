from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin


class Organizacao(TimestampMixin, Base):
    __tablename__ = "organizacao"

    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    logo_arquivo_id: Mapped[UUID | None] = mapped_column(nullable=True)
    cor_primaria: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsavel_tecnico_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    responsavel_tecnico_crea: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Usuario(TenantMixin, TimestampMixin, Base):
    __tablename__ = "usuario"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    papel: Mapped[str] = mapped_column(String(32), nullable=False, default="ADMIN")
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(TenantMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"

    usuario_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("usuario.id"),
        nullable=True,
        index=True,
    )
    acao: Mapped[str] = mapped_column(String(255), nullable=False)
    entidade: Mapped[str] = mapped_column(String(120), nullable=False)
    entidade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    antes: Mapped[str | None] = mapped_column(nullable=True)
    depois: Mapped[str | None] = mapped_column(nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Cliente(TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "cliente"

    razao_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    segmento: Mapped[str | None] = mapped_column(String(40), nullable=True)
    observacoes: Mapped[str | None] = mapped_column(nullable=True)
