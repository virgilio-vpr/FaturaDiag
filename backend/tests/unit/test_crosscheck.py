from __future__ import annotations

from decimal import Decimal

import pytest
from app.integrations.llm.extrator import Alvo, ExtratorLLM
from app.integrations.llm.fake import FakeProvider
from app.integrations.llm.schemas import FaturaExtraida
from app.modules.faturas import crosscheck
from app.modules.faturas.crosscheck import (
    checagem_cruzada,
    extrair_campos_criticos,
    parse_numero_br,
    rotulos_para,
)
from app.modules.faturas.extracao import executar_extracao
from app.modules.faturas.validacoes import Severidade
from tests.support.extracao import campo, fatura_extraida_dict
from tests.support.pdf import pdf_com_texto

TOL = Decimal("0.05")
TEXTO = """
Demanda Contratada 500,00 kW
Demanda Medida Fora Ponta 450,00 kW
Consumo Ponta 12.000,000 kWh
Consumo Fora Ponta 90.000,000 kWh
TOTAL A PAGAR R$ 1.000,00
"""


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("R$ 1.234,56", Decimal("1234.56")),
        ("500", Decimal("500")),
        ("12.000,000 kWh", Decimal("12000.000")),
        ("sem numero", None),
    ],
)
def test_parse_numero_br(texto: str, esperado: Decimal | None) -> None:
    assert parse_numero_br(texto) == esperado


def test_extrai_campos_criticos_do_texto_nativo() -> None:
    campos = extrair_campos_criticos(TEXTO, None)
    assert campos["valor_total"] == Decimal("1000.00")
    assert campos["consumo_ponta_kwh"] == Decimal("12000.000")
    assert campos["consumo_fora_ponta_kwh"] == Decimal("90000.000")
    assert campos["demanda_contratada_unica_kw"] == Decimal("500.00")
    assert campos["demanda_medida_fora_ponta_kw"] == Decimal("450.00")
    assert "demanda_contratada_ponta_kw" not in campos


def _extraida(**overrides: object) -> FaturaExtraida:
    return FaturaExtraida.model_validate(fatura_extraida_dict(**overrides))


def test_sem_divergencia_nao_gera_alerta() -> None:
    assert checagem_cruzada(TEXTO, _extraida(), sigla=None, tolerancia_total_rs=TOL) == []


def test_divergencia_gera_aviso_por_campo() -> None:
    extraida = _extraida(valor_total=campo("1200.00"), consumo_ponta_kwh=campo("13000.000"))
    alertas = checagem_cruzada(TEXTO, extraida, sigla=None, tolerancia_total_rs=TOL)
    assert {a.campo for a in alertas} == {"valor_total", "consumo_ponta_kwh"}
    assert all(a.codigo == "CROSSCHECK_DIVERGE" for a in alertas)
    assert all(a.severidade is Severidade.AVISO for a in alertas)


def test_total_respeita_tolerancia_e_campo_nulo_e_ignorado() -> None:
    dentro = _extraida(valor_total=campo("1000.04"))
    assert checagem_cruzada(TEXTO, dentro, sigla=None, tolerancia_total_rs=TOL) == []
    nulo = _extraida(valor_total=campo(None, 0.0))
    assert checagem_cruzada(TEXTO, nulo, sigla=None, tolerancia_total_rs=TOL) == []


def test_rotulos_especificos_tem_precedencia_sobre_os_genericos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        crosscheck.ROTULOS_POR_DISTRIBUIDORA,
        "enel_sp",
        {"valor_total": (r"importe\s+final",)},
    )
    assert rotulos_para("ENEL_SP")["valor_total"][0] == r"importe\s+final"
    assert rotulos_para("EDP_ES")["valor_total"][0] != r"importe\s+final"
    texto = "TOTAL A PAGAR 10,00\nImporte final 1.000,00"
    assert extrair_campos_criticos(texto, "ENEL_SP")["valor_total"] == Decimal("1000.00")
    assert extrair_campos_criticos(texto, "EDP_ES")["valor_total"] == Decimal("10.00")


def test_pipeline_nativo_inclui_alerta_de_crosscheck() -> None:
    linhas = ["ENEL DISTRIBUICAO SAO PAULO FATURA", "TOTAL A PAGAR R$ 1.500,00"] * 8
    provider = FakeProvider([fatura_extraida_dict()])
    resultado = executar_extracao(
        ExtratorLLM(Alvo(provider, "modelo-teste")),
        conteudo=pdf_com_texto([linhas]),
        mime="application/pdf",
        sha256="cc1",
        tolerancia_divergencia_rs=TOL,
        uc_codigo="12345678",
    )
    assert [a.codigo for a in resultado.alertas if a.campo == "valor_total"] == [
        "CROSSCHECK_DIVERGE"
    ]
