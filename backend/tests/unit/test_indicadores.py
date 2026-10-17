from __future__ import annotations

from decimal import Decimal

import pytest
from app.domain.energia.indicadores import (
    custo_medio_rs_mwh,
    fator_de_carga,
    pct_consumo_ponta,
    utilizacao_demanda,
)

D = Decimal


def test_fator_de_carga() -> None:
    # 144.000 kWh / (400 kW x 720 h) = 0,5
    assert fator_de_carga(D("144000"), D("400"), D("720")).valor == D("0.5")


def test_utilizacao_de_demanda() -> None:
    assert utilizacao_demanda(D("270"), D("300")).valor == D("0.9")


def test_pct_consumo_ponta() -> None:
    assert pct_consumo_ponta(D("100"), D("900")).valor == D("0.1")


def test_custo_medio_em_rs_por_mwh() -> None:
    # R$ 50.000 / (100.000 kWh / 1000) = 500
    assert custo_medio_rs_mwh(D("50000"), D("100000")).valor == D("500")


@pytest.mark.parametrize(
    "chamada",
    [
        lambda: fator_de_carga(D("1"), D("0"), D("720")),
        lambda: fator_de_carga(D("1"), D("10"), D("0")),
        lambda: utilizacao_demanda(D("1"), D("0")),
        lambda: pct_consumo_ponta(D("0"), D("0")),
        lambda: custo_medio_rs_mwh(D("1"), D("0")),
    ],
)
def test_denominador_zero_retorna_indefinido_sem_excecao(chamada) -> None:  # type: ignore[no-untyped-def]
    r = chamada()
    assert r.valor is None
    assert r.trace.passos


def test_entradas_negativas_sao_rejeitadas() -> None:
    with pytest.raises(ValueError):
        fator_de_carga(D("-1"), D("10"), D("720"))
