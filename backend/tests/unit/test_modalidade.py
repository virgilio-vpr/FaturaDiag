from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.modalidade import (
    HistoricoMes,
    TarifasAzul,
    TarifasVerde,
    comparar_modalidades,
)
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, Subgrupo

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


def historico(meses: int = 12) -> list[HistoricoMes]:
    return [HistoricoMes(D("100"), D("200"), D("10000"), D("40000")) for _ in range(meses)]


AZUL = TarifasAzul(D("40"), D("20"), D("0.8"), D("0.4"))


def test_verde_mais_barata_e_recomendada(parametros: ParametrosRegulatorios) -> None:
    verde = TarifasVerde(D("25"), D("0.8"), D("0.4"))
    r = comparar_modalidades(Subgrupo.A4, historico(), AZUL, verde, parametros)
    assert r.azul is not None and r.verde is not None
    assert r.azul.dc_kw == {"PONTA": D("96"), "FORA_PONTA": D("191")}
    assert r.azul.custo_demanda == D("91920.00")
    assert r.azul.custo_consumo == D("288000.00")
    assert r.azul.custo_total == D("379920.00")
    assert r.verde.dc_kw == {"UNICO": D("191")}
    assert r.verde.custo_total == D("345300.00")
    assert r.recomendada is Modalidade.VERDE
    assert r.diferenca_anual == D("34620.00")
    assert r.indicativo is False
    assert r.trace.passos


def test_azul_mais_barata_e_recomendada(parametros: ParametrosRegulatorios) -> None:
    verde = TarifasVerde(D("50"), D("0.8"), D("0.4"))
    r = comparar_modalidades(Subgrupo.AS, historico(), AZUL, verde, parametros)
    assert r.recomendada is Modalidade.AZUL
    assert r.diferenca_anual == D("22680.00")


def test_subgrupo_azul_obrigatorio_so_avalia_azul(parametros: ParametrosRegulatorios) -> None:
    r = comparar_modalidades(Subgrupo.A3, historico(), AZUL, None, parametros)
    assert r.verde is None
    assert r.recomendada is Modalidade.AZUL
    assert r.diferenca_anual == D("0.00")
    assert "não elegível" in r.motivo


def test_verde_inelegivel_ignora_tarifa_verde_fornecida(
    parametros: ParametrosRegulatorios,
) -> None:
    verde = TarifasVerde(D("1"), D("0.1"), D("0.1"))
    r = comparar_modalidades(Subgrupo.A2, historico(), AZUL, verde, parametros)
    assert r.verde is None and r.recomendada is Modalidade.AZUL


def test_elegibilidade_vem_dos_parametros(parametros: ParametrosRegulatorios) -> None:
    so_azul = replace(parametros, modalidades_verde_elegiveis=())
    verde = TarifasVerde(D("1"), D("0.1"), D("0.1"))
    r = comparar_modalidades(Subgrupo.A4, historico(), AZUL, verde, so_azul)
    assert r.verde is None


def test_historico_curto_e_indicativo(parametros: ParametrosRegulatorios) -> None:
    verde = TarifasVerde(D("25"), D("0.8"), D("0.4"))
    r = comparar_modalidades(Subgrupo.A4, historico(6), AZUL, verde, parametros)
    assert r.indicativo is True and r.meses == 6


def test_tarifa_ausente_para_modalidade_elegivel_e_erro(
    parametros: ParametrosRegulatorios,
) -> None:
    with pytest.raises(ValueError, match="Tarifas"):
        comparar_modalidades(Subgrupo.A4, historico(), AZUL, None, parametros)


def test_historico_vazio_e_erro(parametros: ParametrosRegulatorios) -> None:
    with pytest.raises(ValueError):
        comparar_modalidades(Subgrupo.A4, [], AZUL, None, parametros)
