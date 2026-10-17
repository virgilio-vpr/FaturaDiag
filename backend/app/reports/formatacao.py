"""Formatação pt-BR do relatório (§12.2): `R$ 1.234,56`, `12,5 %`, `dd/mm/aaaa`."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from babel.numbers import format_decimal

LOCALE = "pt_BR"
NAO_DISPONIVEL = "—"


def _dec(valor: object) -> Decimal | None:
    if valor is None or valor == "":
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def numero(valor: object, casas: int = 0) -> str:
    dec = _dec(valor)
    if dec is None:
        return NAO_DISPONIVEL
    padrao = "#,##0" + ("." + "0" * casas if casas else "")
    return format_decimal(dec, format=padrao, locale=LOCALE)


def moeda(valor: object) -> str:
    dec = _dec(valor)
    if dec is None:
        return NAO_DISPONIVEL
    sinal = "-" if dec < 0 else ""
    return f"{sinal}R$ {numero(abs(dec), 2)}"


def percentual(fracao: object, casas: int = 1) -> str:
    """Recebe fração (0–1), conforme a convenção do projeto (§7)."""
    dec = _dec(fracao)
    if dec is None:
        return NAO_DISPONIVEL
    return f"{numero(dec * 100, casas)} %"


def data(valor: object) -> str:
    if valor is None:
        return NAO_DISPONIVEL
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")


def referencia(valor: object) -> str:
    """`2026-03` ou `2026-03-01` → `03/2026`."""
    if valor is None:
        return NAO_DISPONIVEL
    texto = str(valor)
    return f"{texto[5:7]}/{texto[:4]}"
