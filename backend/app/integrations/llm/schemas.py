from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Campo[T](BaseModel):
    valor: T | None = None
    confianca: float = Field(0.0, ge=0.0, le=1.0)
    evidencia: str | None = Field(None, max_length=200)
    pagina: int | None = None


class CategoriaItem(StrEnum):
    DEMANDA = "DEMANDA"
    DEMANDA_ULTRAPASSAGEM = "DEMANDA_ULTRAPASSAGEM"
    CONSUMO_TUSD = "CONSUMO_TUSD"
    CONSUMO_TE = "CONSUMO_TE"
    ENERGIA_REATIVA_EXCEDENTE = "ENERGIA_REATIVA_EXCEDENTE"
    DEMANDA_REATIVA_EXCEDENTE = "DEMANDA_REATIVA_EXCEDENTE"
    BANDEIRA = "BANDEIRA"
    ILUMINACAO_PUBLICA = "ILUMINACAO_PUBLICA"
    MULTA_JUROS = "MULTA_JUROS"
    AJUSTE_CREDITO_DEBITO = "AJUSTE_CREDITO_DEBITO"
    TRIBUTO_INFORMATIVO = "TRIBUTO_INFORMATIVO"
    OUTROS = "OUTROS"


class ItemFatura(BaseModel):
    descricao: str
    categoria: CategoriaItem
    posto: Literal["PONTA", "FORA_PONTA", "UNICO"] | None = None
    unidade: str | None = None
    quantidade: Decimal | None = None
    tarifa_unitaria: Decimal | None = None
    valor: Decimal


class FaturaExtraida(BaseModel):
    # Identificação
    distribuidora: Campo[str]
    razao_social: Campo[str]
    cnpj: Campo[str]
    codigo_uc: Campo[str]
    uf: Campo[str]
    subgrupo: Campo[Literal["A1", "A2", "A3", "A3a", "A4", "AS"]]
    # CONVENCIONAL não está no Anexo E; permite detectar a modalidade em extinção (§10.3).
    modalidade: Campo[Literal["AZUL", "VERDE", "CONVENCIONAL"]]
    tipo_rede: Campo[Literal["AEREA", "SUBTERRANEA"]]
    # Ciclo
    mes_referencia: Campo[date]
    leitura_anterior: Campo[date]
    leitura_atual: Campo[date]
    dias_faturados: Campo[int]
    vencimento: Campo[date]
    # Contrato e leituras (kW / kWh / kvarh)
    demanda_contratada_ponta_kw: Campo[Decimal]
    demanda_contratada_fora_ponta_kw: Campo[Decimal]
    demanda_contratada_unica_kw: Campo[Decimal]
    demanda_medida_ponta_kw: Campo[Decimal]
    demanda_medida_fora_ponta_kw: Campo[Decimal]
    consumo_ponta_kwh: Campo[Decimal]
    consumo_fora_ponta_kwh: Campo[Decimal]
    reativo_ponta_kvarh: Campo[Decimal]
    reativo_fora_ponta_kvarh: Campo[Decimal]
    fator_potencia: Campo[Decimal]
    # Tributos: percentuais como impressos (ex.: 18.00); normalizados para fração fora do extrator
    icms_aliquota_pct: Campo[Decimal]
    pis_aliquota_pct: Campo[Decimal]
    cofins_aliquota_pct: Campo[Decimal]
    bandeira: Campo[Literal["VERDE", "AMARELA", "VERMELHA_1", "VERMELHA_2"]]
    valor_total: Campo[Decimal]
    itens: list[ItemFatura]
    observacoes_extrator: list[str] = []
