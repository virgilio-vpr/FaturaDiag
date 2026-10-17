from __future__ import annotations

from decimal import Decimal

import pytest
from app.domain.energia.tributos import aplicar_tributos, fator_tributos

D = Decimal


def test_g05_fator_e_valor_com_tributos() -> None:
    assert fator_tributos(D("0.0565"), D("0.18")).quantize(D("0.000001")) == D("1.292541")
    r = aplicar_tributos(D("1000.00"), pis_cofins=D("0.0565"), icms=D("0.18"))
    assert r.valor_com_tributos == D("1292.54")
    assert r.valor_sem_tributos == D("1000.00")
    assert r.valor_tributos == D("292.54")


def test_tributos_por_dentro_difere_da_soma_de_aliquotas() -> None:
    soma = 1 + D("0.0565") + D("0.18")
    assert fator_tributos(D("0.0565"), D("0.18")) != soma


def test_sem_tributos_fator_um() -> None:
    assert fator_tributos(D("0"), D("0")) == D("1")


def test_override_de_fator_por_distribuidora() -> None:
    r = aplicar_tributos(D("100"), D("0.0565"), D("0.18"), fator_override=D("1.30"))
    assert r.fator == D("1.30")
    assert r.valor_com_tributos == D("130.00")
    assert "override" in r.trace.passos[0].nome


@pytest.mark.parametrize(("pc", "icms"), [("-0.1", "0.1"), ("0.1", "1"), ("1", "0.1")])
def test_rejeita_aliquotas_invalidas(pc: str, icms: str) -> None:
    with pytest.raises(ValueError):
        fator_tributos(D(pc), D(icms))


def test_rejeita_override_nao_positivo_e_valor_negativo() -> None:
    with pytest.raises(ValueError):
        aplicar_tributos(D("100"), D("0"), D("0"), fator_override=D("0"))
    with pytest.raises(ValueError):
        aplicar_tributos(D("-1"), D("0"), D("0"))
