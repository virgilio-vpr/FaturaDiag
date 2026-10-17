from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

JsonValor = str | int | bool | None | list[Any] | dict[str, Any]


def para_json(valor: object) -> JsonValor:
    """Converte dataclasses do motor em JSON sem perda: Decimal e datas viram texto (P3, P6)."""
    if isinstance(valor, Enum):
        return str(valor.value)
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if is_dataclass(valor) and not isinstance(valor, type):
        return {f.name: para_json(getattr(valor, f.name)) for f in fields(valor)}
    if isinstance(valor, Mapping):
        return {str(k): para_json(v) for k, v in valor.items()}
    if isinstance(valor, (tuple, list)):
        return [para_json(v) for v in valor]
    raise TypeError(f"Tipo não serializável no snapshot: {type(valor).__name__}")


def de_json[T](tipo: type[T], dados: object) -> T:
    """Reconstrói uma dataclass do motor a partir do JSON gerado por `para_json`."""
    return cast(T, _converter(tipo, dados))


def _converter(tipo: Any, dados: object) -> Any:
    origem = get_origin(tipo)
    if origem in (Union, types.UnionType):
        if dados is None:
            return None
        alvo = next(a for a in get_args(tipo) if a is not type(None))
        return _converter(alvo, dados)
    if origem is tuple:
        return tuple(_converter(get_args(tipo)[0], item) for item in cast(list[Any], dados))
    if origem is dict:
        return {k: _converter(get_args(tipo)[1], v) for k, v in cast(dict[str, Any], dados).items()}
    if dados is None:
        return None
    if tipo is Decimal:
        return Decimal(cast(str, dados))
    if tipo is date:
        return date.fromisoformat(cast(str, dados))
    if isinstance(tipo, type) and issubclass(tipo, Enum):
        return tipo(dados)
    if is_dataclass(tipo):
        dicas = get_type_hints(tipo)
        brutos = cast(dict[str, Any], dados)
        return cast(Any, tipo)(
            **{f.name: _converter(dicas[f.name], brutos[f.name]) for f in fields(tipo)}
        )
    return dados
