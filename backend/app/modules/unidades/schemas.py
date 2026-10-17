from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Subgrupo(StrEnum):
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A3A = "A3a"
    A4 = "A4"
    AS = "AS"


class TipoRede(StrEnum):
    AEREA = "AEREA"
    SUBTERRANEA = "SUBTERRANEA"


class AmbienteUnidade(StrEnum):
    CATIVO = "CATIVO"
    LIVRE = "LIVRE"


class ModalidadeDemanda(StrEnum):
    AZUL = "AZUL"
    VERDE = "VERDE"
    CONVENCIONAL = "CONVENCIONAL"


class UnidadeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribuidora_id: UUID
    codigo_uc: str = Field(min_length=1, max_length=80)
    apelido: str | None = Field(default=None, max_length=255)
    uf: str = Field(min_length=2, max_length=2)
    municipio: str = Field(min_length=1, max_length=120)
    subgrupo: Subgrupo
    tipo_rede: TipoRede
    ambiente: AmbienteUnidade
    tensao_kv: Decimal | None = None
    observacoes: str | None = None

    @field_validator("codigo_uc", "municipio")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("O campo não pode ser vazio.")
        return normalized

    @field_validator("uf")
    @classmethod
    def normalize_uf(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("apelido")
    @classmethod
    def normalize_apelido(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class UnidadeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo_uc: str | None = Field(default=None, min_length=1, max_length=80)
    apelido: str | None = Field(default=None, max_length=255)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    municipio: str | None = Field(default=None, min_length=1, max_length=120)
    subgrupo: Subgrupo | None = None
    tipo_rede: TipoRede | None = None
    ambiente: AmbienteUnidade | None = None
    tensao_kv: Decimal | None = None
    observacoes: str | None = None

    @field_validator("codigo_uc", "municipio")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("uf")
    @classmethod
    def normalize_uf(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> UnidadeUpdate:
        required_fields = {"codigo_uc", "uf", "municipio", "subgrupo", "tipo_rede", "ambiente"}
        for field_name in required_fields.intersection(self.model_fields_set):
            value = getattr(self, field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{field_name} não pode ser vazio.")
        return self


class UnidadeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organizacao_id: UUID
    cliente_id: UUID
    distribuidora_id: UUID
    codigo_uc: str
    apelido: str | None
    uf: str
    municipio: str
    subgrupo: str
    tipo_rede: str
    ambiente: str
    tensao_kv: Decimal | None
    observacoes: str | None
    criado_em: datetime
    atualizado_em: datetime


class UnidadePage(BaseModel):
    items: list[UnidadeResponse]
    limit: int
    next_cursor: UUID | None


class ContratoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modalidade: ModalidadeDemanda
    demanda_ponta_kw: Decimal | None = None
    demanda_fora_ponta_kw: Decimal | None = None
    demanda_unica_kw: Decimal | None = None
    vigencia_inicio: date
    vigencia_fim: date | None = None


class ContratoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    uc_id: UUID
    modalidade: str
    demanda_ponta_kw: Decimal | None
    demanda_fora_ponta_kw: Decimal | None
    demanda_unica_kw: Decimal | None
    vigencia_inicio: date
    vigencia_fim: date | None
    criado_em: datetime
    atualizado_em: datetime
