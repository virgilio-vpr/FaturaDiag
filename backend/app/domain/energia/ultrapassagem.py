from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, Posto, arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ApuracaoPosto:
    posto: Posto
    dc_kw: Decimal
    dm_kw: Decimal
    limite_kw: Decimal
    ultrapassagem_kw: Decimal
    demanda_faturada_kw: Decimal
    valor_demanda: Decimal
    valor_ultrapassagem: Decimal
    valor_total: Decimal
    trace: Trace


@dataclass(frozen=True, slots=True)
class ResultadoUltrapassagem:
    modalidade: Modalidade
    postos: tuple[ApuracaoPosto, ...]
    valor_demanda: Decimal
    valor_ultrapassagem: Decimal
    valor_total: Decimal
    trace: Trace


def apurar_posto(
    posto: Posto,
    dc_kw: Decimal,
    dm_kw: Decimal,
    tarifa_demanda: Decimal,
    tolerancia: Decimal,
    multiplicador: Decimal,
) -> ApuracaoPosto:
    """Apura demanda faturável e ultrapassagem de um posto (§3.4.1).

    Tarifa sem tributos. Valores monetários arredondados só no resultado final.
    """
    if dc_kw < 0 or dm_kw < 0 or tarifa_demanda < 0:
        raise ValueError("Demandas e tarifa não podem ser negativas")

    limite = dc_kw * (1 + tolerancia)
    ultrapassagem = dm_kw - dc_kw if dm_kw > limite else ZERO
    valor_demanda = arredondar_moeda(dc_kw * tarifa_demanda)
    valor_ultrapassagem = arredondar_moeda(ultrapassagem * tarifa_demanda * multiplicador)

    trace = (
        Trace()
        .adicionar(
            PassoTrace(
                f"limite_{posto.value}",
                "limite = Dc x (1 + tolerancia_ultrapassagem)",
                {"Dc": dc_kw, "tolerancia_ultrapassagem": tolerancia},
                limite,
            )
        )
        .adicionar(
            PassoTrace(
                f"ultrapassagem_kw_{posto.value}",
                "Dm > limite ? Dm - Dc : 0",
                {"Dm": dm_kw, "limite": limite, "Dc": dc_kw},
                ultrapassagem,
            )
        )
        .adicionar(
            PassoTrace(
                f"valor_demanda_{posto.value}",
                "Dc x T_demanda (take-or-pay)",
                {"Dc": dc_kw, "T_demanda": tarifa_demanda},
                valor_demanda,
            )
        )
        .adicionar(
            PassoTrace(
                f"valor_ultrapassagem_{posto.value}",
                "ultrapassagem_kw x T_demanda x multiplicador_ultrapassagem",
                {
                    "ultrapassagem_kw": ultrapassagem,
                    "T_demanda": tarifa_demanda,
                    "multiplicador_ultrapassagem": multiplicador,
                },
                valor_ultrapassagem,
            )
        )
    )
    return ApuracaoPosto(
        posto=posto,
        dc_kw=dc_kw,
        dm_kw=dm_kw,
        limite_kw=limite,
        ultrapassagem_kw=ultrapassagem,
        demanda_faturada_kw=dc_kw,
        valor_demanda=valor_demanda,
        valor_ultrapassagem=valor_ultrapassagem,
        valor_total=valor_demanda + valor_ultrapassagem,
        trace=trace,
    )


def _consolidar(
    modalidade: Modalidade, postos: tuple[ApuracaoPosto, ...]
) -> ResultadoUltrapassagem:
    trace = Trace()
    for p in postos:
        trace = trace.concatenar(p.trace)
    return ResultadoUltrapassagem(
        modalidade=modalidade,
        postos=postos,
        valor_demanda=sum((p.valor_demanda for p in postos), ZERO),
        valor_ultrapassagem=sum((p.valor_ultrapassagem for p in postos), ZERO),
        valor_total=sum((p.valor_total for p in postos), ZERO),
        trace=trace,
    )


def apurar_verde(
    dc_kw: Decimal,
    dm_ponta_kw: Decimal,
    dm_fora_ponta_kw: Decimal,
    tarifa_demanda: Decimal,
    parametros: ParametrosRegulatorios,
) -> ResultadoUltrapassagem:
    """Verde: demanda única; Dm é o maior valor entre ponta e fora de ponta."""
    dm = max(dm_ponta_kw, dm_fora_ponta_kw)
    posto = apurar_posto(
        Posto.UNICO,
        dc_kw,
        dm,
        tarifa_demanda,
        parametros.tolerancia_ultrapassagem,
        parametros.multiplicador_ultrapassagem,
    )
    resultado = _consolidar(Modalidade.VERDE, (posto,))
    passo = PassoTrace(
        "dm_verde",
        "Dm = max(Dm_ponta, Dm_fora_ponta)",
        {"Dm_ponta": dm_ponta_kw, "Dm_fora_ponta": dm_fora_ponta_kw},
        dm,
    )
    return ResultadoUltrapassagem(
        modalidade=resultado.modalidade,
        postos=resultado.postos,
        valor_demanda=resultado.valor_demanda,
        valor_ultrapassagem=resultado.valor_ultrapassagem,
        valor_total=resultado.valor_total,
        trace=Trace((passo,)).concatenar(resultado.trace),
    )


def apurar_azul(
    dc_ponta_kw: Decimal,
    dc_fora_ponta_kw: Decimal,
    dm_ponta_kw: Decimal,
    dm_fora_ponta_kw: Decimal,
    tarifa_demanda_ponta: Decimal,
    tarifa_demanda_fora_ponta: Decimal,
    parametros: ParametrosRegulatorios,
) -> ResultadoUltrapassagem:
    """Azul: Dc, Dm e ultrapassagem apurados separadamente por posto."""
    tol = parametros.tolerancia_ultrapassagem
    mult = parametros.multiplicador_ultrapassagem
    ponta = apurar_posto(Posto.PONTA, dc_ponta_kw, dm_ponta_kw, tarifa_demanda_ponta, tol, mult)
    fora = apurar_posto(
        Posto.FORA_PONTA, dc_fora_ponta_kw, dm_fora_ponta_kw, tarifa_demanda_fora_ponta, tol, mult
    )
    return _consolidar(Modalidade.AZUL, (ponta, fora))
