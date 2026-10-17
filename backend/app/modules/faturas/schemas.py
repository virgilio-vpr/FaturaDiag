from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.integrations.llm.schemas import CategoriaItem
from pydantic import BaseModel, ConfigDict, Field


class FaturaUploadResponse(BaseModel):
    id: UUID
    status: str


class FaturaResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    uc_id: UUID | None
    status: str
    origem: str | None
    mes_referencia: date | None
    valor_total: Decimal | None
    confianca_minima: Decimal | None
    criado_em: datetime


class FaturaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordem: int
    descricao: str
    categoria: str
    posto: str | None
    unidade: str | None
    quantidade: Decimal | None
    tarifa_unitaria: Decimal | None
    valor: Decimal


class FaturaResponse(FaturaResumo):
    arquivo_id: UUID | None
    leitura_anterior: date | None
    leitura_atual: date | None
    dias_faturados: int | None
    vencimento: date | None
    dados_extraidos: dict[str, Any] | None
    alertas: list[dict[str, Any]]
    distribuidora_detectada_id: UUID | None
    hint_usado: str | None
    atualizado_em: datetime
    codigo_uc: str | None
    subgrupo: str | None
    modalidade: str | None
    tipo_rede: str | None
    validada_em: datetime | None
    itens: list[FaturaItemResponse] = []


class ItemDados(BaseModel):
    descricao: str = Field(max_length=255)
    categoria: CategoriaItem
    posto: Literal["PONTA", "FORA_PONTA", "UNICO"] | None = None
    unidade: str | None = Field(None, max_length=16)
    quantidade: Decimal | None = None
    tarifa_unitaria: Decimal | None = None
    valor: Decimal


class DadosFaturaUpdate(BaseModel):
    """Valores revisados; campos ausentes permanecem como estão. Alíquotas em fração (0.18)."""

    uc_id: UUID | None = None
    codigo_uc: str | None = Field(None, max_length=80)
    subgrupo: Literal["A1", "A2", "A3", "A3a", "A4", "AS"] | None = None
    modalidade: Literal["AZUL", "VERDE", "CONVENCIONAL"] | None = None
    tipo_rede: Literal["AEREA", "SUBTERRANEA"] | None = None
    mes_referencia: date | None = None
    leitura_anterior: date | None = None
    leitura_atual: date | None = None
    dias_faturados: int | None = Field(None, ge=0, le=100)
    vencimento: date | None = None
    dc_ponta_kw: Decimal | None = Field(None, ge=0)
    dc_fora_ponta_kw: Decimal | None = Field(None, ge=0)
    dc_unica_kw: Decimal | None = Field(None, ge=0)
    dm_ponta_kw: Decimal | None = Field(None, ge=0)
    dm_fora_ponta_kw: Decimal | None = Field(None, ge=0)
    consumo_ponta_kwh: Decimal | None = Field(None, ge=0)
    consumo_fora_ponta_kwh: Decimal | None = Field(None, ge=0)
    reativo_ponta_kvarh: Decimal | None = Field(None, ge=0)
    reativo_fora_ponta_kvarh: Decimal | None = Field(None, ge=0)
    fator_potencia: Decimal | None = Field(None, ge=0, le=1)
    icms_aliquota: Decimal | None = Field(None, ge=0, lt=1)
    pis_aliquota: Decimal | None = Field(None, ge=0, lt=1)
    cofins_aliquota: Decimal | None = Field(None, ge=0, lt=1)
    bandeira: Literal["VERDE", "AMARELA", "VERMELHA_1", "VERMELHA_2"] | None = None
    valor_total: Decimal | None = Field(None, ge=0)
    itens: list[ItemDados] | None = None
