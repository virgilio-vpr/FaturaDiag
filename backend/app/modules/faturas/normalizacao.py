from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.integrations.llm.schemas import FaturaExtraida

UM_CEM = Decimal(100)
SEIS_CASAS = Decimal("0.000001")


@dataclass(frozen=True)
class CamposNormalizados:
    valores: dict[str, Any]


def pct_para_fracao(pct: Decimal | None) -> Decimal | None:
    """18.00 (como impresso) → 0.180000."""
    if pct is None:
        return None
    return (pct / UM_CEM).quantize(SEIS_CASAS)


def normalizar_para_fatura(extraida: FaturaExtraida) -> CamposNormalizados:
    """Valores extraídos mapeados para as colunas validadas da fatura (§8.4)."""
    mes: date | None = extraida.mes_referencia.valor
    return CamposNormalizados(
        {
            "codigo_uc": extraida.codigo_uc.valor,
            "subgrupo": extraida.subgrupo.valor,
            "modalidade": extraida.modalidade.valor,
            "tipo_rede": extraida.tipo_rede.valor,
            "mes_referencia": mes.replace(day=1) if mes else None,
            "leitura_anterior": extraida.leitura_anterior.valor,
            "leitura_atual": extraida.leitura_atual.valor,
            "dias_faturados": extraida.dias_faturados.valor,
            "vencimento": extraida.vencimento.valor,
            "dc_ponta_kw": extraida.demanda_contratada_ponta_kw.valor,
            "dc_fora_ponta_kw": extraida.demanda_contratada_fora_ponta_kw.valor,
            "dc_unica_kw": extraida.demanda_contratada_unica_kw.valor,
            "dm_ponta_kw": extraida.demanda_medida_ponta_kw.valor,
            "dm_fora_ponta_kw": extraida.demanda_medida_fora_ponta_kw.valor,
            "consumo_ponta_kwh": extraida.consumo_ponta_kwh.valor,
            "consumo_fora_ponta_kwh": extraida.consumo_fora_ponta_kwh.valor,
            "reativo_ponta_kvarh": extraida.reativo_ponta_kvarh.valor,
            "reativo_fora_ponta_kvarh": extraida.reativo_fora_ponta_kvarh.valor,
            "fator_potencia": extraida.fator_potencia.valor,
            "icms_aliquota": pct_para_fracao(extraida.icms_aliquota_pct.valor),
            "pis_aliquota": pct_para_fracao(extraida.pis_aliquota_pct.valor),
            "cofins_aliquota": pct_para_fracao(extraida.cofins_aliquota_pct.valor),
            "bandeira": extraida.bandeira.valor,
            "valor_total": extraida.valor_total.valor,
        }
    )


def confianca_minima(extraida: FaturaExtraida) -> Decimal | None:
    confiancas = [
        campo.confianca
        for campo in (
            extraida.subgrupo,
            extraida.modalidade,
            extraida.codigo_uc,
            extraida.mes_referencia,
            extraida.demanda_contratada_ponta_kw,
            extraida.demanda_contratada_fora_ponta_kw,
            extraida.demanda_contratada_unica_kw,
            extraida.consumo_ponta_kwh,
            extraida.consumo_fora_ponta_kwh,
            extraida.valor_total,
        )
        if campo.valor is not None
    ]
    if not confiancas:
        return None
    return Decimal(str(min(confiancas))).quantize(Decimal("0.001"))


COLUNA_PARA_CAMPO = {
    "codigo_uc": "codigo_uc",
    "subgrupo": "subgrupo",
    "modalidade": "modalidade",
    "tipo_rede": "tipo_rede",
    "mes_referencia": "mes_referencia",
    "leitura_anterior": "leitura_anterior",
    "leitura_atual": "leitura_atual",
    "dias_faturados": "dias_faturados",
    "vencimento": "vencimento",
    "dc_ponta_kw": "demanda_contratada_ponta_kw",
    "dc_fora_ponta_kw": "demanda_contratada_fora_ponta_kw",
    "dc_unica_kw": "demanda_contratada_unica_kw",
    "dm_ponta_kw": "demanda_medida_ponta_kw",
    "dm_fora_ponta_kw": "demanda_medida_fora_ponta_kw",
    "consumo_ponta_kwh": "consumo_ponta_kwh",
    "consumo_fora_ponta_kwh": "consumo_fora_ponta_kwh",
    "reativo_ponta_kvarh": "reativo_ponta_kvarh",
    "reativo_fora_ponta_kvarh": "reativo_fora_ponta_kvarh",
    "fator_potencia": "fator_potencia",
    "bandeira": "bandeira",
    "valor_total": "valor_total",
}
ALIQUOTA_PARA_CAMPO_PCT = {
    "icms_aliquota": "icms_aliquota_pct",
    "pis_aliquota": "pis_aliquota_pct",
    "cofins_aliquota": "cofins_aliquota_pct",
}
CAMPOS_IDENTIDADE = ("distribuidora", "razao_social", "cnpj", "uf")


def extraida_revisada(
    dados_extraidos: dict[str, Any] | None,
    valores: dict[str, Any],
    itens: list[dict[str, Any]],
) -> FaturaExtraida:
    """Reconstrói a extração com os valores confirmados pelo analista (confiança 1.0)."""
    base: dict[str, Any] = dict(dados_extraidos or {})
    for nome in FaturaExtraida.model_fields:
        if nome not in ("itens", "observacoes_extrator"):
            base.setdefault(nome, _campo_humano(None))
    for coluna, campo in COLUNA_PARA_CAMPO.items():
        base[campo] = _campo_humano(valores.get(coluna))
    for coluna, campo in ALIQUOTA_PARA_CAMPO_PCT.items():
        fracao = valores.get(coluna)
        base[campo] = _campo_humano(None if fracao is None else Decimal(fracao) * UM_CEM)
    base["itens"] = itens
    base.setdefault("observacoes_extrator", [])
    return FaturaExtraida.model_validate(base)


def _campo_humano(valor: Any) -> dict[str, Any]:
    if valor is None:
        return {"valor": None, "confianca": 0.0}
    return {"valor": valor, "confianca": 1.0}
