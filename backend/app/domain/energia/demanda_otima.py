from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from app.domain.energia.tipos import arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace

ZERO = Decimal(0)
MESES_MINIMOS = 12
FATOR_MAX = Decimal("1.2")
VARIACOES = (Decimal("-0.10"), Decimal("-0.05"), Decimal("0.05"), Decimal("0.10"))


@dataclass(frozen=True, slots=True)
class PontoCurva:
    dc_kw: Decimal
    custo_anual: Decimal


@dataclass(frozen=True, slots=True)
class Sensibilidade:
    variacao: Decimal
    dc_kw: Decimal
    custo_anual: Decimal


@dataclass(frozen=True, slots=True)
class ResultadoDemandaOtima:
    dc_otima_kw: Decimal
    custo_anual_otimo: Decimal
    custo_anual_atual: Decimal | None
    economia_anual: Decimal | None
    curva: tuple[PontoCurva, ...]
    sensibilidade: tuple[Sensibilidade, ...]
    meses: int
    indicativo: bool
    trace: Trace


@dataclass(frozen=True, slots=True)
class ResultadoDemandaOtimaAzul:
    ponta: ResultadoDemandaOtima
    fora_ponta: ResultadoDemandaOtima
    custo_anual_otimo: Decimal
    trace: Trace


def custo_anual(
    dc_kw: Decimal,
    dm_mensal_kw: Sequence[Decimal],
    tarifa: Decimal,
    tolerancia: Decimal,
    multiplicador: Decimal,
) -> Decimal:
    """custo(Dc) = Σ_mês [ Dc x T + (Dm > Dc x (1+tol) ? mult x T x (Dm - Dc) : 0) ]."""
    limite = dc_kw * (1 + tolerancia)
    total = ZERO
    for dm in dm_mensal_kw:
        total += dc_kw * tarifa
        if dm > limite:
            total += multiplicador * tarifa * (dm - dc_kw)
    return total


def otimizar_posto(
    dm_mensal_kw: Sequence[Decimal],
    tarifa: Decimal,
    tolerancia: Decimal,
    multiplicador: Decimal,
    dc_minima_kw: Decimal,
    dc_atual_kw: Decimal | None = None,
) -> ResultadoDemandaOtima:
    """Dc ótima em [dc_minima, 1,2 x max(Dm)], passo de 1 kW, desempate pelo menor Dc (§3.4.5)."""
    if not dm_mensal_kw:
        raise ValueError("Série de demanda medida vazia")
    if any(dm < 0 for dm in dm_mensal_kw) or tarifa < 0:
        raise ValueError("Demandas e tarifa não podem ser negativas")

    teto = (max(dm_mensal_kw) * FATOR_MAX).to_integral_value(rounding=ROUND_FLOOR)
    inicio = dc_minima_kw
    fim = max(teto, inicio)

    curva: list[PontoCurva] = []
    melhor_dc = inicio
    melhor_custo: Decimal | None = None
    dc = inicio
    while dc <= fim:
        custo = custo_anual(dc, dm_mensal_kw, tarifa, tolerancia, multiplicador)
        curva.append(PontoCurva(dc, arredondar_moeda(custo)))
        if melhor_custo is None or custo < melhor_custo:
            melhor_dc, melhor_custo = dc, custo
        dc += 1
    assert melhor_custo is not None

    custo_atual = None
    economia = None
    if dc_atual_kw is not None:
        custo_atual_bruto = custo_anual(
            dc_atual_kw, dm_mensal_kw, tarifa, tolerancia, multiplicador
        )
        custo_atual = arredondar_moeda(custo_atual_bruto)
        economia = arredondar_moeda(custo_atual_bruto - melhor_custo)

    sens = tuple(
        Sensibilidade(
            v,
            melhor_dc * (1 + v),
            arredondar_moeda(
                custo_anual(melhor_dc * (1 + v), dm_mensal_kw, tarifa, tolerancia, multiplicador)
            ),
        )
        for v in VARIACOES
    )
    meses = len(dm_mensal_kw)
    trace = Trace().adicionar(
        PassoTrace(
            "demanda_otima",
            "Dc_otima = argmin Σ_mes [Dc x T + ult(Dm, Dc)], Dc em [Dc_min, 1,2 x max(Dm)], passo 1 kW",
            {
                "T": tarifa,
                "tolerancia": tolerancia,
                "multiplicador": multiplicador,
                "dc_min": dc_minima_kw,
                "max_dm": max(dm_mensal_kw),
                "meses": meses,
            },
            melhor_dc,
        )
    )
    return ResultadoDemandaOtima(
        dc_otima_kw=melhor_dc,
        custo_anual_otimo=arredondar_moeda(melhor_custo),
        custo_anual_atual=custo_atual,
        economia_anual=economia,
        curva=tuple(curva),
        sensibilidade=sens,
        meses=meses,
        indicativo=meses < MESES_MINIMOS,
        trace=trace,
    )


def otimizar_verde(
    dm_ponta_kw: Sequence[Decimal],
    dm_fora_ponta_kw: Sequence[Decimal],
    tarifa: Decimal,
    tolerancia: Decimal,
    multiplicador: Decimal,
    dc_minima_kw: Decimal,
    dc_atual_kw: Decimal | None = None,
) -> ResultadoDemandaOtima:
    """Verde: otimiza a demanda única, usando o maior Dm entre postos em cada mês."""
    if len(dm_ponta_kw) != len(dm_fora_ponta_kw):
        raise ValueError("Séries de ponta e fora de ponta devem ter o mesmo tamanho")
    unica = [max(a, b) for a, b in zip(dm_ponta_kw, dm_fora_ponta_kw, strict=True)]
    return otimizar_posto(unica, tarifa, tolerancia, multiplicador, dc_minima_kw, dc_atual_kw)


def otimizar_azul(
    dm_ponta_kw: Sequence[Decimal],
    dm_fora_ponta_kw: Sequence[Decimal],
    tarifa_ponta: Decimal,
    tarifa_fora_ponta: Decimal,
    tolerancia: Decimal,
    multiplicador: Decimal,
    dc_minima_kw: Decimal,
    dc_atual_ponta_kw: Decimal | None = None,
    dc_atual_fora_ponta_kw: Decimal | None = None,
) -> ResultadoDemandaOtimaAzul:
    """Azul: otimiza ponta e fora de ponta de forma independente."""
    ponta = otimizar_posto(
        dm_ponta_kw, tarifa_ponta, tolerancia, multiplicador, dc_minima_kw, dc_atual_ponta_kw
    )
    fora = otimizar_posto(
        dm_fora_ponta_kw,
        tarifa_fora_ponta,
        tolerancia,
        multiplicador,
        dc_minima_kw,
        dc_atual_fora_ponta_kw,
    )
    return ResultadoDemandaOtimaAzul(
        ponta=ponta,
        fora_ponta=fora,
        custo_anual_otimo=ponta.custo_anual_otimo + fora.custo_anual_otimo,
        trace=ponta.trace.concatenar(fora.trace),
    )
