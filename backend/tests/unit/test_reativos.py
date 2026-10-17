from __future__ import annotations

from decimal import Decimal

import pytest
from app.domain.energia.reativos import (
    IntervaloMedicao,
    Precisao,
    apurar_reativos,
    apurar_reativos_aproximado,
    fator_potencia,
)

D = Decimal
FR = D("0.92")


def test_fator_potencia_horario() -> None:
    assert fator_potencia(D("100"), D("75")) == D("0.8")


def test_fator_potencia_com_eeam_zero_e_indefinido() -> None:
    assert fator_potencia(D("0"), D("10")) is None
    assert fator_potencia(D("0"), D("0")) is None


def test_g03a_ere_horaria() -> None:
    r = apurar_reativos(
        [IntervaloMedicao(D("100"), D("75"), D("0"))],
        fr=FR,
        vrere=D("0.50"),
        paf_kw=D("0"),
        vrdre=D("0"),
    )
    assert r.ere_kwh == D("15")
    assert r.valor_ere == D("7.50")
    assert r.precisao is Precisao.HORARIA


def test_g03b_dre_horaria() -> None:
    r = apurar_reativos(
        [IntervaloMedicao(D("100"), D("75"), D("280"))],
        fr=FR,
        vrere=D("0"),
        paf_kw=D("300"),
        vrdre=D("30"),
    )
    assert r.dre_kw == D("22")
    assert r.valor_dre == D("660.00")
    assert r.valor_total == D("660.00")


@pytest.mark.parametrize("ereat", ["0", "40"])
def test_g03c_fp_igual_ou_acima_da_referencia(ereat: str) -> None:
    # EEAM=100: ereat=0 -> fT=1; ereat=40 -> fT~0,928
    r = apurar_reativos(
        [IntervaloMedicao(D("100"), D(ereat), D("300"))],
        fr=FR,
        vrere=D("0.50"),
        paf_kw=D("300"),
        vrdre=D("30"),
    )
    assert r.ere_kwh == D("0")
    assert r.dre_kw == D("0")
    assert r.valor_total == D("0.00")


def test_g07_eeam_zero_e_ignorado_sem_excecao() -> None:
    r = apurar_reativos(
        [
            IntervaloMedicao(D("0"), D("50"), D("0")),
            IntervaloMedicao(D("100"), D("75"), D("0")),
        ],
        fr=FR,
        vrere=D("0.50"),
        paf_kw=D("0"),
        vrdre=D("0"),
    )
    assert r.intervalos_ignorados == 1
    assert r.ere_kwh == D("15")


def test_soma_ere_de_varios_intervalos_e_maior_dre() -> None:
    r = apurar_reativos(
        [
            IntervaloMedicao(D("100"), D("75"), D("280")),
            IntervaloMedicao(D("100"), D("75"), D("250")),
        ],
        fr=FR,
        vrere=D("0.50"),
        paf_kw=D("300"),
        vrdre=D("30"),
    )
    assert r.ere_kwh == D("30")
    assert r.valor_ere == D("15.00")
    assert r.dre_kw == D("22")


def test_sem_intervalos_retorna_zero() -> None:
    r = apurar_reativos([], fr=FR, vrere=D("0.5"), paf_kw=D("0"), vrdre=D("1"))
    assert r.valor_total == D("0.00")
    assert r.intervalos_ignorados == 0


def test_trace_registra_formula_por_intervalo() -> None:
    r = apurar_reativos(
        [IntervaloMedicao(D("100"), D("75"), D("280"))],
        fr=FR,
        vrere=D("0.50"),
        paf_kw=D("300"),
        vrdre=D("30"),
    )
    nomes = [p.nome for p in r.trace.passos]
    assert "ere_intervalo_1" in nomes
    assert "valor_dre" in nomes


def test_modo_aproximado_e_marcado_como_triagem() -> None:
    r = apurar_reativos_aproximado(eeam_kwh=D("100"), ereat_kvarh=D("75"), fr=FR, vrere=D("0.50"))
    assert r.precisao is Precisao.APROXIMADA
    assert r.ere_kwh == D("15")
    assert r.valor_ere == D("7.50")
    assert r.dre_kw == D("0")


def test_rejeita_entradas_negativas() -> None:
    with pytest.raises(ValueError):
        apurar_reativos(
            [IntervaloMedicao(D("-1"), D("0"), D("0"))],
            fr=FR,
            vrere=D("0"),
            paf_kw=D("0"),
            vrdre=D("0"),
        )
