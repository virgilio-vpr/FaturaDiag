from __future__ import annotations

import pytest
from app.integrations.llm.hints import HINTS_DIR, carregar_hint_arquivo
from app.scripts.seed_catalogs import PRIORITY_DISTRIBUTORS

PRIORITARIAS = [
    "ENEL_SP",
    "ENEL_RJ",
    "EDP_SP",
    "EDP_ES",
    "CPFL_PAULISTA",
    "CPFL_PIRATININGA",
    "ELEKTRO",
]


@pytest.mark.parametrize("sigla", PRIORITARIAS)
def test_hint_especifico_existe_e_segue_estrutura(sigla: str) -> None:
    hint = carregar_hint_arquivo(sigla)
    assert hint.especifico
    assert hint.nome == sigla.lower()
    linhas = hint.conteudo.splitlines()
    assert linhas[0] == f"# Hint: {sigla.lower()}"
    for secao in ("## Particularidades do layout", "## Nomenclatura específica", "## Cuidados"):
        assert secao in linhas


def test_generico_e_usado_quando_nao_ha_hint() -> None:
    hint = carregar_hint_arquivo("DISTRIBUIDORA_DESCONHECIDA")
    assert not hint.especifico
    assert hint.nome == "_generico"
    assert carregar_hint_arquivo(None).nome == "_generico"


def test_sigla_maliciosa_nao_sai_do_diretorio() -> None:
    assert carregar_hint_arquivo("../../etc/passwd").nome == "_generico"
    assert carregar_hint_arquivo("_generico").especifico is False


def test_toda_distribuidora_prioritaria_do_seed_tem_hint() -> None:
    siglas_seed = {d.sigla for d in PRIORITY_DISTRIBUTORS}
    for sigla in PRIORITARIAS:
        assert sigla in siglas_seed


def test_hints_particularidades_documentadas() -> None:
    assert "GRANDEZAS MEDIDAS" in carregar_hint_arquivo("ENEL_SP").conteudo
    assert "18h às 21h" in carregar_hint_arquivo("ENEL_SP").conteudo
    assert "17h30 às 20h30" in carregar_hint_arquivo("EDP_SP").conteudo
    assert "CCI" in carregar_hint_arquivo("ELEKTRO").conteudo
    assert sorted(p.stem for p in HINTS_DIR.glob("*.md")) == sorted(
        [s.lower() for s in PRIORITARIAS] + ["_generico"]
    )
