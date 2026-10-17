from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    login_falhas_consecutivas: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(TimestampMixin, Base):
    __tablename__ = "auth_session"

    usuario_id: Mapped[UUID] = mapped_column(
        ForeignKey("usuario.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    versao_token: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revogada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(TenantMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_organizacao_ts", "organizacao_id", "ts"),)

    usuario_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("usuario.id"),
        nullable=True,
        index=True,
    )
    acao: Mapped[str] = mapped_column(String(255), nullable=False)
    entidade: Mapped[str] = mapped_column(String(120), nullable=False)
    entidade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    antes: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    depois: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Cliente(TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "cliente"
    __table_args__ = (
        UniqueConstraint("organizacao_id", "cnpj", name="uq_cliente_organizacao_cnpj"),
    )

    razao_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    segmento: Mapped[str | None] = mapped_column(String(40), nullable=True)
    observacoes: Mapped[str | None] = mapped_column(nullable=True)


class UnidadeConsumidora(TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "unidade_consumidora"
    __table_args__ = (
        UniqueConstraint(
            "distribuidora_id",
            "codigo_uc",
            "organizacao_id",
            name="uq_unidade_distribuidora_codigo_organizacao",
        ),
        CheckConstraint(
            "subgrupo IN ('A1', 'A2', 'A3', 'A3a', 'A4', 'AS')",
            name="ck_unidade_subgrupo",
        ),
        CheckConstraint(
            "tipo_rede IN ('AEREA', 'SUBTERRANEA')",
            name="ck_unidade_tipo_rede",
        ),
        CheckConstraint(
            "(subgrupo = 'AS' AND tipo_rede = 'SUBTERRANEA') OR subgrupo <> 'AS'",
            name="ck_unidade_as_subterranea",
        ),
        CheckConstraint(
            "ambiente IN ('CATIVO', 'LIVRE')",
            name="ck_unidade_ambiente",
        ),
    )

    cliente_id: Mapped[UUID] = mapped_column(ForeignKey("cliente.id"), nullable=False, index=True)
    distribuidora_id: Mapped[UUID] = mapped_column(
        ForeignKey("distribuidora.id"),
        nullable=False,
        index=True,
    )
    codigo_uc: Mapped[str] = mapped_column(String(80), nullable=False)
    apelido: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uf: Mapped[str] = mapped_column(String(2), nullable=False)
    municipio: Mapped[str] = mapped_column(String(120), nullable=False)
    subgrupo: Mapped[str] = mapped_column(String(8), nullable=False)
    tipo_rede: Mapped[str] = mapped_column(String(16), nullable=False)
    ambiente: Mapped[str] = mapped_column(String(16), nullable=False)
    tensao_kv: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    observacoes: Mapped[str | None] = mapped_column(nullable=True)


class ContratoDemanda(TimestampMixin, Base):
    __tablename__ = "contrato_demanda"
    __table_args__ = (
        CheckConstraint(
            "modalidade IN ('AZUL', 'VERDE', 'CONVENCIONAL')",
            name="ck_contrato_modalidade",
        ),
        CheckConstraint(
            "(modalidade = 'AZUL' AND demanda_ponta_kw IS NOT NULL "
            "AND demanda_fora_ponta_kw IS NOT NULL AND demanda_unica_kw IS NULL) "
            "OR (modalidade IN ('VERDE', 'CONVENCIONAL') "
            "AND demanda_unica_kw IS NOT NULL AND demanda_ponta_kw IS NULL "
            "AND demanda_fora_ponta_kw IS NULL)",
            name="ck_contrato_demanda_por_modalidade",
        ),
        CheckConstraint(
            "(demanda_ponta_kw IS NULL OR demanda_ponta_kw >= 30) "
            "AND (demanda_fora_ponta_kw IS NULL OR demanda_fora_ponta_kw >= 30) "
            "AND (demanda_unica_kw IS NULL OR demanda_unica_kw >= 30)",
            name="ck_contrato_demanda_minima",
        ),
        CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_contrato_vigencia",
        ),
    )

    uc_id: Mapped[UUID] = mapped_column(
        ForeignKey("unidade_consumidora.id"),
        nullable=False,
        index=True,
    )
    modalidade: Mapped[str] = mapped_column(String(16), nullable=False)
    demanda_ponta_kw: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    demanda_fora_ponta_kw: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    demanda_unica_kw: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)


class Distribuidora(TimestampMixin, Base):
    __tablename__ = "distribuidora"
    __table_args__ = (
        CheckConstraint(
            "ponta_status IN ('VALIDAR', 'VALIDADO')",
            name="ck_distribuidora_ponta_status",
        ),
        CheckConstraint(
            "(ponta_inicio IS NULL AND ponta_fim IS NULL) "
            "OR (ponta_inicio IS NOT NULL AND ponta_fim IS NOT NULL)",
            name="ck_distribuidora_ponta_window",
        ),
        UniqueConstraint("sigla", name="uq_distribuidora_sigla"),
    )

    sigla: Mapped[str] = mapped_column(String(40), nullable=False)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    codigo_aneel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ufs: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False)
    ponta_inicio: Mapped[time | None] = mapped_column(nullable=True)
    ponta_fim: Mapped[time | None] = mapped_column(nullable=True)
    ponta_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="VALIDAR", server_default="VALIDAR"
    )
    tem_hint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class FeriadoNacional(TimestampMixin, Base):
    __tablename__ = "feriado_nacional"
    __table_args__ = (UniqueConstraint("data", name="uq_feriado_nacional_data"),)

    data: Mapped[date] = mapped_column(nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    vale_para_ponta: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class Tarifa(TimestampMixin, Base):
    __tablename__ = "tarifa"
    __table_args__ = (
        UniqueConstraint(
            "distribuidora_id",
            "subgrupo",
            "modalidade",
            "posto",
            "componente",
            "vigencia_inicio",
            name="uq_tarifa_versao",
        ),
        CheckConstraint(
            "modalidade IN ('AZUL', 'VERDE', 'CONVENCIONAL')",
            name="ck_tarifa_modalidade",
        ),
        CheckConstraint(
            "posto IN ('PONTA', 'FORA_PONTA', 'UNICO')",
            name="ck_tarifa_posto",
        ),
        CheckConstraint(
            "componente IN ('TUSD_DEMANDA', 'TUSD_CONSUMO', 'TE_CONSUMO')",
            name="ck_tarifa_componente",
        ),
        CheckConstraint("unidade IN ('RS_KW', 'RS_MWH')", name="ck_tarifa_unidade"),
        CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_tarifa_vigencia",
        ),
    )

    distribuidora_id: Mapped[UUID] = mapped_column(
        ForeignKey("distribuidora.id"), nullable=False, index=True
    )
    subgrupo: Mapped[str] = mapped_column(String(8), nullable=False)
    modalidade: Mapped[str] = mapped_column(String(16), nullable=False)
    posto: Mapped[str] = mapped_column(String(16), nullable=False)
    componente: Mapped[str] = mapped_column(String(24), nullable=False)
    unidade: Mapped[str] = mapped_column(String(16), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolucao_homologatoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fonte: Mapped[str] = mapped_column(Text, nullable=False)
    importado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BandeiraTarifaria(TimestampMixin, Base):
    __tablename__ = "bandeira_tarifaria"
    __table_args__ = (
        CheckConstraint(
            "bandeira IN ('VERDE', 'AMARELA', 'VERMELHA_1', 'VERMELHA_2')",
            name="ck_bandeira_tarifaria_bandeira",
        ),
    )

    mes_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    bandeira: Mapped[str] = mapped_column(String(16), nullable=False)
    adicional_rs_mwh: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fonte: Mapped[str] = mapped_column(Text, nullable=False)


class ParametroRegulatorio(TimestampMixin, Base):
    __tablename__ = "parametro_regulatorio"
    __table_args__ = (
        UniqueConstraint("chave", "vigencia_inicio", name="uq_parametro_regulatorio_versao"),
        CheckConstraint(
            "status IN ('VALIDADO', 'VALIDAR')",
            name="ck_parametro_regulatorio_status",
        ),
        CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_parametro_regulatorio_vigencia",
        ),
    )

    chave: Mapped[str] = mapped_column(String(120), nullable=False)
    valor: Mapped[object] = mapped_column(JSONB, nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    fonte: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="VALIDAR", server_default="VALIDAR"
    )
    validado_por: Mapped[UUID | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    validado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HintDistribuidora(TimestampMixin, Base):
    __tablename__ = "hint_distribuidora"
    __table_args__ = (
        UniqueConstraint("distribuidora_id", "versao", name="uq_hint_distribuidora_versao"),
        CheckConstraint(
            "vigencia_fim IS NULL OR vigencia_fim > vigencia_inicio",
            name="ck_hint_distribuidora_vigencia",
        ),
    )

    distribuidora_id: Mapped[UUID] = mapped_column(
        ForeignKey("distribuidora.id"), nullable=False, index=True
    )
    versao: Mapped[str] = mapped_column(String(32), nullable=False)
    arquivo_md: Mapped[str] = mapped_column(Text, nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
