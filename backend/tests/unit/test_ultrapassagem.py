from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, Posto
from app.domain.energia.ultrapassagem import (
    apurar_azul,
    apurar_posto,
    apurar_verde,
)

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
        carga_minima_as_kw=D("0"),
        limite_varejista_kw=D("500"),
        prazo_notificacao_migracao_acl_dias=180,
        feriados_nacionais_ponta=(),
        limiar_subutilizacao=D("0.85"),
        tolerancia_divergencia_item_rs=D("1"),
        distribuidoras_suportadas=(),
        vigencia_referencia=date(2026, 10, 10),
        pendentes_validacao=(),
    )


def test_g01_verde_com_ultrapassagem(parametros: ParametrosRegulatorios) -> None:
    r = apurar_verde(
        dc_kw=D("300"),
        dm_ponta_kw=D("340"),
        dm_fora_ponta_kw=D("0"),
        tarifa_demanda=D("30.00"),
        parametros=parametros,
    )
    p = r.postos[0]
    assert r.modalidade is Modalidade.VERDE
    assert p.posto is Posto.UNICO
    assert p.limite_kw == D("315")
    assert p.valor_demanda == D("9000.00")
    assert p.valor_ultrapassagem == D("2400.00")
    assert p.valor_total == D("11400.00")
    assert r.valor_total == D("11400.00")
    assert len(r.trace.passos) >= 3


def test_g02a_limite_exato_nao_gera_ultrapassagem() -> None:
    p = apurar_posto(Posto.UNICO, D("300"), D("315"), D("30"), D("0.05"), D("2"))
    assert p.ultrapassagem_kw == D("0")
    assert p.valor_ultrapassagem == D("0.00")
    assert p.valor_total == D("9000.00")


def test_g02b_logo_acima_do_limite() -> None:
    p = apurar_posto(Posto.UNICO, D("300"), D("315.01"), D("30"), D("0.05"), D("2"))
    assert p.ultrapassagem_kw == D("15.01")
    assert p.valor_ultrapassagem == D("900.60")


def test_g13_verde_usa_maior_dm_entre_postos(
    parametros: ParametrosRegulatorios,
) -> None:
    r = apurar_verde(
        dc_kw=D("300"),
        dm_ponta_kw=D("340"),
        dm_fora_ponta_kw=D("200"),
        tarifa_demanda=D("30"),
        parametros=parametros,
    )
    p = r.postos[0]
    assert p.dm_kw == D("340")
    assert p.ultrapassagem_kw == D("40")
    assert p.valor_ultrapassagem == D("2400.00")


def test_g13_verde_dm_fora_ponta_maior(parametros: ParametrosRegulatorios) -> None:
    r = apurar_verde(D("300"), D("200"), D("340"), D("30"), parametros)
    assert r.postos[0].dm_kw == D("340")


def test_g14_azul_por_posto(parametros: ParametrosRegulatorios) -> None:
    r = apurar_azul(
        dc_ponta_kw=D("200"),
        dc_fora_ponta_kw=D("300"),
        dm_ponta_kw=D("250"),
        dm_fora_ponta_kw=D("280"),
        tarifa_demanda_ponta=D("30"),
        tarifa_demanda_fora_ponta=D("30"),
        parametros=parametros,
    )
    ponta, fora = r.postos
    assert r.modalidade is Modalidade.AZUL
    assert (ponta.posto, fora.posto) == (Posto.PONTA, Posto.FORA_PONTA)
    assert ponta.ultrapassagem_kw == D("50")
    assert ponta.valor_ultrapassagem == D("3000.00")
    assert fora.limite_kw == D("315")
    assert fora.ultrapassagem_kw == D("0")
    assert fora.valor_ultrapassagem == D("0.00")
    assert r.valor_ultrapassagem == D("3000.00")
    assert r.valor_demanda == D("200") * D("30") + D("300") * D("30")


def test_take_or_pay_fatura_dc_mesmo_com_dm_menor() -> None:
    p = apurar_posto(Posto.UNICO, D("300"), D("100"), D("30"), D("0.05"), D("2"))
    assert p.demanda_faturada_kw == D("300")
    assert p.valor_demanda == D("9000.00")
    assert p.ultrapassagem_kw == D("0")


def test_multiplicador_e_tolerancia_vem_dos_parametros(
    parametros: ParametrosRegulatorios,
) -> None:
    param3x = replace(parametros, multiplicador_ultrapassagem=D("3"))
    r = apurar_verde(D("300"), D("340"), D("0"), D("30"), param3x)
    assert r.valor_ultrapassagem == D("3600.00")


def test_arredonda_apenas_valor_final() -> None:
    p = apurar_posto(Posto.UNICO, D("100"), D("110.333"), D("10.005"), D("0.05"), D("2"))
    assert p.ultrapassagem_kw == D("10.333")
    assert p.valor_ultrapassagem == D("206.76")


@pytest.mark.parametrize(
    ("dc", "dm", "tarifa"),
    [("-1", "10", "30"), ("10", "-1", "30"), ("10", "10", "-1")],
)
def test_rejeita_entradas_negativas(dc: str, dm: str, tarifa: str) -> None:
    with pytest.raises(ValueError):
        apurar_posto(Posto.UNICO, D(dc), D(dm), D(tarifa), D("0.05"), D("2"))
