from __future__ import annotations

from decimal import Decimal

import pytest
from app.domain.energia.demanda_otima import otimizar_azul, otimizar_posto, otimizar_verde

D = Decimal
DM = [D(x) for x in (280, 290, 300, 310, 320, 330, 340, 330, 320, 310, 300, 290)]
TOL = D("0.05")
MULT = D("2")
T = D("30")
DMIN = D("30")


def test_g04_demanda_otima() -> None:
    r = otimizar_posto(DM, T, TOL, MULT, DMIN, dc_atual_kw=D("300"))
    assert r.dc_otima_kw == D("305")
    assert r.custo_anual_otimo == D("114900.00")
    assert r.custo_anual_atual == D("116400.00")
    assert r.economia_anual == D("1500.00")
    assert r.indicativo is False


def test_g04_custo_com_dc_340() -> None:
    r = otimizar_posto(DM, T, TOL, MULT, DMIN, dc_atual_kw=D("340"))
    assert r.custo_anual_atual == D("122400.00")
    assert r.economia_anual == D("7500.00")


def test_curva_custo_cobre_faixa_com_passo_de_1kw() -> None:
    r = otimizar_posto(DM, T, TOL, MULT, DMIN)
    dcs = [p.dc_kw for p in r.curva]
    assert dcs[0] == DMIN
    assert dcs[-1] == D("408")  # floor(1,2 x 340)
    assert all(b - a == 1 for a, b in zip(dcs, dcs[1:], strict=False))
    assert min(p.custo_anual for p in r.curva) == r.custo_anual_otimo.quantize(D("0.01"))


def test_desempate_escolhe_menor_dc() -> None:
    # Dc=96 já cobre Dm=100 pela tolerância (limite 100,8); acima disso só encarece
    r = otimizar_posto([D("100")] * 12, T, TOL, MULT, DMIN)
    assert r.dc_otima_kw == D("96")


def test_sensibilidade_mais_menos_5_e_10_por_cento() -> None:
    r = otimizar_posto(DM, T, TOL, MULT, DMIN)
    assert [s.variacao for s in r.sensibilidade] == [D("-0.10"), D("-0.05"), D("0.05"), D("0.10")]
    assert r.sensibilidade[2].dc_kw == D("305") * D("1.05")


def test_menos_de_12_meses_e_indicativo() -> None:
    r = otimizar_posto(DM[:6], T, TOL, MULT, DMIN)
    assert r.indicativo is True
    assert r.meses == 6


def test_piso_de_demanda_minima() -> None:
    r = otimizar_posto([D("10")] * 12, T, TOL, MULT, D("30"))
    assert r.dc_otima_kw == D("30")


def test_verde_usa_maior_dm_entre_postos_a_cada_mes() -> None:
    ponta = [D("100")] * 12
    fora = DM
    r = otimizar_verde(ponta, fora, T, TOL, MULT, DMIN, dc_atual_kw=D("300"))
    assert r.dc_otima_kw == D("305")
    assert r.economia_anual == D("1500.00")


def test_azul_otimiza_postos_de_forma_independente() -> None:
    r = otimizar_azul(
        dm_ponta_kw=DM,
        dm_fora_ponta_kw=[D("100")] * 12,
        tarifa_ponta=T,
        tarifa_fora_ponta=T,
        tolerancia=TOL,
        multiplicador=MULT,
        dc_minima_kw=DMIN,
    )
    assert r.ponta.dc_otima_kw == D("305")
    assert r.fora_ponta.dc_otima_kw == D("96")
    assert r.custo_anual_otimo == r.ponta.custo_anual_otimo + r.fora_ponta.custo_anual_otimo


def test_trace_presente() -> None:
    r = otimizar_posto(DM, T, TOL, MULT, DMIN)
    assert r.trace.passos


def test_rejeita_serie_vazia_e_valores_negativos() -> None:
    with pytest.raises(ValueError):
        otimizar_posto([], T, TOL, MULT, DMIN)
    with pytest.raises(ValueError):
        otimizar_posto([D("-1")], T, TOL, MULT, DMIN)
