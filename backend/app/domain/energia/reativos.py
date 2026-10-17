from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.energia.tipos import arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace

ZERO = Decimal(0)


class Precisao(StrEnum):
    HORARIA = "HORARIA"
    APROXIMADA = "APROXIMADA"


@dataclass(frozen=True, slots=True)
class IntervaloMedicao:
    """Intervalo de apuração (1 h): EEAM em kWh, EREAT em kvarh (indutiva ou capacitiva
    conforme a janela do intervalo) e PAM em kW."""

    eeam_kwh: Decimal
    ereat_kvarh: Decimal
    pam_kw: Decimal


@dataclass(frozen=True, slots=True)
class ResultadoReativos:
    precisao: Precisao
    ere_kwh: Decimal
    valor_ere: Decimal
    dre_kw: Decimal
    valor_dre: Decimal
    valor_total: Decimal
    intervalos_ignorados: int
    trace: Trace


def fator_potencia(eeam: Decimal, ereat: Decimal) -> Decimal | None:
    """fT = EEAM / sqrt(EEAM² + EREAT²); None quando indefinido (evita divisão por zero)."""
    if eeam <= 0:
        return None
    return eeam / (eeam * eeam + ereat * ereat).sqrt()


def apurar_reativos(
    intervalos: Sequence[IntervaloMedicao],
    fr: Decimal,
    vrere: Decimal,
    paf_kw: Decimal,
    vrdre: Decimal,
) -> ResultadoReativos:
    """ERE e DRE horárias (§3.4.2). Só intervalos com fT < fR geram excedente."""
    if fr <= 0 or vrere < 0 or vrdre < 0 or paf_kw < 0:
        raise ValueError("Parâmetros e tarifas inválidos")

    ere_total = ZERO
    max_demanda_corrigida = ZERO
    ignorados = 0
    trace = Trace()

    for i, it in enumerate(intervalos, start=1):
        if it.eeam_kwh < 0 or it.ereat_kvarh < 0 or it.pam_kw < 0:
            raise ValueError("Medições não podem ser negativas")
        ft = fator_potencia(it.eeam_kwh, it.ereat_kvarh)
        if ft is None:
            ignorados += 1
            continue
        if ft >= fr:
            continue
        ere = it.eeam_kwh * (fr / ft - 1)
        ere_total += ere
        corrigida = it.pam_kw * fr / ft
        max_demanda_corrigida = max(max_demanda_corrigida, corrigida)
        trace = trace.adicionar(
            PassoTrace(
                f"ere_intervalo_{i}",
                "ERE = EEAM x (fR / fT - 1), fT = EEAM / sqrt(EEAM² + EREAT²)",
                {
                    "EEAM": it.eeam_kwh,
                    "EREAT": it.ereat_kvarh,
                    "fR": fr,
                    "fT": ft,
                    "PAM": it.pam_kw,
                },
                ere,
            )
        )

    dre = max(ZERO, max_demanda_corrigida - paf_kw)
    valor_ere = arredondar_moeda(ere_total * vrere)
    valor_dre = arredondar_moeda(dre * vrdre)
    trace = trace.adicionar(
        PassoTrace(
            "valor_ere",
            "Σ ERE_T x VRERE",
            {"ERE_kWh": ere_total, "VRERE": vrere},
            valor_ere,
        )
    ).adicionar(
        PassoTrace(
            "valor_dre",
            "max(0, max_T(PAM x fR / fT) - PAF) x VRDRE",
            {"max_PAM_corrigida": max_demanda_corrigida, "PAF": paf_kw, "VRDRE": vrdre},
            valor_dre,
        )
    )
    return ResultadoReativos(
        precisao=Precisao.HORARIA,
        ere_kwh=ere_total,
        valor_ere=valor_ere,
        dre_kw=dre,
        valor_dre=valor_dre,
        valor_total=valor_ere + valor_dre,
        intervalos_ignorados=ignorados,
        trace=trace,
    )


def apurar_reativos_aproximado(
    eeam_kwh: Decimal,
    ereat_kvarh: Decimal,
    fr: Decimal,
    vrere: Decimal,
) -> ResultadoReativos:
    """Modo de triagem sem memória de massa: usa o fator de potência mensal.

    O valor cobrado real vem dos itens da fatura; DRE não é estimada.
    """
    if eeam_kwh < 0 or ereat_kvarh < 0 or fr <= 0 or vrere < 0:
        raise ValueError("Entradas inválidas")
    fm = fator_potencia(eeam_kwh, ereat_kvarh)
    ignorados = 1 if fm is None else 0
    ere = ZERO
    if fm is not None and fm < fr:
        ere = eeam_kwh * (fr / fm - 1)
    valor_ere = arredondar_moeda(ere * vrere)
    trace = Trace().adicionar(
        PassoTrace(
            "ere_aproximada",
            "ERE = kWh x (fR / fm - 1), fm = kWh / sqrt(kWh² + kvarh²) mensal",
            {"kWh": eeam_kwh, "kvarh": ereat_kvarh, "fR": fr, "fm": fm, "VRERE": vrere},
            ere,
        )
    )
    return ResultadoReativos(
        precisao=Precisao.APROXIMADA,
        ere_kwh=ere,
        valor_ere=valor_ere,
        dre_kw=ZERO,
        valor_dre=arredondar_moeda(ZERO),
        valor_total=valor_ere,
        intervalos_ignorados=ignorados,
        trace=trace,
    )
