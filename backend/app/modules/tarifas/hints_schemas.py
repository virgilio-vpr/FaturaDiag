from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HintDistribuidoraUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribuidora_id: UUID
    versao: str = Field(min_length=1, max_length=32)
    arquivo_md: str = Field(min_length=1, max_length=100_000)


class HintDistribuidoraVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: str = Field(min_length=1, max_length=32)
    arquivo_md: str = Field(min_length=1, max_length=100_000)
    vigencia_inicio: date


class HintDistribuidoraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    distribuidora_id: UUID
    versao: str
    arquivo_md: str
    vigencia_inicio: date
    vigencia_fim: date | None
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime


class HintDistribuidoraList(BaseModel):
    itens: list[HintDistribuidoraResponse]
