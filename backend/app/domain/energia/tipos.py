from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

CENTAVO = Decimal("0.01")


class Modalidade(StrEnum):
    AZUL = "AZUL"
    VERDE = "VERDE"
    CONVENCIONAL = "CONVENCIONAL"


class Subgrupo(StrEnum):
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A3A = "A3a"
    A4 = "A4"
    AS = "AS"


class Posto(StrEnum):
    PONTA = "PONTA"
    FORA_PONTA = "FORA_PONTA"
    UNICO = "UNICO"


class Severidade(StrEnum):
    INFO = "INFO"
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


def dec(valor: str | int | Decimal) -> Decimal:
    """Converte para Decimal rejeitando float (e bool) para evitar erro binário."""
    if isinstance(valor, bool) or not isinstance(valor, (str, int, Decimal)):
        raise TypeError(
            f"Valor numérico inválido ({type(valor).__name__}); use str, int ou Decimal"
        )
    return valor if isinstance(valor, Decimal) else Decimal(valor)


def arredondar(valor: Decimal, casas: int) -> Decimal:
    if casas < 0:
        raise ValueError("casas deve ser >= 0")
    return valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)


def arredondar_moeda(valor: Decimal) -> Decimal:
    """Arredonda o valor final em 2 casas com ROUND_HALF_UP (§3.6)."""
    return arredondar(valor, 2)
