from __future__ import annotations

import ast
import re
from pathlib import Path

DOMINIO = Path(__file__).resolve().parents[2] / "app" / "domain"
NOMES_DE_PRECO = re.compile(r"tarifa|tusd|preco|vrere|vrdre|te_cativa", re.IGNORECASE)
LITERAIS_NEUTROS = {0, 1}


def _arquivos() -> list[Path]:
    return sorted(DOMINIO.rglob("*.py"))


def violacoes_float(codigo: str) -> list[str]:
    achados: list[str] = []
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "float":
            achados.append(f"float() na linha {no.lineno}")
        if isinstance(no, ast.Constant) and isinstance(no.value, float):
            achados.append(f"literal float na linha {no.lineno}")
    return achados


def _numero(no: ast.AST | None) -> bool:
    """True para literal numérico (ou Decimal("...")/Decimal(n)) diferente de 0 e 1."""
    if no is None:
        return False
    if isinstance(no, ast.Constant) and isinstance(no.value, (int, str)):
        try:
            return float(no.value) not in LITERAIS_NEUTROS
        except ValueError:
            return False
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "Decimal":
        return bool(no.args) and _numero(no.args[0])
    return False


def violacoes_tarifa_literal(codigo: str) -> list[str]:
    achados: list[str] = []
    for no in ast.walk(ast.parse(codigo)):
        pares: list[tuple[str, ast.AST | None]] = []
        if isinstance(no, ast.Assign):
            pares = [(t.id, no.value) for t in no.targets if isinstance(t, ast.Name)]
        elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
            pares = [(no.target.id, no.value)]
        elif isinstance(no, ast.keyword) and no.arg:
            pares = [(no.arg, no.value)]
        elif isinstance(no, ast.arguments):
            for arg, default in zip(reversed(no.args), reversed(no.defaults), strict=False):
                pares.append((arg.arg, default))
            for arg, kw_default in zip(no.kwonlyargs, no.kw_defaults, strict=True):
                pares.append((arg.arg, kw_default))
        for nome, valor in pares:
            if NOMES_DE_PRECO.search(nome) and _numero(valor):
                achados.append(f"valor literal em '{nome}'")
    return achados


def test_dominio_existe() -> None:
    assert len(_arquivos()) >= 10


def test_dominio_nao_usa_float() -> None:
    problemas = {
        str(a.relative_to(DOMINIO)): v
        for a in _arquivos()
        if (v := violacoes_float(a.read_text(encoding="utf-8")))
    }
    assert not problemas, problemas


def test_dominio_nao_embute_tarifas_literais() -> None:
    problemas = {
        str(a.relative_to(DOMINIO)): v
        for a in _arquivos()
        if (v := violacoes_tarifa_literal(a.read_text(encoding="utf-8")))
    }
    assert not problemas, problemas


def test_guarda_detecta_float() -> None:
    assert violacoes_float("x = float('1.5')")
    assert violacoes_float("x = 1.5")
    assert not violacoes_float("x = Decimal('1.5')")


def test_guarda_detecta_tarifa_literal() -> None:
    assert violacoes_tarifa_literal("tarifa_demanda = Decimal('30.25')")
    assert violacoes_tarifa_literal("def f(preco_rs_mwh=Decimal('260')): ...")
    assert violacoes_tarifa_literal("f(tusd=12)")
    assert not violacoes_tarifa_literal("tarifa = Decimal(0)")
    assert not violacoes_tarifa_literal("tarifa = parametros.valor")
