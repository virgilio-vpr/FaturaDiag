from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _sem_float(valor: object) -> object:
    """Dinheiro e tarifas nunca trafegam como float (P3): aceita string ou inteiro."""
    if isinstance(valor, float):
        raise ValueError('Envie valores decimais como string (ex.: "12.34").')
    return valor


Dec = Annotated[Decimal, BeforeValidator(_sem_float), Field(allow_inf_nan=False)]
DecNaoNegativo = Annotated[Decimal, BeforeValidator(_sem_float), Field(allow_inf_nan=False, ge=0)]


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntradaACLSchema(Entrada):
    consumo_mwh_mes: DecNaoNegativo
    te_cativa_rs_mwh: DecNaoNegativo
    encargos_rs_mwh: DecNaoNegativo
    custos_fixos_mes: DecNaoNegativo
    tusd_demanda_mes: DecNaoNegativo = Decimal(0)
    tusd_consumo_mes: DecNaoNegativo = Decimal(0)
    bandeira_mes: DecNaoNegativo = Decimal(0)
    desconto_tusd: DecNaoNegativo = Decimal(0)
    fator_tributos_cativo: DecNaoNegativo = Decimal(1)
    fator_tributos_livre: DecNaoNegativo = Decimal(1)
    custo_adequacao_unico: DecNaoNegativo = Decimal(0)


class CenarioPrecoSchema(Entrada):
    nome: Annotated[str, Field(min_length=1, max_length=32)]
    preco_rs_mwh: DecNaoNegativo


class SimulacaoACLRequest(Entrada):
    entrada: EntradaACLSchema
    cenarios: Annotated[list[CenarioPrecoSchema], Field(min_length=1, max_length=10)]


class SimulacaoACLPuraRequest(SimulacaoACLRequest):
    data_referencia: date | None = None


class SimulacaoDemandaRequest(Entrada):
    modalidade: Literal["VERDE", "AZUL"]
    dm_ponta_kw: Annotated[list[DecNaoNegativo], Field(min_length=1, max_length=120)]
    dm_fora_ponta_kw: Annotated[list[DecNaoNegativo], Field(min_length=1, max_length=120)]
    tarifa_unica_rs_kw: DecNaoNegativo | None = None
    tarifa_ponta_rs_kw: DecNaoNegativo | None = None
    tarifa_fora_ponta_rs_kw: DecNaoNegativo | None = None
    dc_atual_kw: DecNaoNegativo | None = None
    dc_atual_ponta_kw: DecNaoNegativo | None = None
    dc_atual_fora_ponta_kw: DecNaoNegativo | None = None
    data_referencia: date | None = None


class SimulacaoPuraResponse(BaseModel):
    resultado: dict[str, Any]


class DiagnosticoCreate(Entrada):
    uc_id: UUID
    escopo: Literal["FATURA_UNICA", "HISTORICO"]
    fatura_id: UUID | None = None
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    acl: SimulacaoACLRequest | None = None


class DiagnosticoPatch(Entrada):
    notas: Annotated[str | None, Field(max_length=10_000)]


class AchadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordem: int
    codigo: str
    severidade: str
    titulo: str
    descricao: str
    economia_anual: Decimal | None
    recomendacao: str
    evidencias: list[str]
    premissas: list[str]
    trace: dict[str, Any]


class SimulacaoACLResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    diagnostico_id: UUID
    cenario: str
    premissas: dict[str, Any]
    resultado: dict[str, Any]
    criado_em: datetime


class DiagnosticoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    uc_id: UUID
    escopo: str
    periodo_inicio: date
    periodo_fim: date
    status: str
    versao_motor: str
    economia_mensal_estimada: Decimal
    economia_anual_estimada: Decimal
    notas: str | None
    criado_por: UUID | None
    revisado_por: UUID | None
    revisado_em: datetime | None
    criado_em: datetime
    resultado: dict[str, Any]
    fontes: dict[str, Any]
    premissas_montagem: list[str]
    parametros_pendentes: list[str]
    achados: list[AchadoResponse]
    simulacoes_acl: list[SimulacaoACLResponse]
