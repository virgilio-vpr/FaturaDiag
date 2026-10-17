from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.energia.trace import PassoTrace, Trace

MIL = Decimal(1000)


@dataclass(frozen=True, slots=True)
class Indicador:
    """`valor` é None quando o denominador é zero (indicador indefinido)."""

    valor: Decimal | None
    trace: Trace


def _indicador(
    nome: str, formula: str, insumos: dict[str, Decimal], numerador: Decimal, denominador: Decimal
) -> Indicador:
    if any(v < 0 for v in insumos.values()):
        raise ValueError("Entradas não podem ser negativas")
    valor = None if denominador == 0 else numerador / denominador
    trace = Trace().adicionar(PassoTrace(nome, formula, insumos, valor))
    return Indicador(valor, trace)


def fator_de_carga(energia_kwh: Decimal, dm_max_kw: Decimal, horas: Decimal) -> Indicador:
    return _indicador(
        "fator_de_carga",
        "energia_total_kWh / (Dm_max_kW x horas_do_periodo)",
        {"energia_kwh": energia_kwh, "dm_max_kw": dm_max_kw, "horas": horas},
        energia_kwh,
        dm_max_kw * horas,
    )


def utilizacao_demanda(dm_kw: Decimal, dc_kw: Decimal) -> Indicador:
    return _indicador(
        "utilizacao_demanda", "Dm / Dc", {"dm_kw": dm_kw, "dc_kw": dc_kw}, dm_kw, dc_kw
    )


def pct_consumo_ponta(consumo_ponta_kwh: Decimal, consumo_fora_ponta_kwh: Decimal) -> Indicador:
    return _indicador(
        "pct_consumo_ponta",
        "consumo_ponta / (consumo_ponta + consumo_fora_ponta)",
        {"ponta": consumo_ponta_kwh, "fora_ponta": consumo_fora_ponta_kwh},
        consumo_ponta_kwh,
        consumo_ponta_kwh + consumo_fora_ponta_kwh,
    )


def custo_medio_rs_mwh(valor_sem_cip_e_multas: Decimal, energia_kwh: Decimal) -> Indicador:
    return _indicador(
        "custo_medio_rs_mwh",
        "valor_total_sem_cip_e_multas / (energia_total_kWh / 1000)",
        {"valor": valor_sem_cip_e_multas, "energia_kwh": energia_kwh},
        valor_sem_cip_e_multas,
        energia_kwh / MIL,
    )
