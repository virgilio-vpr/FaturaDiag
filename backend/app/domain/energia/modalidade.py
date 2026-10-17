from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.domain.energia.demanda_otima import (
    MESES_MINIMOS,
    otimizar_azul,
    otimizar_verde,
)
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, Subgrupo, arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace


@dataclass(frozen=True, slots=True)
class HistoricoMes:
    dm_ponta_kw: Decimal
    dm_fora_ponta_kw: Decimal
    consumo_ponta_kwh: Decimal
    consumo_fora_ponta_kwh: Decimal


@dataclass(frozen=True, slots=True)
class TarifasAzul:
    """Tarifas sem tributos da modalidade Azul. Energia = TUSD consumo + TE (R$/kWh)."""

    demanda_ponta_rs_kw: Decimal
    demanda_fora_ponta_rs_kw: Decimal
    energia_ponta_rs_kwh: Decimal
    energia_fora_ponta_rs_kwh: Decimal


@dataclass(frozen=True, slots=True)
class TarifasVerde:
    """Tarifas sem tributos da modalidade Verde (demanda única; energia por posto)."""

    demanda_rs_kw: Decimal
    energia_ponta_rs_kwh: Decimal
    energia_fora_ponta_rs_kwh: Decimal


@dataclass(frozen=True, slots=True)
class CustoModalidade:
    modalidade: Modalidade
    dc_kw: dict[str, Decimal]
    custo_demanda: Decimal
    custo_consumo: Decimal
    custo_total: Decimal


@dataclass(frozen=True, slots=True)
class ComparacaoModalidades:
    azul: CustoModalidade | None
    verde: CustoModalidade | None
    recomendada: Modalidade
    diferenca_anual: Decimal
    motivo: str
    meses: int
    indicativo: bool
    trace: Trace


def _soma(valores: Sequence[Decimal]) -> Decimal:
    return sum(valores, Decimal(0))


def comparar_modalidades(
    subgrupo: Subgrupo,
    historico: Sequence[HistoricoMes],
    tarifas_azul: TarifasAzul,
    tarifas_verde: TarifasVerde | None,
    parametros: ParametrosRegulatorios,
) -> ComparacaoModalidades:
    """Compara Azul × Verde com Dc ótima em cada uma (§3.4.6).

    Custo = demanda + ultrapassagem (Dc ótima) + consumo (TUSD + TE por posto), sem tributos.
    Verde só é avaliada se o subgrupo for elegível segundo os parâmetros (§3.8).
    """
    if not historico:
        raise ValueError("Histórico vazio")
    meses = len(historico)
    tol = parametros.tolerancia_ultrapassagem
    mult = parametros.multiplicador_ultrapassagem
    dc_min = parametros.demanda_minima_contratada_kw
    dm_p = [h.dm_ponta_kw for h in historico]
    dm_f = [h.dm_fora_ponta_kw for h in historico]
    cons_p = _soma([h.consumo_ponta_kwh for h in historico])
    cons_f = _soma([h.consumo_fora_ponta_kwh for h in historico])

    otm_azul = otimizar_azul(
        dm_p,
        dm_f,
        tarifas_azul.demanda_ponta_rs_kw,
        tarifas_azul.demanda_fora_ponta_rs_kw,
        tol,
        mult,
        dc_min,
    )
    consumo_azul = arredondar_moeda(
        cons_p * tarifas_azul.energia_ponta_rs_kwh + cons_f * tarifas_azul.energia_fora_ponta_rs_kwh
    )
    azul = CustoModalidade(
        Modalidade.AZUL,
        {"PONTA": otm_azul.ponta.dc_otima_kw, "FORA_PONTA": otm_azul.fora_ponta.dc_otima_kw},
        otm_azul.custo_anual_otimo,
        consumo_azul,
        otm_azul.custo_anual_otimo + consumo_azul,
    )
    trace = otm_azul.trace.adicionar(
        PassoTrace(
            "custo_azul",
            "demanda+ultrapassagem (Dc ótima por posto) + consumo TUSD+TE por posto",
            {"custo_demanda": azul.custo_demanda, "custo_consumo": azul.custo_consumo},
            azul.custo_total,
        )
    )

    verde: CustoModalidade | None = None
    if subgrupo.value in parametros.modalidades_verde_elegiveis:
        if tarifas_verde is None:
            raise ValueError("Tarifas da modalidade Verde são obrigatórias para subgrupo elegível")
        otm_verde = otimizar_verde(dm_p, dm_f, tarifas_verde.demanda_rs_kw, tol, mult, dc_min)
        consumo_verde = arredondar_moeda(
            cons_p * tarifas_verde.energia_ponta_rs_kwh
            + cons_f * tarifas_verde.energia_fora_ponta_rs_kwh
        )
        verde = CustoModalidade(
            Modalidade.VERDE,
            {"UNICO": otm_verde.dc_otima_kw},
            otm_verde.custo_anual_otimo,
            consumo_verde,
            otm_verde.custo_anual_otimo + consumo_verde,
        )
        trace = trace.concatenar(otm_verde.trace).adicionar(
            PassoTrace(
                "custo_verde",
                "demanda+ultrapassagem (Dc ótima única) + consumo TUSD+TE por posto",
                {"custo_demanda": verde.custo_demanda, "custo_consumo": verde.custo_consumo},
                verde.custo_total,
            )
        )

    if verde is None:
        recomendada = Modalidade.AZUL
        diferenca = arredondar_moeda(Decimal(0))
        motivo = f"Modalidade Verde não elegível para o subgrupo {subgrupo.value}"
    elif verde.custo_total < azul.custo_total:
        recomendada = Modalidade.VERDE
        diferenca = azul.custo_total - verde.custo_total
        motivo = "Verde tem menor custo anual"
    else:
        recomendada = Modalidade.AZUL
        diferenca = verde.custo_total - azul.custo_total
        motivo = "Azul tem menor custo anual (ou empate)"

    trace = trace.adicionar(
        PassoTrace(
            "recomendacao_modalidade",
            "modalidade de menor custo anual",
            {"subgrupo": subgrupo.value, "meses": meses},
            recomendada.value,
        )
    )
    return ComparacaoModalidades(
        azul=azul,
        verde=verde,
        recomendada=recomendada,
        diferenca_anual=diferenca,
        motivo=motivo,
        meses=meses,
        indicativo=meses < MESES_MINIMOS,
        trace=trace,
    )
