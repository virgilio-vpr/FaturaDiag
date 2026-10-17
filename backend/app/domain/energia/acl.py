from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import arredondar_moeda
from app.domain.energia.trace import PassoTrace, Trace

ZERO = Decimal(0)
UM = Decimal(1)
DOZE = Decimal(12)
VARIACOES_PRECO = (Decimal("-0.20"), Decimal("-0.10"), Decimal(0), Decimal("0.10"), Decimal("0.20"))
SEIS_CASAS = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class CenarioPreco:
    """Preço da energia no ACL: sempre informado pelo engenheiro, nunca inferido."""

    nome: str
    preco_rs_mwh: Decimal


@dataclass(frozen=True, slots=True)
class EntradaACL:
    """Valores mensais sem tributos. A bandeira tarifária existe só no mercado cativo."""

    consumo_mwh_mes: Decimal
    te_cativa_rs_mwh: Decimal
    encargos_rs_mwh: Decimal
    custos_fixos_mes: Decimal
    tusd_demanda_mes: Decimal = ZERO
    tusd_consumo_mes: Decimal = ZERO
    bandeira_mes: Decimal = ZERO
    desconto_tusd: Decimal = ZERO
    fator_tributos_cativo: Decimal = UM
    fator_tributos_livre: Decimal = UM
    custo_adequacao_unico: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class ResultadoCenarioACL:
    nome: str
    preco_rs_mwh: Decimal
    custo_cativo_mes: Decimal
    custo_livre_mes: Decimal
    economia_mensal: Decimal
    economia_anual: Decimal
    economia_pct: Decimal
    payback_meses: Decimal | None


@dataclass(frozen=True, slots=True)
class PontoSensibilidade:
    variacao: Decimal
    preco_rs_mwh: Decimal
    economia_mensal: Decimal


@dataclass(frozen=True, slots=True)
class ResultadoACL:
    cenarios: tuple[ResultadoCenarioACL, ...]
    break_even_rs_mwh: Decimal
    sensibilidade: tuple[PontoSensibilidade, ...]
    checklist: tuple[str, ...]
    trace: Trace


def _validar(entrada: EntradaACL, cenarios: Sequence[CenarioPreco]) -> None:
    if not cenarios:
        raise ValueError("Informe ao menos um cenário de preço")
    if entrada.consumo_mwh_mes <= 0:
        raise ValueError("Consumo mensal deve ser positivo")
    if not ZERO <= entrada.desconto_tusd <= UM:
        raise ValueError("Desconto de TUSD deve estar entre 0 e 1")
    if entrada.fator_tributos_cativo <= 0 or entrada.fator_tributos_livre <= 0:
        raise ValueError("Fatores de tributos devem ser positivos")
    valores = (
        entrada.te_cativa_rs_mwh,
        entrada.encargos_rs_mwh,
        entrada.custos_fixos_mes,
        entrada.tusd_demanda_mes,
        entrada.tusd_consumo_mes,
        entrada.bandeira_mes,
        entrada.custo_adequacao_unico,
        *(c.preco_rs_mwh for c in cenarios),
    )
    if any(v < 0 for v in valores):
        raise ValueError("Valores monetários não podem ser negativos")


def _custo_cativo(e: EntradaACL) -> Decimal:
    bruto = e.tusd_demanda_mes + e.tusd_consumo_mes + e.te_cativa_rs_mwh * e.consumo_mwh_mes
    return (bruto + e.bandeira_mes) * e.fator_tributos_cativo


def _custo_livre(e: EntradaACL, preco: Decimal) -> Decimal:
    tusd_livre = (e.tusd_demanda_mes + e.tusd_consumo_mes) * (UM - e.desconto_tusd)
    bruto = tusd_livre + e.consumo_mwh_mes * (preco + e.encargos_rs_mwh) + e.custos_fixos_mes
    return bruto * e.fator_tributos_livre


def _checklist(p: ParametrosRegulatorios) -> tuple[str, ...]:
    return (
        f"Aviso prévio à distribuidora: {p.prazo_notificacao_migracao_acl_dias} dias",
        "Garantias financeiras exigidas pela CCEE/comercializador",
        "Sazonalização e flexibilidade contratual da energia",
        f"UCs abaixo de {p.limite_varejista_kw} kW migram via comercializador varejista",
        "Perda de benefícios do mercado cativo (ex.: bandeiras, tarifa regulada)",
        "Riscos de preço e de contraparte",
    )


def simular_acl(
    entrada: EntradaACL,
    cenarios: Sequence[CenarioPreco],
    parametros: ParametrosRegulatorios,
) -> ResultadoACL:
    """Simula migração ao ACL (§3.4.7). O preço da energia é sempre premissa informada."""
    _validar(entrada, cenarios)
    cativo = _custo_cativo(entrada)
    trace = Trace().adicionar(
        PassoTrace(
            "custo_cativo",
            "(TUSD demanda + TUSD consumo + TE x MWh + bandeira) x fator_tributos",
            {
                "TE_rs_mwh": entrada.te_cativa_rs_mwh,
                "consumo_mwh": entrada.consumo_mwh_mes,
                "bandeira": entrada.bandeira_mes,
                "fator": entrada.fator_tributos_cativo,
            },
            cativo,
        )
    )

    resultados: list[ResultadoCenarioACL] = []
    for c in cenarios:
        livre = _custo_livre(entrada, c.preco_rs_mwh)
        economia = cativo - livre
        payback = None
        if economia > 0 and entrada.custo_adequacao_unico > 0:
            payback = entrada.custo_adequacao_unico / economia
        resultados.append(
            ResultadoCenarioACL(
                nome=c.nome,
                preco_rs_mwh=c.preco_rs_mwh,
                custo_cativo_mes=arredondar_moeda(cativo),
                custo_livre_mes=arredondar_moeda(livre),
                economia_mensal=arredondar_moeda(economia),
                economia_anual=arredondar_moeda(economia * DOZE),
                economia_pct=(economia / cativo).quantize(SEIS_CASAS, rounding=ROUND_HALF_UP)
                if cativo > 0
                else ZERO,
                payback_meses=payback,
            )
        )
        trace = trace.adicionar(
            PassoTrace(
                f"cenario_{c.nome}",
                "livre = (TUSD' + MWh x (preço + encargos) + custos fixos) x fator'; "
                "economia = cativo - livre",
                {
                    "preco_rs_mwh": c.preco_rs_mwh,
                    "encargos_rs_mwh": entrada.encargos_rs_mwh,
                    "custos_fixos": entrada.custos_fixos_mes,
                    "desconto_tusd": entrada.desconto_tusd,
                },
                economia,
            )
        )

    # preço em que economia = 0, resolvendo custo_livre(preço) = custo_cativo
    sem_energia = _custo_livre(entrada, ZERO)
    break_even = (cativo - sem_energia) / (entrada.consumo_mwh_mes * entrada.fator_tributos_livre)
    trace = trace.adicionar(
        PassoTrace(
            "break_even_preco",
            "preço máximo em que custo_livre = custo_cativo",
            {"custo_cativo": cativo},
            break_even,
        )
    )

    base = next((c for c in cenarios if c.nome == "base"), cenarios[len(cenarios) // 2])
    sens = tuple(
        PontoSensibilidade(
            v,
            base.preco_rs_mwh * (UM + v),
            arredondar_moeda(cativo - _custo_livre(entrada, base.preco_rs_mwh * (UM + v))),
        )
        for v in VARIACOES_PRECO
    )
    return ResultadoACL(
        cenarios=tuple(resultados),
        break_even_rs_mwh=break_even,
        sensibilidade=sens,
        checklist=_checklist(parametros),
        trace=trace,
    )
