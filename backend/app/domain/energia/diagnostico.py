from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.domain.energia.acl import CenarioPreco, EntradaACL, ResultadoACL, simular_acl
from app.domain.energia.demanda_otima import (
    MESES_MINIMOS,
    ResultadoDemandaOtima,
    ResultadoDemandaOtimaAzul,
    otimizar_azul,
    otimizar_verde,
)
from app.domain.energia.indicadores import (
    custo_medio_rs_mwh,
    fator_de_carga,
    pct_consumo_ponta,
    utilizacao_demanda,
)
from app.domain.energia.modalidade import (
    ComparacaoModalidades,
    HistoricoMes,
    TarifasAzul,
    TarifasVerde,
    comparar_modalidades,
)
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.reativos import (
    IntervaloMedicao,
    ResultadoReativos,
    apurar_reativos,
)
from app.domain.energia.tipos import Modalidade, Severidade, Subgrupo, arredondar_moeda
from app.domain.energia.trace import VERSAO_MOTOR, PassoTrace, Trace
from app.domain.energia.tributos import fator_tributos
from app.domain.energia.ultrapassagem import (
    ResultadoUltrapassagem,
    apurar_azul,
    apurar_verde,
)

ZERO = Decimal(0)
DOZE = Decimal(12)
CICLOS_PERIODO_TESTES = 3


class CodigoAchado(StrEnum):
    ULTRAPASSAGEM_DEMANDA = "ULTRAPASSAGEM_DEMANDA"
    DEMANDA_SUPERDIMENSIONADA = "DEMANDA_SUPERDIMENSIONADA"
    DEMANDA_OTIMA_DISPONIVEL = "DEMANDA_OTIMA_DISPONIVEL"
    FP_ABAIXO_REFERENCIA = "FP_ABAIXO_REFERENCIA"
    MODALIDADE_SUBOTIMA = "MODALIDADE_SUBOTIMA"
    DIVERGENCIA_FATURAMENTO = "DIVERGENCIA_FATURAMENTO"
    ELEGIVEL_ACL_VANTAJOSO = "ELEGIVEL_ACL_VANTAJOSO"
    CONSUMO_PONTA_ELEVADO = "CONSUMO_PONTA_ELEVADO"
    MULTA_JUROS_ATRASO = "MULTA_JUROS_ATRASO"
    PERIODO_DE_TESTES = "PERIODO_DE_TESTES"
    DADOS_INSUFICIENTES = "DADOS_INSUFICIENTES"
    MODALIDADE_INCOMPATIVEL = "MODALIDADE_INCOMPATIVEL"
    TIPO_REDE_AS_INCONSISTENTE = "TIPO_REDE_AS_INCONSISTENTE"
    MODALIDADE_NAO_SUPORTADA = "MODALIDADE_NAO_SUPORTADA"


@dataclass(frozen=True, slots=True)
class LimiaresAchados:
    """Limiares de disparo de achados que não são regulatórios (heurísticas de negócio)."""

    economia_minima_anual_rs: Decimal = Decimal("1000")
    pct_consumo_ponta: Decimal = Decimal("0.20")


@dataclass(frozen=True, slots=True)
class MesFatura:
    """Dados de um ciclo. Valores `faturado_*` e `valor_total_sem_cip_multas` são sem tributos."""

    referencia: str
    horas: Decimal
    dm_ponta_kw: Decimal
    dm_fora_ponta_kw: Decimal
    consumo_ponta_kwh: Decimal
    consumo_fora_ponta_kwh: Decimal
    valor_total_sem_cip_multas: Decimal | None = None
    multa_juros: Decimal = ZERO
    pis_cofins: Decimal | None = None
    icms: Decimal | None = None
    intervalos_reativos: tuple[IntervaloMedicao, ...] = ()
    faturado_demanda: Decimal | None = None
    faturado_ultrapassagem: Decimal | None = None
    faturado_reativos: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InsumosDiagnostico:
    subgrupo: Subgrupo
    modalidade_atual: Modalidade
    meses: tuple[MesFatura, ...]
    dc_unica_kw: Decimal | None = None
    dc_ponta_kw: Decimal | None = None
    dc_fora_ponta_kw: Decimal | None = None
    tarifas_verde: TarifasVerde | None = None
    tarifas_azul: TarifasAzul | None = None
    tipo_rede: str | None = None
    ciclos_contrato: int | None = None
    memoria_massa_incompleta: bool = False
    vrere_rs_kwh: Decimal | None = None
    vrdre_rs_kw: Decimal | None = None
    acl: EntradaACL | None = None
    cenarios_acl: tuple[CenarioPreco, ...] = ()
    fator_tributos_override: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Achado:
    codigo: CodigoAchado
    severidade: Severidade
    titulo: str
    descricao: str
    economia_anual_estimada: Decimal | None
    evidencias: tuple[str, ...]
    recomendacao: str
    premissas: tuple[str, ...]
    trace: Trace


@dataclass(frozen=True, slots=True)
class ApuracaoMensal:
    referencia: str
    ultrapassagem: ResultadoUltrapassagem
    reativos: ResultadoReativos | None


@dataclass(frozen=True, slots=True)
class ResultadoDiagnostico:
    versao_motor: str
    achados: tuple[Achado, ...]
    economia_anual_estimada: Decimal
    mensal: tuple[ApuracaoMensal, ...]
    indicadores: dict[str, Decimal | None]
    demanda_otima: ResultadoDemandaOtima | ResultadoDemandaOtimaAzul | None
    comparacao: ComparacaoModalidades | None
    acl: ResultadoACL | None
    fator_tributos: Decimal
    meses: int
    indicativo: bool
    premissas: tuple[str, ...]
    trace: Trace = field(default_factory=Trace)


def _achado(
    codigo: CodigoAchado,
    severidade: Severidade,
    titulo: str,
    descricao: str,
    recomendacao: str,
    economia: Decimal | None = None,
    evidencias: Sequence[str] = (),
    premissas: Sequence[str] = (),
    trace: Trace | None = None,
) -> Achado:
    return Achado(
        codigo,
        severidade,
        titulo,
        descricao,
        economia,
        tuple(evidencias),
        recomendacao,
        tuple(premissas),
        trace or Trace(),
    )


def _validar_contrato(ins: InsumosDiagnostico) -> None:
    if not ins.meses:
        raise ValueError("Informe ao menos um mês de fatura")
    if ins.modalidade_atual is Modalidade.VERDE:
        if ins.dc_unica_kw is None or ins.tarifas_verde is None:
            raise ValueError("Verde exige dc_unica_kw e tarifas_verde")
    elif ins.modalidade_atual is Modalidade.AZUL and (
        ins.dc_ponta_kw is None or ins.dc_fora_ponta_kw is None or ins.tarifas_azul is None
    ):
        raise ValueError("Azul exige dc_ponta_kw, dc_fora_ponta_kw e tarifas_azul")


def _validacoes_cadastrais(ins: InsumosDiagnostico, p: ParametrosRegulatorios) -> list[Achado]:
    achados: list[Achado] = []
    sg = ins.subgrupo.value
    if ins.modalidade_atual is Modalidade.CONVENCIONAL:
        achados.append(
            _achado(
                CodigoAchado.MODALIDADE_NAO_SUPORTADA,
                Severidade.INFO,
                "Modalidade Convencional não suportada",
                "A modalidade Convencional está em extinção e não é calculada pelo motor.",
                "Avaliar enquadramento em Azul ou Verde (backlog B-14).",
            )
        )
    elif (
        sg in p.modalidades_azul_obrigatorias and ins.modalidade_atual is not Modalidade.AZUL
    ) or (ins.modalidade_atual is Modalidade.VERDE and sg not in p.modalidades_verde_elegiveis):
        achados.append(
            _achado(
                CodigoAchado.MODALIDADE_INCOMPATIVEL,
                Severidade.ALTA,
                "Modalidade incompatível com o subgrupo",
                f"A modalidade {ins.modalidade_atual.value} não é elegível ao subgrupo {sg}.",
                "Corrigir o cadastro ou a extração da fatura.",
            )
        )
    if ins.subgrupo is Subgrupo.AS and ins.tipo_rede != "SUBTERRANEA":
        achados.append(
            _achado(
                CodigoAchado.TIPO_REDE_AS_INCONSISTENTE,
                Severidade.MEDIA,
                "Subgrupo AS sem rede subterrânea",
                "O subgrupo AS exige rede subterrânea; o tipo de rede informado é "
                f"{ins.tipo_rede or 'ausente'}.",
                "Verificar o enquadramento tarifário da unidade.",
            )
        )
    return achados


def _vazio(achados: list[Achado], meses: int, tributos: Decimal) -> ResultadoDiagnostico:
    return ResultadoDiagnostico(
        versao_motor=VERSAO_MOTOR,
        achados=tuple(achados),
        economia_anual_estimada=arredondar_moeda(ZERO),
        mensal=(),
        indicadores={},
        demanda_otima=None,
        comparacao=None,
        acl=None,
        fator_tributos=tributos,
        meses=meses,
        indicativo=True,
        premissas=("Cálculo interrompido por inconsistência cadastral",),
        trace=Trace(),
    )


def _fator_tributos(ins: InsumosDiagnostico) -> tuple[Decimal, str]:
    if ins.fator_tributos_override is not None:
        return ins.fator_tributos_override, "Fator de tributos informado manualmente"
    for m in reversed(ins.meses):
        if m.pis_cofins is not None and m.icms is not None:
            return (
                fator_tributos(m.pis_cofins, m.icms),
                f"Alíquotas efetivas da fatura {m.referencia} aplicadas à economia",
            )
    return Decimal(1), "Economias sem tributos: alíquotas não informadas"


def _apurar_mes(
    ins: InsumosDiagnostico, m: MesFatura, p: ParametrosRegulatorios
) -> ResultadoUltrapassagem:
    if ins.modalidade_atual is Modalidade.VERDE:
        assert ins.dc_unica_kw is not None and ins.tarifas_verde is not None
        return apurar_verde(
            ins.dc_unica_kw, m.dm_ponta_kw, m.dm_fora_ponta_kw, ins.tarifas_verde.demanda_rs_kw, p
        )
    assert ins.dc_ponta_kw is not None and ins.dc_fora_ponta_kw is not None
    assert ins.tarifas_azul is not None
    return apurar_azul(
        ins.dc_ponta_kw,
        ins.dc_fora_ponta_kw,
        m.dm_ponta_kw,
        m.dm_fora_ponta_kw,
        ins.tarifas_azul.demanda_ponta_rs_kw,
        ins.tarifas_azul.demanda_fora_ponta_rs_kw,
        p,
    )


def _paf(ins: InsumosDiagnostico) -> Decimal:
    if ins.modalidade_atual is Modalidade.VERDE:
        assert ins.dc_unica_kw is not None
        return ins.dc_unica_kw
    assert ins.dc_ponta_kw is not None and ins.dc_fora_ponta_kw is not None
    return max(ins.dc_ponta_kw, ins.dc_fora_ponta_kw)


def diagnosticar(
    insumos: InsumosDiagnostico,
    parametros: ParametrosRegulatorios,
    limiares: LimiaresAchados | None = None,
) -> ResultadoDiagnostico:
    """Orquestra o motor puro: apuração, indicadores, otimização, comparação, ACL e achados."""
    lim = limiares or LimiaresAchados()
    ins = insumos
    _validar_contrato(ins)
    n = len(ins.meses)
    anual = DOZE / Decimal(n)
    tributos, premissa_trib = _fator_tributos(ins)

    achados = _validacoes_cadastrais(ins, parametros)
    cadastral_bloqueante = {
        CodigoAchado.MODALIDADE_NAO_SUPORTADA,
        CodigoAchado.MODALIDADE_INCOMPATIVEL,
    }
    if any(a.codigo in cadastral_bloqueante for a in achados):
        return _vazio(achados, n, tributos)

    premissas = [premissa_trib]
    trace = Trace()

    mensal: list[ApuracaoMensal] = []
    for m in ins.meses:
        ult = _apurar_mes(ins, m, parametros)
        reativos = None
        if m.intervalos_reativos and ins.vrere_rs_kwh is not None and ins.vrdre_rs_kw is not None:
            reativos = apurar_reativos(
                m.intervalos_reativos,
                parametros.fator_potencia_referencia,
                ins.vrere_rs_kwh,
                _paf(ins),
                ins.vrdre_rs_kw,
            )
        mensal.append(ApuracaoMensal(m.referencia, ult, reativos))
        trace = trace.concatenar(ult.trace)
    if ins.modalidade_atual is Modalidade.AZUL:
        premissas.append("Reativos em Azul: PAF considerada como o maior Dc entre os postos")

    dm_p = [m.dm_ponta_kw for m in ins.meses]
    dm_f = [m.dm_fora_ponta_kw for m in ins.meses]
    cons_p = sum((m.consumo_ponta_kwh for m in ins.meses), ZERO)
    cons_f = sum((m.consumo_fora_ponta_kwh for m in ins.meses), ZERO)
    energia = cons_p + cons_f
    horas = sum((m.horas for m in ins.meses), ZERO)
    dm_max = max(max(dm_p), max(dm_f))
    dc_ref = ins.dc_unica_kw if ins.modalidade_atual is Modalidade.VERDE else _paf(ins)
    assert dc_ref is not None
    valores = [m.valor_total_sem_cip_multas for m in ins.meses]
    indicadores: dict[str, Decimal | None] = {
        "fator_de_carga": fator_de_carga(energia, dm_max, horas).valor,
        "utilizacao_demanda": utilizacao_demanda(dm_max, dc_ref).valor,
        "pct_consumo_ponta": pct_consumo_ponta(cons_p, cons_f).valor,
        "custo_medio_rs_mwh": (
            custo_medio_rs_mwh(sum((v for v in valores if v is not None), ZERO), energia).valor
            if all(v is not None for v in valores)
            else None
        ),
    }

    indicativo = n < MESES_MINIMOS or ins.memoria_massa_incompleta
    if indicativo:
        achados.append(
            _achado(
                CodigoAchado.DADOS_INSUFICIENTES,
                Severidade.INFO,
                "Dados insuficientes",
                f"Histórico de {n} mês(es) (mínimo {MESES_MINIMOS}) ou memória de massa "
                "incompleta; resultados indicativos.",
                "Coletar mais faturas e a memória de massa.",
            )
        )
        premissas.append(f"Valores anualizados por 12/{n} sobre o histórico informado")

    economias_nao_cumulativas: list[Decimal] = []

    # ultrapassagem
    total_ult = sum((r.ultrapassagem.valor_ultrapassagem for r in mensal), ZERO)
    meses_ult = [r.referencia for r in mensal if r.ultrapassagem.valor_ultrapassagem > 0]
    if meses_ult:
        eco = arredondar_moeda(total_ult * anual * tributos)
        achados.append(
            _achado(
                CodigoAchado.ULTRAPASSAGEM_DEMANDA,
                Severidade.ALTA if len(meses_ult) > 2 else Severidade.MEDIA,
                "Ultrapassagem de demanda",
                f"Ultrapassagem em {len(meses_ult)} de {n} mês(es).",
                "Reavaliar a demanda contratada ou gerenciar picos.",
                eco,
                [
                    f"{r.referencia}: R$ {r.ultrapassagem.valor_ultrapassagem}"
                    for r in mensal
                    if r.ultrapassagem.valor_ultrapassagem > 0
                ],
                [premissa_trib],
            )
        )

    # demanda ótima
    otima: ResultadoDemandaOtima | ResultadoDemandaOtimaAzul
    dc_min = parametros.demanda_minima_contratada_kw
    tol = parametros.tolerancia_ultrapassagem
    mult = parametros.multiplicador_ultrapassagem
    if ins.modalidade_atual is Modalidade.VERDE:
        assert ins.tarifas_verde is not None
        otima = otimizar_verde(
            dm_p, dm_f, ins.tarifas_verde.demanda_rs_kw, tol, mult, dc_min, ins.dc_unica_kw
        )
        bruta = otima.economia_anual or ZERO
        dc_texto = f"Dc ótima {otima.dc_otima_kw} kW (atual {ins.dc_unica_kw} kW)"
        ratios = {"única": dm_max / dc_ref} if dc_ref > 0 else {}
    else:
        assert ins.tarifas_azul is not None
        otima = otimizar_azul(
            dm_p,
            dm_f,
            ins.tarifas_azul.demanda_ponta_rs_kw,
            ins.tarifas_azul.demanda_fora_ponta_rs_kw,
            tol,
            mult,
            dc_min,
            ins.dc_ponta_kw,
            ins.dc_fora_ponta_kw,
        )
        bruta = (otima.ponta.economia_anual or ZERO) + (otima.fora_ponta.economia_anual or ZERO)
        dc_texto = (
            f"Dc ótima ponta {otima.ponta.dc_otima_kw} kW, "
            f"fora de ponta {otima.fora_ponta.dc_otima_kw} kW"
        )
        assert ins.dc_ponta_kw is not None and ins.dc_fora_ponta_kw is not None
        ratios = {}
        if ins.dc_ponta_kw > 0:
            ratios["ponta"] = max(dm_p) / ins.dc_ponta_kw
        if ins.dc_fora_ponta_kw > 0:
            ratios["fora de ponta"] = max(dm_f) / ins.dc_fora_ponta_kw
    trace = trace.concatenar(otima.trace)
    eco_otima = arredondar_moeda(bruta * anual * tributos)
    if eco_otima > lim.economia_minima_anual_rs:
        achados.append(
            _achado(
                CodigoAchado.DEMANDA_OTIMA_DISPONIVEL,
                Severidade.ALTA
                if eco_otima > 10 * lim.economia_minima_anual_rs
                else Severidade.MEDIA,
                "Ajuste de demanda contratada disponível",
                dc_texto,
                "Ajustar a demanda contratada ao ótimo, respeitando prazos contratuais.",
                eco_otima,
                [dc_texto],
                [premissa_trib, "Dc ótima calculada sobre o histórico informado"],
                otima.trace,
            )
        )
        economias_nao_cumulativas.append(eco_otima)

    sub = {k: v for k, v in ratios.items() if v < parametros.limiar_subutilizacao}
    if sub:
        achados.append(
            _achado(
                CodigoAchado.DEMANDA_SUPERDIMENSIONADA,
                Severidade.MEDIA,
                "Demanda contratada superdimensionada",
                "Dm máxima / Dc abaixo do limiar de subutilização.",
                "Reduzir a demanda contratada ao ótimo.",
                eco_otima if eco_otima > 0 else None,
                [f"{k}: Dm_max/Dc = {v.quantize(Decimal('0.0001'))}" for k, v in sub.items()],
                [f"Limiar de subutilização {parametros.limiar_subutilizacao}"],
            )
        )

    # reativos
    reat = [r for r in mensal if r.reativos is not None and r.reativos.valor_total > 0]
    if reat:
        total = sum((r.reativos.valor_total for r in reat if r.reativos), ZERO)
        achados.append(
            _achado(
                CodigoAchado.FP_ABAIXO_REFERENCIA,
                Severidade.MEDIA,
                "Fator de potência abaixo da referência",
                f"Energia/demanda reativa excedente em {len(reat)} mês(es).",
                "Avaliar correção do fator de potência (banco de capacitores/filtros).",
                arredondar_moeda(total * anual * tributos),
                [f"{r.referencia}: R$ {r.reativos.valor_total}" for r in reat if r.reativos],
                [premissa_trib],
                reat[0].reativos.trace if reat[0].reativos else None,
            )
        )

    # comparação de modalidades
    comparacao: ComparacaoModalidades | None = None
    elegivel_verde = ins.subgrupo.value in parametros.modalidades_verde_elegiveis
    if ins.tarifas_azul is not None and (not elegivel_verde or ins.tarifas_verde is not None):
        historico = [
            HistoricoMes(
                m.dm_ponta_kw, m.dm_fora_ponta_kw, m.consumo_ponta_kwh, m.consumo_fora_ponta_kwh
            )
            for m in ins.meses
        ]
        comparacao = comparar_modalidades(
            ins.subgrupo, historico, ins.tarifas_azul, ins.tarifas_verde, parametros
        )
        trace = trace.concatenar(comparacao.trace)
        eco_mod = arredondar_moeda(comparacao.diferenca_anual * anual * tributos)
        if (
            comparacao.recomendada is not ins.modalidade_atual
            and eco_mod > lim.economia_minima_anual_rs
        ):
            achados.append(
                _achado(
                    CodigoAchado.MODALIDADE_SUBOTIMA,
                    Severidade.ALTA,
                    "Modalidade tarifária subótima",
                    f"{comparacao.recomendada.value} tem menor custo anual que "
                    f"{ins.modalidade_atual.value}.",
                    "Avaliar migração entre Azul e Verde.",
                    eco_mod,
                    [comparacao.motivo],
                    [premissa_trib, "Ambas as modalidades com Dc ótima; tarifas sem tributos"],
                    comparacao.trace,
                )
            )
            economias_nao_cumulativas.append(eco_mod)
    else:
        premissas.append(
            "Comparação Azul × Verde não executada: tarifas da outra modalidade ausentes"
        )

    # divergências
    tol_rs = parametros.tolerancia_divergencia_item_rs
    diverg: list[str] = []
    for r, m in zip(mensal, ins.meses, strict=True):
        calc = {
            "demanda": (r.ultrapassagem.valor_demanda, m.faturado_demanda),
            "ultrapassagem": (r.ultrapassagem.valor_ultrapassagem, m.faturado_ultrapassagem),
            "reativos": (r.reativos.valor_total if r.reativos else None, m.faturado_reativos),
        }
        for item, (calculado, faturado) in calc.items():
            if (
                calculado is not None
                and faturado is not None
                and abs(calculado - faturado) > tol_rs
            ):
                diverg.append(
                    f"{m.referencia} {item}: calculado R$ {calculado}, faturado R$ {faturado}"
                )
    if diverg:
        achados.append(
            _achado(
                CodigoAchado.DIVERGENCIA_FATURAMENTO,
                Severidade.ALTA,
                "Divergência entre valor calculado e faturado",
                f"{len(diverg)} item(ns) acima da tolerância de R$ {tol_rs}.",
                "Contestar com a distribuidora ou revisar a extração.",
                None,
                diverg,
            )
        )

    # consumo na ponta
    pct = indicadores["pct_consumo_ponta"]
    if pct is not None and pct > lim.pct_consumo_ponta:
        achados.append(
            _achado(
                CodigoAchado.CONSUMO_PONTA_ELEVADO,
                Severidade.BAIXA,
                "Consumo na ponta elevado",
                f"{(pct * 100).quantize(Decimal('0.1'))}% do consumo ocorre na ponta.",
                "Avaliar deslocamento de carga ou geração na ponta.",
                evidencias=[f"pct_consumo_ponta = {pct}"],
                premissas=[f"Limiar de {lim.pct_consumo_ponta} (heurística de negócio)"],
            )
        )

    multas = sum((m.multa_juros for m in ins.meses), ZERO)
    if multas > 0:
        achados.append(
            _achado(
                CodigoAchado.MULTA_JUROS_ATRASO,
                Severidade.BAIXA,
                "Multas e juros por atraso",
                f"Total de R$ {multas} em multas e juros no período.",
                "Rever a gestão de vencimentos.",
                arredondar_moeda(multas * anual),
                [f"{m.referencia}: R$ {m.multa_juros}" for m in ins.meses if m.multa_juros > 0],
            )
        )

    if ins.ciclos_contrato is not None and ins.ciclos_contrato < CICLOS_PERIODO_TESTES:
        achados.append(
            _achado(
                CodigoAchado.PERIODO_DE_TESTES,
                Severidade.INFO,
                "Possível período de testes",
                f"Contrato com {ins.ciclos_contrato} ciclo(s) (< {CICLOS_PERIODO_TESTES}).",
                "Regras de ultrapassagem específicas podem se aplicar; o motor usa a regra geral.",
            )
        )

    # ACL
    acl: ResultadoACL | None = None
    if ins.acl is not None and ins.cenarios_acl:
        acl = simular_acl(ins.acl, ins.cenarios_acl, parametros)
        trace = trace.concatenar(acl.trace)
        base = next(
            (c for c in acl.cenarios if c.nome == "base"), acl.cenarios[len(acl.cenarios) // 2]
        )
        if base.economia_anual > lim.economia_minima_anual_rs:
            achados.append(
                _achado(
                    CodigoAchado.ELEGIVEL_ACL_VANTAJOSO,
                    Severidade.MEDIA,
                    "Migração ao mercado livre potencialmente vantajosa",
                    f"Economia estimada no cenário {base.nome}.",
                    "Iniciar estudo de migração ao ACL.",
                    base.economia_anual,
                    [f"Break-even: R$ {acl.break_even_rs_mwh.quantize(Decimal('0.01'))}/MWh"],
                    ["Preço da energia é premissa informada pelo engenheiro", *acl.checklist],
                    acl.trace,
                )
            )

    achados.sort(key=lambda a: a.economia_anual_estimada or ZERO, reverse=True)
    economia = max(economias_nao_cumulativas, default=ZERO)
    trace = trace.adicionar(
        PassoTrace(
            "economia_anual_estimada",
            "maior economia entre achados de demanda e modalidade (não cumulativas)",
            {"candidatas": len(economias_nao_cumulativas), "meses": n},
            economia,
        )
    )
    return ResultadoDiagnostico(
        versao_motor=VERSAO_MOTOR,
        achados=tuple(achados),
        economia_anual_estimada=arredondar_moeda(economia),
        mensal=tuple(mensal),
        indicadores=indicadores,
        demanda_otima=otima,
        comparacao=comparacao,
        acl=acl,
        fator_tributos=tributos,
        meses=n,
        indicativo=indicativo,
        premissas=tuple(premissas),
        trace=trace,
    )
