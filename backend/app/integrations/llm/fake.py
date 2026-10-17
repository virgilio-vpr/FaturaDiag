from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from app.integrations.llm.base import (
    LLMError,
    LLMPermanentError,
    LLMResult,
    LLMUsage,
)
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
Resposta = dict[str, Any] | LLMError


class FakeProvider:
    """Provedor determinístico para testes e avaliação offline; nunca usa rede."""

    name = "fake"

    def __init__(
        self,
        respostas: list[Resposta] | Callable[[str | None], Resposta] | None = None,
        *,
        tokens_entrada: int = 100,
        tokens_saida: int = 50,
    ) -> None:
        self._respostas = respostas
        self._indice = 0
        self._tokens = (tokens_entrada, tokens_saida)
        self.chamadas: list[dict[str, Any]] = []

    def extract_structured(
        self,
        *,
        system: str,
        texto: str | None,
        imagens: list[bytes] | None,
        schema: type[T],
        modelo: str,
        timeout_s: int = 90,
    ) -> LLMResult:
        self.chamadas.append(
            {"system": system, "texto": texto, "imagens": len(imagens or []), "modelo": modelo}
        )
        resposta = self._proxima(texto)
        if isinstance(resposta, LLMError):
            raise resposta
        try:
            parsed = schema.model_validate(resposta).model_dump(mode="json")
        except ValidationError as error:
            raise LLMPermanentError("Resposta gravada fora do schema.") from error
        return LLMResult(
            parsed=parsed,
            usage=LLMUsage(
                tokens_entrada=self._tokens[0], tokens_saida=self._tokens[1], latencia_ms=1
            ),
            modelo=modelo,
        )

    def _proxima(self, texto: str | None) -> Resposta:
        if callable(self._respostas):
            return self._respostas(texto)
        if not self._respostas:
            raise LLMPermanentError("FakeProvider sem respostas configuradas.")
        resposta = self._respostas[min(self._indice, len(self._respostas) - 1)]
        self._indice += 1
        return resposta
