from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.energia.tipos import arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace

UM = Decimal(1)


@dataclass(frozen=True, slots=True)
class ResultadoTributos:
    valor_sem_tributos: Decimal
    fator: Decimal
    valor_com_tributos: Decimal
    valor_tributos: Decimal
    trace: Trace


def fator_tributos(pis_cofins: Decimal, icms: Decimal) -> Decimal:
    """ICMS e PIS/COFINS "por dentro": 1 / ((1 - pis_cofins) x (1 - icms))."""
    for aliquota in (pis_cofins, icms):
        if aliquota < 0 or aliquota >= 1:
            raise ValueError("Alíquota deve estar no intervalo [0, 1)")
    return UM / ((UM - pis_cofins) * (UM - icms))


def aplicar_tributos(
    valor_sem_tributos: Decimal,
    pis_cofins: Decimal,
    icms: Decimal,
    fator_override: Decimal | None = None,
) -> ResultadoTributos:
    """Aplica tributos sobre valor sem tributos (§3.4.3).

    Alíquotas devem ser as efetivas da fatura; `fator_override` permite ajuste
    por distribuidora quando o fator de composição for validado.
    """
    if valor_sem_tributos < 0:
        raise ValueError("Valor não pode ser negativo")
    if fator_override is not None:
        if fator_override <= 0:
            raise ValueError("Fator de override deve ser positivo")
        fator = fator_override
        passo = PassoTrace(
            "fator_tributos_override",
            "fator informado por distribuidora (override)",
            {"pis_cofins": pis_cofins, "icms": icms},
            fator,
        )
    else:
        fator = fator_tributos(pis_cofins, icms)
        passo = PassoTrace(
            "fator_tributos",
            "1 / ((1 - pis_cofins) x (1 - icms))",
            {"pis_cofins": pis_cofins, "icms": icms},
            fator,
        )
    com = arredondar_moeda(valor_sem_tributos * fator)
    sem = valor_sem_tributos
    trace = (
        Trace()
        .adicionar(passo)
        .adicionar(
            PassoTrace(
                "valor_com_tributos",
                "valor_sem_tributos x fator_tributos",
                {"valor_sem_tributos": sem, "fator": fator},
                com,
            )
        )
    )
    return ResultadoTributos(
        valor_sem_tributos=sem,
        fator=fator,
        valor_com_tributos=com,
        valor_tributos=com - arredondar_moeda(sem),
        trace=trace,
    )
