from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.acl import CenarioPreco, EntradaACL
from app.domain.energia.diagnostico import (
    CodigoAchado,
    InsumosDiagnostico,
    LimiaresAchados,
    MesFatura,
    diagnosticar,
)
from app.domain.energia.modalidade import TarifasAzul, TarifasVerde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.reativos import IntervaloMedicao
from app.domain.energia.tipos import Modalidade, Severidade, Subgrupo
from app.domain.energia.trace import VERSAO_MOTOR

D = Decimal


@pytest.fixture
def parametros() -> ParametrosRegulatorios:
    return ParametrosRegulatorios(
        tolerancia_ultrapassagem=D("0.05"),
        multiplicador_ultrapassagem=D("2"),
        fator_potencia_referencia=D("0.92"),
        intervalo_apuracao_fp_min=60,
        janela_indutiva="06:00-24:00",
        janela_capacitiva="00:00-06:00",
        demanda_minima_contratada_kw=D("30"),
        modalidades_verde_elegiveis=("A3a", "A4", "AS"),
        modalidades_azul_obrigatorias=("A1", "A2", "A3"),
        subgrupos_prioritarios=("A4", "AS"),
        carga_minima_as_kw=D("75"),
        limite_varejista_kw=D("500"),
        prazo_notificacao_migracao_acl_dias=90,
        feriados_nacionais_ponta=(),
        limiar_subutilizacao=D("0.85"),
        tolerancia_divergencia_item_rs=D("0.05"),
        distribuidoras_suportadas=(),
        vigencia_referencia=date(2026, 10, 10),
        pendentes_validacao=(),
    )


DM = [D(x) for x in (280, 290, 300, 310, 320, 330, 340, 330, 320, 310, 300, 290)]
VERDE = TarifasVerde(D("30"), D("0.8"), D("0.4"))
AZUL = TarifasAzul(D("40"), D("30"), D("0.8"), D("0.4"))


def meses(dms: list[Decimal] = DM, **kw: object) -> tuple[MesFatura, ...]:
    return tuple(
        MesFatura(
            referencia=f"2026-{i:02d}",
            horas=D("720"),
            dm_ponta_kw=D("100"),
            dm_fora_ponta_kw=dm,
            consumo_ponta_kwh=D("10000"),
            consumo_fora_ponta_kwh=D("90000"),
            **kw,  # type: ignore[arg-type]
        )
        for i, dm in enumerate(dms, start=1)
    )


def insumos_verde(**kw: object) -> InsumosDiagnostico:
    base: dict[str, object] = {
        "subgrupo": Subgrupo.A4,
        "modalidade_atual": Modalidade.VERDE,
        "dc_unica_kw": D("300"),
        "tarifas_verde": VERDE,
        "meses": meses(),
    }
    base.update(kw)
    return InsumosDiagnostico(**base)  # type: ignore[arg-type]


def codigos(r) -> set[CodigoAchado]:  # type: ignore[no-untyped-def]
    return {a.codigo for a in r.achados}


def achado(r, codigo: CodigoAchado):  # type: ignore[no-untyped-def]
    return next(a for a in r.achados if a.codigo is codigo)


def test_verde_com_ultrapassagem_e_demanda_otima(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(), parametros)
    assert r.versao_motor == VERSAO_MOTOR
    assert CodigoAchado.ULTRAPASSAGEM_DEMANDA in codigos(r)
    a = achado(r, CodigoAchado.DEMANDA_OTIMA_DISPONIVEL)
    assert a.economia_anual_estimada == D("1500.00")
    assert a.trace.passos and a.evidencias and a.recomendacao
    assert r.demanda_otima is not None
    assert r.economia_anual_estimada == D("1500.00")
    assert r.trace.passos


def test_ultrapassagem_mensal_e_valor_anualizado(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(), parametros)
    assert len(r.mensal) == 12
    assert sum(m.ultrapassagem.valor_ultrapassagem for m in r.mensal) == D("8400.00")
    assert achado(r, CodigoAchado.ULTRAPASSAGEM_DEMANDA).economia_anual_estimada == D("8400.00")
    assert achado(r, CodigoAchado.ULTRAPASSAGEM_DEMANDA).severidade in (
        Severidade.MEDIA,
        Severidade.ALTA,
    )


def test_sem_ultrapassagem_nao_gera_achado(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(dc_unica_kw=D("340")), parametros)
    assert CodigoAchado.ULTRAPASSAGEM_DEMANDA not in codigos(r)


def test_demanda_superdimensionada(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(dc_unica_kw=D("500")), parametros)
    assert CodigoAchado.DEMANDA_SUPERDIMENSIONADA in codigos(r)
    assert CodigoAchado.DEMANDA_OTIMA_DISPONIVEL in codigos(r)


def test_historico_curto_gera_dados_insuficientes(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(meses=meses(DM[:6])), parametros)
    assert CodigoAchado.DADOS_INSUFICIENTES in codigos(r)
    assert r.indicativo is True


def test_modalidade_suboptima_quando_azul_mais_barata(
    parametros: ParametrosRegulatorios,
) -> None:
    caro = TarifasVerde(D("90"), D("0.8"), D("0.4"))
    r = diagnosticar(insumos_verde(tarifas_verde=caro, tarifas_azul=AZUL), parametros)
    a = achado(r, CodigoAchado.MODALIDADE_SUBOTIMA)
    assert r.comparacao is not None and r.comparacao.recomendada is Modalidade.AZUL
    assert a.economia_anual_estimada == r.comparacao.diferenca_anual


def test_sem_tarifa_da_outra_modalidade_comparacao_nao_executada(
    parametros: ParametrosRegulatorios,
) -> None:
    r = diagnosticar(insumos_verde(), parametros)
    assert r.comparacao is None
    assert any("Azul" in p for p in r.premissas)


def test_azul_apura_por_posto(parametros: ParametrosRegulatorios) -> None:
    ins = InsumosDiagnostico(
        subgrupo=Subgrupo.A4,
        modalidade_atual=Modalidade.AZUL,
        dc_ponta_kw=D("200"),
        dc_fora_ponta_kw=D("300"),
        tarifas_azul=AZUL,
        meses=meses([D("280")] * 12),
    )
    r = diagnosticar(ins, parametros)
    assert r.mensal[0].ultrapassagem.modalidade is Modalidade.AZUL
    assert r.mensal[0].ultrapassagem.postos[0].ultrapassagem_kw == D("0")
    assert r.demanda_otima is not None


def test_consumo_ponta_elevado(parametros: ParametrosRegulatorios) -> None:
    ms = tuple(
        replace(m, consumo_ponta_kwh=D("50000"), consumo_fora_ponta_kwh=D("50000")) for m in meses()
    )
    r = diagnosticar(
        insumos_verde(meses=ms), parametros, LimiaresAchados(pct_consumo_ponta=D("0.30"))
    )
    assert CodigoAchado.CONSUMO_PONTA_ELEVADO in codigos(r)
    assert r.indicadores["pct_consumo_ponta"] == D("0.5")


def test_multa_juros_e_periodo_de_testes(parametros: ParametrosRegulatorios) -> None:
    ms = tuple(replace(m, multa_juros=D("10")) for m in meses())
    r = diagnosticar(insumos_verde(meses=ms, ciclos_contrato=2), parametros)
    assert achado(r, CodigoAchado.MULTA_JUROS_ATRASO).evidencias
    assert CodigoAchado.PERIODO_DE_TESTES in codigos(r)
    r2 = diagnosticar(insumos_verde(ciclos_contrato=3), parametros)
    assert CodigoAchado.PERIODO_DE_TESTES not in codigos(r2)


def test_divergencia_de_faturamento(parametros: ParametrosRegulatorios) -> None:
    ms = list(meses())
    ms[0] = replace(ms[0], faturado_demanda=D("9100.00"))  # calculado: 9000,00
    ms[1] = replace(ms[1], faturado_demanda=D("9000.04"))  # dentro da tolerância de 0,05
    r = diagnosticar(insumos_verde(meses=tuple(ms)), parametros)
    a = achado(r, CodigoAchado.DIVERGENCIA_FATURAMENTO)
    assert len(a.evidencias) == 1 and "2026-01" in a.evidencias[0]


def test_reativos_horarios_geram_fp_abaixo_da_referencia(
    parametros: ParametrosRegulatorios,
) -> None:
    ms = tuple(
        replace(m, intervalos_reativos=(IntervaloMedicao(D("100"), D("75"), D("280")),))
        for m in meses()
    )
    ins = insumos_verde(meses=ms, vrere_rs_kwh=D("0.5"), vrdre_rs_kw=D("30"))
    r = diagnosticar(ins, parametros)
    assert CodigoAchado.FP_ABAIXO_REFERENCIA in codigos(r)
    reativos = r.mensal[0].reativos
    assert reativos is not None and reativos.valor_total == D("667.50")


def test_acl_vantajoso(parametros: ParametrosRegulatorios) -> None:
    acl = EntradaACL(D("100"), D("350"), D("10"), D("1500"))
    ins = insumos_verde(acl=acl, cenarios_acl=(CenarioPreco("base", D("260")),))
    r = diagnosticar(ins, parametros)
    assert r.acl is not None
    assert achado(r, CodigoAchado.ELEGIVEL_ACL_VANTAJOSO).economia_anual_estimada == D("78000.00")


def test_convencional_nao_e_calculada(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(modalidade_atual=Modalidade.CONVENCIONAL), parametros)
    assert codigos(r) == {CodigoAchado.MODALIDADE_NAO_SUPORTADA}
    assert r.mensal == ()


def test_modalidade_incompativel_com_subgrupo(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(subgrupo=Subgrupo.A3), parametros)
    assert codigos(r) == {CodigoAchado.MODALIDADE_INCOMPATIVEL}
    assert r.mensal == ()


def test_subgrupo_as_sem_rede_subterranea(parametros: ParametrosRegulatorios) -> None:
    r = diagnosticar(insumos_verde(subgrupo=Subgrupo.AS, tipo_rede="AEREA"), parametros)
    assert CodigoAchado.TIPO_REDE_AS_INCONSISTENTE in codigos(r)
    r2 = diagnosticar(insumos_verde(subgrupo=Subgrupo.AS, tipo_rede="SUBTERRANEA"), parametros)
    assert CodigoAchado.TIPO_REDE_AS_INCONSISTENTE not in codigos(r2)


def test_tributos_do_ultimo_mes_aplicados_a_economia(parametros: ParametrosRegulatorios) -> None:
    ms = tuple(replace(m, pis_cofins=D("0.0565"), icms=D("0.18")) for m in meses())
    r = diagnosticar(insumos_verde(meses=ms), parametros)
    assert r.fator_tributos.quantize(D("0.000001")) == D("1.292541")
    assert achado(r, CodigoAchado.DEMANDA_OTIMA_DISPONIVEL).economia_anual_estimada == D("1938.81")


def test_insumos_invalidos(parametros: ParametrosRegulatorios) -> None:
    with pytest.raises(ValueError):
        diagnosticar(insumos_verde(meses=()), parametros)
    with pytest.raises(ValueError):
        diagnosticar(insumos_verde(dc_unica_kw=None), parametros)
    with pytest.raises(ValueError):
        diagnosticar(insumos_verde(tarifas_verde=None), parametros)
