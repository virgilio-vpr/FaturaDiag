from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMTransientError(LLMError):
    """Falha temporária (429, 5xx, timeout): pode ser repetida."""


class LLMPermanentError(LLMError):
    """Falha que não deve ser repetida (4xx, resposta fora do schema)."""


class LLMOrcamentoExcedido(LLMError):
    pass


class LLMUsage(BaseModel):
    tokens_entrada: int
    tokens_saida: int
    latencia_ms: int
    custo_estimado: float | None = None


class LLMResult(BaseModel):
    parsed: dict[str, Any]
    usage: LLMUsage
    modelo: str
    bruto: str | None = None


class LLMProvider(Protocol):
    name: str

    def extract_structured(
        self,
        *,
        system: str,
        texto: str | None,
        imagens: list[bytes] | None,
        schema: type[T],
        modelo: str,
        timeout_s: int = 90,
    ) -> LLMResult: ...
