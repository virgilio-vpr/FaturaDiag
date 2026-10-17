from __future__ import annotations

from decimal import Decimal

from app.domain.energia.acl import CenarioPreco, EntradaACL, simular_acl
from app.domain.energia.demanda_otima import custo_anual, otimizar_posto
from app.domain.energia.indicadores import (
    custo_medio_rs_mwh,
    fator_de_carga,
    pct_consumo_ponta,
    utilizacao_demanda,
)
from app.domain.energia.reativos import IntervaloMedicao, apurar_reativos
from app.domain.energia.tipos import Posto, arredondar_moeda
from app.domain.energia.tributos import aplicar_tributos, fator_tributos
from app.domain.energia.ultrapassagem import apurar_posto
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

D = Decimal
config = settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

kw = st.decimals(min_value=0, max_value=5000, places=2, allow_nan=False, allow_infinity=False)
kw_pos = st.decimals(min_value=1, max_value=5000, places=2, allow_nan=False, allow_infinity=False)
tarifa = st.decimals(min_value=0, max_value=200, places=2, allow_nan=False, allow_infinity=False)
aliquota = st.decimals(min_value=0, max_value=D("0.5"), places=4, allow_nan=False)
tol = st.decimals(min_value=0, max_value=D("0.2"), places=2, allow_nan=False)
mult = st.decimals(min_value=1, max_value=3, places=1, allow_nan=False)


@config
@given(st.decimals(min_value=-(10**6), max_value=10**6, places=6, allow_nan=False))
def test_arredondamento_e_idempotente_e_limitado(v: Decimal) -> None:
    r = arredondar_moeda(v)
    assert arredondar_moeda(r) == r
    assert abs(r - v) <= D("0.005")


@config
@given(kw, kw, tarifa, tol, mult)
def test_ultrapassagem_nunca_negativa_e_respeita_limite(
    dc: Decimal, dm: Decimal, t: Decimal, tl: Decimal, m: Decimal
) -> None:
    p = apurar_posto(Posto.UNICO, dc, dm, t, tl, m)
    assert p.ultrapassagem_kw >= 0 and p.valor_ultrapassagem >= 0
    assert p.valor_total >= p.valor_demanda
    if dm <= dc * (1 + tl):
        assert p.ultrapassagem_kw == 0
    else:
        assert p.ultrapassagem_kw == dm - dc


@config
@given(kw, kw, kw, tarifa, tol, mult)
def test_ultrapassagem_monotona_em_dm(
    dc: Decimal, dm1: Decimal, dm2: Decimal, t: Decimal, tl: Decimal, m: Decimal
) -> None:
    lo, hi = sorted((dm1, dm2))
    a = apurar_posto(Posto.UNICO, dc, lo, t, tl, m)
    b = apurar_posto(Posto.UNICO, dc, hi, t, tl, m)
    assert b.valor_ultrapassagem >= a.valor_ultrapassagem


@config
@given(aliquota, aliquota, kw)
def test_tributos_por_dentro_nunca_reduzem_o_valor(pc: Decimal, icms: Decimal, v: Decimal) -> None:
    assert fator_tributos(pc, icms) >= 1
    r = aplicar_tributos(v, pc, icms)
    assert r.valor_com_tributos >= arredondar_moeda(v)


@config
@given(
    st.lists(kw_pos, min_size=1, max_size=12),
    kw_pos,
    tol,
    mult,
    st.decimals(min_value=30, max_value=60, places=0, allow_nan=False),
)
def test_demanda_otima_e_minimo_global_da_curva(
    dms: list[Decimal], t: Decimal, tl: Decimal, m: Decimal, dc_min: Decimal
) -> None:
    r = otimizar_posto(dms, t, tl, m, dc_min)
    assert r.dc_otima_kw >= dc_min
    bruto = custo_anual(r.dc_otima_kw, dms, t, tl, m)
    for ponto in r.curva:
        assert bruto <= custo_anual(ponto.dc_kw, dms, t, tl, m)
        if ponto.dc_kw < r.dc_otima_kw:
            assert bruto < custo_anual(ponto.dc_kw, dms, t, tl, m)  # desempate: menor Dc


@config
@given(
    st.lists(st.tuples(kw, kw, kw).map(lambda x: IntervaloMedicao(*x)), min_size=0, max_size=24),
    kw,
    tarifa,
    tarifa,
)
def test_reativos_nunca_negativos_e_sem_excecao(
    intervalos: list[IntervaloMedicao], paf: Decimal, vrere: Decimal, vrdre: Decimal
) -> None:
    r = apurar_reativos(intervalos, D("0.92"), vrere, paf, vrdre)
    assert r.ere_kwh >= 0 and r.dre_kw >= 0 and r.valor_total >= 0
    assert 0 <= r.intervalos_ignorados <= len(intervalos)


@config
@given(kw, kw, kw, kw)
def test_indicadores_nao_levantam_excecao_para_entradas_nao_negativas(
    a: Decimal, b: Decimal, c: Decimal, d: Decimal
) -> None:
    for r in (
        fator_de_carga(a, b, c),
        utilizacao_demanda(a, b),
        pct_consumo_ponta(a, b),
        custo_medio_rs_mwh(a, d),
    ):
        assert r.valor is None or r.valor >= 0


@config
@given(
    mwh=st.decimals(min_value=1, max_value=1000, places=1, allow_nan=False),
    te=st.decimals(min_value=0, max_value=800, places=2, allow_nan=False),
    enc=st.decimals(min_value=0, max_value=100, places=2, allow_nan=False),
    fixos=st.decimals(min_value=0, max_value=20000, places=2, allow_nan=False),
    p1=st.decimals(min_value=0, max_value=800, places=2, allow_nan=False),
    p2=st.decimals(min_value=0, max_value=800, places=2, allow_nan=False),
)
def test_acl_economia_decresce_com_preco_e_zera_no_break_even(
    mwh: Decimal, te: Decimal, enc: Decimal, fixos: Decimal, p1: Decimal, p2: Decimal, parametros
) -> None:  # type: ignore[no-untyped-def]
    e = EntradaACL(mwh, te, enc, fixos)
    lo, hi = sorted((p1, p2))
    r = simular_acl(e, [CenarioPreco("lo", lo), CenarioPreco("hi", hi)], parametros)
    assert r.cenarios[0].economia_mensal >= r.cenarios[1].economia_mensal
    be = simular_acl(e, [CenarioPreco("be", max(r.break_even_rs_mwh, D(0)))], parametros)
    if r.break_even_rs_mwh >= 0:
        assert abs(be.cenarios[0].economia_mensal) <= D("0.01") * 2 + mwh * D("1e-20")
