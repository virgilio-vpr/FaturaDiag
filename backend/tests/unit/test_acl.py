from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.acl import CenarioPreco, EntradaACL, simular_acl
from app.domain.energia.parametros import ParametrosRegulatorios

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


@pytest.fixture
def entrada() -> EntradaACL:
    return EntradaACL(
        consumo_mwh_mes=D("100"),
        te_cativa_rs_mwh=D("350"),
        encargos_rs_mwh=D("10"),
        custos_fixos_mes=D("1500"),
    )


CENARIOS = (
    CenarioPreco("conservador", D("300")),
    CenarioPreco("base", D("260")),
    CenarioPreco("otimista", D("240")),
)


def test_g06_economia_mensal_cenario_base(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    r = simular_acl(entrada, CENARIOS, parametros)
    base = next(c for c in r.cenarios if c.nome == "base")
    assert base.custo_cativo_mes == D("35000.00")
    assert base.custo_livre_mes == D("28500.00")
    assert base.economia_mensal == D("6500.00")
    assert base.economia_anual == D("78000.00")
    assert base.economia_pct == D("0.185714")
    assert r.trace.passos


def test_tres_cenarios_ordenados_conforme_entrada(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    r = simular_acl(entrada, CENARIOS, parametros)
    assert [c.nome for c in r.cenarios] == ["conservador", "base", "otimista"]
    # conservador: 100*300 + 1000 + 1500 = 32.500 -> economia 2.500
    assert r.cenarios[0].economia_mensal == D("2500.00")


def test_break_even_do_preco(entrada: EntradaACL, parametros: ParametrosRegulatorios) -> None:
    r = simular_acl(entrada, CENARIOS, parametros)
    # (35000 - 1000 - 1500) / 100
    assert r.break_even_rs_mwh == D("325")
    r2 = simular_acl(entrada, [CenarioPreco("be", r.break_even_rs_mwh)], parametros)
    assert r2.cenarios[0].economia_mensal == D("0.00")


def test_bandeira_so_entra_no_cativo(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    com_bandeira = replace(entrada, bandeira_mes=D("2000"))
    base = simular_acl(com_bandeira, CENARIOS, parametros).cenarios[1]
    assert base.custo_cativo_mes == D("37000.00")
    assert base.custo_livre_mes == D("28500.00")


def test_desconto_fonte_incentivada_reduz_tusd_do_livre(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    e = replace(
        entrada, tusd_demanda_mes=D("5000"), tusd_consumo_mes=D("3000"), desconto_tusd=D("0.5")
    )
    base = simular_acl(e, CENARIOS, parametros).cenarios[1]
    assert base.custo_cativo_mes == D("43000.00")
    assert base.custo_livre_mes == D("32500.00")  # 28500 + 8000 x 0,5
    assert base.economia_mensal == D("10500.00")


def test_payback_do_custo_unico_de_adequacao(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    e = replace(entrada, custo_adequacao_unico=D("26000"))
    r = simular_acl(e, CENARIOS, parametros)
    assert r.cenarios[1].payback_meses == D("4")
    assert simular_acl(entrada, CENARIOS, parametros).cenarios[1].payback_meses is None


def test_sem_economia_nao_ha_payback(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    e = replace(entrada, custo_adequacao_unico=D("1000"))
    r = simular_acl(e, [CenarioPreco("caro", D("400"))], parametros)
    assert r.cenarios[0].economia_mensal < 0
    assert r.cenarios[0].payback_meses is None


def test_sensibilidade_de_preco_em_torno_do_cenario_base(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    r = simular_acl(entrada, CENARIOS, parametros)
    assert [s.variacao for s in r.sensibilidade] == [
        D("-0.20"),
        D("-0.10"),
        D("0"),
        D("0.10"),
        D("0.20"),
    ]
    assert r.sensibilidade[2].economia_mensal == D("6500.00")
    assert r.sensibilidade[3].preco_rs_mwh == D("286.00")


def test_tributos_aplicados_por_lado(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    e = replace(entrada, fator_tributos_cativo=D("1.2"), fator_tributos_livre=D("1.1"))
    base = simular_acl(e, CENARIOS, parametros).cenarios[1]
    assert base.custo_cativo_mes == D("42000.00")
    assert base.custo_livre_mes == D("31350.00")


def test_checklist_usa_parametros_regulatorios(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    r = simular_acl(entrada, CENARIOS, parametros)
    texto = " ".join(r.checklist)
    assert "90 dias" in texto
    assert "500" in texto


def test_rejeita_entradas_invalidas(
    entrada: EntradaACL, parametros: ParametrosRegulatorios
) -> None:
    with pytest.raises(ValueError):
        simular_acl(entrada, [], parametros)
    with pytest.raises(ValueError):
        simular_acl(replace(entrada, consumo_mwh_mes=D("0")), CENARIOS, parametros)
    with pytest.raises(ValueError):
        simular_acl(replace(entrada, desconto_tusd=D("1.5")), CENARIOS, parametros)
    with pytest.raises(ValueError):
        simular_acl(entrada, [CenarioPreco("x", D("-1"))], parametros)
