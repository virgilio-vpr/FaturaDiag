from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from app.domain.energia.tipos import (
    CENTAVO,
    Modalidade,
    Posto,
    Severidade,
    Subgrupo,
    arredondar,
    arredondar_moeda,
    dec,
)
from app.domain.energia.trace import VERSAO_MOTOR, PassoTrace, Trace


def test_arredondamento_half_up_em_duas_casas() -> None:
    assert arredondar_moeda(Decimal("2.345")) == Decimal("2.35")
    assert arredondar_moeda(Decimal("2.335")) == Decimal("2.34")
    assert arredondar_moeda(Decimal("-2.345")) == Decimal("-2.35")
    assert arredondar_moeda(Decimal("0.004")) == Decimal("0.00")
    assert CENTAVO == Decimal("0.01")


def test_arredondar_com_casas_arbitrarias() -> None:
    assert arredondar(Decimal("1.00005"), 4) == Decimal("1.0001")
    assert arredondar(Decimal("1.5"), 0) == Decimal("2")


def test_arredondar_rejeita_casas_negativas() -> None:
    with pytest.raises(ValueError):
        arredondar(Decimal("1"), -1)


def test_dec_converte_str_int_e_decimal_sem_float() -> None:
    assert dec("1.10") == Decimal("1.10")
    assert dec(3) == Decimal(3)
    assert dec(Decimal("2.5")) == Decimal("2.5")


def test_dec_rejeita_float_e_bool() -> None:
    with pytest.raises(TypeError):
        dec(0.1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        dec(True)  # type: ignore[arg-type]


def test_enums_alinhados_ao_banco_e_a_spec() -> None:
    assert {m.value for m in Modalidade} == {"AZUL", "VERDE", "CONVENCIONAL"}
    assert {s.value for s in Subgrupo} == {"A1", "A2", "A3", "A3a", "A4", "AS"}
    assert {p.value for p in Posto} == {"PONTA", "FORA_PONTA", "UNICO"}
    assert {s.value for s in Severidade} == {"INFO", "BAIXA", "MEDIA", "ALTA"}


def test_trace_e_imutavel_e_serializavel() -> None:
    passo = PassoTrace(
        nome="limite",
        formula="Dc x (1 + tolerancia)",
        insumos={"Dc": Decimal("500"), "tolerancia": Decimal("0.05")},
        resultado=Decimal("525.00"),
    )
    with pytest.raises(FrozenInstanceError):
        passo.nome = "outro"  # type: ignore[misc]

    trace = Trace().adicionar(passo)
    assert trace.passos == (passo,)
    assert Trace().passos == ()
    assert trace.versao_motor == VERSAO_MOTOR

    assert trace.para_dict() == {
        "versao_motor": VERSAO_MOTOR,
        "passos": [
            {
                "nome": "limite",
                "formula": "Dc x (1 + tolerancia)",
                "insumos": {"Dc": "500", "tolerancia": "0.05"},
                "resultado": "525.00",
            }
        ],
    }


def test_trace_concatena_sem_mutar() -> None:
    a = Trace().adicionar(PassoTrace("a", "f", {}, Decimal("1")))
    b = Trace().adicionar(PassoTrace("b", "g", {}, Decimal("2")))
    c = a.concatenar(b)
    assert [p.nome for p in c.passos] == ["a", "b"]
    assert [p.nome for p in a.passos] == ["a"]
