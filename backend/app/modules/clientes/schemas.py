from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SegmentoCliente = Literal["HOSPITAL", "INDUSTRIA", "COMERCIO", "CONDOMINIO", "OUTRO"]


class ClienteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razao_social: str = Field(min_length=1, max_length=255)
    nome_fantasia: str | None = Field(default=None, max_length=255)
    cnpj: str | None = Field(default=None, min_length=1, max_length=18)
    segmento: SegmentoCliente | None = None
    observacoes: str | None = None

    @model_validator(mode="after")
    def normalize_text_fields(self) -> ClienteCreate:
        self.razao_social = self.razao_social.strip()
        if not self.razao_social:
            raise ValueError("razao_social não pode ser vazio.")
        if self.nome_fantasia is not None:
            self.nome_fantasia = self.nome_fantasia.strip() or None
        if self.cnpj is not None:
            self.cnpj = self.cnpj.strip() or None
        return self


class ClienteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razao_social: str | None = Field(default=None, min_length=1, max_length=255)
    nome_fantasia: str | None = Field(default=None, max_length=255)
    cnpj: str | None = Field(default=None, min_length=1, max_length=18)
    segmento: SegmentoCliente | None = None
    observacoes: str | None = None

    @model_validator(mode="after")
    def validate_and_normalize_fields(self) -> ClienteUpdate:
        if "razao_social" in self.model_fields_set:
            if self.razao_social is None or not self.razao_social.strip():
                raise ValueError("razao_social não pode ser vazio.")
            self.razao_social = self.razao_social.strip()
        if "nome_fantasia" in self.model_fields_set and self.nome_fantasia is not None:
            self.nome_fantasia = self.nome_fantasia.strip() or None
        if "cnpj" in self.model_fields_set and self.cnpj is not None:
            self.cnpj = self.cnpj.strip() or None
        return self


class ClienteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organizacao_id: UUID
    razao_social: str
    nome_fantasia: str | None
    cnpj: str | None
    segmento: str | None
    observacoes: str | None
    criado_em: datetime
    atualizado_em: datetime


class ClientePage(BaseModel):
    items: list[ClienteResponse]
    limit: int
    next_cursor: UUID | None
