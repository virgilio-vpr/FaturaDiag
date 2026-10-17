from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ParametroRegulatorioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chave: str = Field(min_length=1, max_length=120)
    valor: object
    vigencia_inicio: date
    vigencia_fim: date | None = None
    fonte: str | None = Field(default=None, max_length=10000)
    status: Literal["VALIDAR", "VALIDADO"] = "VALIDAR"


class ParametroRegulatorioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chave: str
    valor: object
    vigencia_inicio: date
    vigencia_fim: date | None
    fonte: str | None
    status: str
    validado_por: UUID | None
    validado_em: datetime | None


class ParametrosRegulatoriosResponse(BaseModel):
    data_referencia: date
    itens: list[ParametroRegulatorioResponse]
    pendentes_validacao: list[str]
