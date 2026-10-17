from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

VERSAO_MOTOR = "0.1.0"

Valor = Decimal | int | str | bool | None


def _texto(valor: Valor) -> str | bool | None:
    if valor is None or isinstance(valor, bool):
        return valor
    return str(valor)


@dataclass(frozen=True, slots=True)
class PassoTrace:
    nome: str
    formula: str
    insumos: Mapping[str, Valor]
    resultado: Valor

    def para_dict(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "formula": self.formula,
            "insumos": {k: _texto(v) for k, v in self.insumos.items()},
            "resultado": _texto(self.resultado),
        }


@dataclass(frozen=True, slots=True)
class Trace:
    passos: tuple[PassoTrace, ...] = ()
    versao_motor: str = field(default=VERSAO_MOTOR)

    def adicionar(self, passo: PassoTrace) -> Trace:
        return Trace(self.passos + (passo,), self.versao_motor)

    def concatenar(self, outro: Trace) -> Trace:
        return Trace(self.passos + outro.passos, self.versao_motor)

    def para_dict(self) -> dict[str, Any]:
        return {
            "versao_motor": self.versao_motor,
            "passos": [p.para_dict() for p in self.passos],
        }
