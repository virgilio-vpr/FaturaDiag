from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app.integrations.llm.schemas import FaturaExtraida
from app.scripts.eval_extraction import (
    RAIZ_FIXTURES,
    avaliar,
    carregar_casos,
    formatar,
    main,
    resposta_gravada,
    valores_iguais,
)


def test_fixtures_cobrem_distribuidoras_prioritarias_e_sao_sinteticas() -> None:
    casos = carregar_casos()
    assert {c.sigla for c in casos} == {"enel_sp", "edp_sp", "cpfl_paulista", "elektro"}
    for caso in casos:
        bruto = (RAIZ_FIXTURES / "faturas" / caso.sigla / f"{caso.nome}.json").read_text()
        assert "SINTÉTICA" in bruto
        assert "00.000.000/" in bruto


def test_resposta_gravada_respeita_o_schema() -> None:
    caso = carregar_casos()[0]
    modelo = FaturaExtraida.model_validate(resposta_gravada(caso.esperado, {}))
    assert modelo.valor_total.valor == Decimal(caso.esperado["valor_total"])
    assert modelo.demanda_contratada_ponta_kw.valor is None


@pytest.mark.parametrize(
    ("esperado", "obtido", "igual"),
    [
        ("500.00", Decimal("500.0"), True),
        (30, 30, True),
        (None, None, True),
        (None, "x", False),
        ("VERDE", "VERDE", True),
        ("VERDE", "AZUL", False),
        ("2026-03-01", "2026-03-01", True),
    ],
)
def test_comparacao_de_valores(esperado: object, obtido: object, igual: bool) -> None:
    assert valores_iguais(esperado, obtido) is igual


def test_avaliacao_mede_ganho_do_hint_e_nao_usa_rede() -> None:
    relatorio = avaliar(carregar_casos())
    assert relatorio.geral["com_hint"].taxa > relatorio.geral["sem_hint"].taxa
    assert relatorio.atinge_meta
    assert set(relatorio.por_hint) >= {"com_hint:enel_sp", "sem_hint:_generico"}
    saida = formatar(relatorio)
    assert "NÃO representam a acurácia real" in saida
    assert "Ganho do hint específico" in saida


def test_cli_sem_fixtures_retorna_erro(tmp_path: Path) -> None:
    assert main(["--fixtures", str(tmp_path)]) == 2


def test_cli_roda_com_fixtures_do_repositorio(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--exigir-meta"]) == 0
    assert "Por distribuidora" in capsys.readouterr().out
