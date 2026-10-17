from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
