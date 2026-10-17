from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ImportacaoMedicoesResponse(BaseModel):
    uc_id: UUID
    registros: int
    registros_afetados: int
    intervalo_min: int
    fonte: str
    completude_pct: Decimal
    lacunas: int
    alertas: list[str]


class ResumoMedicoesResponse(BaseModel):
    uc_id: UUID
    periodo_inicio: date
    periodo_fim: date
    registros: int
    completude_pct: Decimal
    fontes: list[str]
    ressalvas: list[str]
    parametros_pendentes: list[str]
    dm_por_mes: list[dict[str, Any]]
    fator_de_carga_por_mes: list[dict[str, Any]]
    fp_horario: list[dict[str, Any]]
    horas_fp_abaixo_referencia: int
    reativos_por_mes: list[dict[str, Any]]
    curva_tipica: list[dict[str, Any]]
    ultrapassagens: list[dict[str, Any]]
    horas_ultrapassagem: list[dict[str, Any]]
    alertas: list[str]
