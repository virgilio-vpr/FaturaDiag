from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypeVar

import structlog
from app.integrations.llm.base import (
    LLMError,
    LLMOrcamentoExcedido,
    LLMProvider,
    LLMResult,
    LLMTransientError,
)
from pydantic import BaseModel
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

T = TypeVar("T", bound=BaseModel)
logger = structlog.get_logger(__name__)
CacheKey = tuple[str, str, str, str]
UM_MILHAO = Decimal(1_000_000)


class CacheExtracao(Protocol):
    def get(self, chave: CacheKey) -> LLMResult | None: ...

    def put(self, chave: CacheKey, resultado: LLMResult) -> None: ...


class CacheEmMemoria:
    def __init__(self) -> None:
        self._dados: dict[CacheKey, LLMResult] = {}

    def get(self, chave: CacheKey) -> LLMResult | None:
        return self._dados.get(chave)

    def put(self, chave: CacheKey, resultado: LLMResult) -> None:
        self._dados[chave] = resultado


@dataclass(frozen=True)
class Alvo:
    provider: LLMProvider
    modelo: str


@dataclass(frozen=True)
class PrecoTokens:
    entrada_brl_por_mtok: Decimal = Decimal(0)
    saida_brl_por_mtok: Decimal = Decimal(0)

    def custo(self, tokens_entrada: int, tokens_saida: int) -> float | None:
        if not self.entrada_brl_por_mtok and not self.saida_brl_por_mtok:
            return None
        total = (
            Decimal(tokens_entrada) * self.entrada_brl_por_mtok
            + Decimal(tokens_saida) * self.saida_brl_por_mtok
        ) / UM_MILHAO
        return float(total)


@dataclass(frozen=True)
class ResultadoExtracao:
    resultado: LLMResult
    provider: str
    cache_hit: bool
    usou_fallback: bool


class ExtratorLLM:
    def __init__(
        self,
        principal: Alvo,
        *,
        fallback: Alvo | None = None,
        cache: CacheExtracao | None = None,
        preco: PrecoTokens | None = None,
        timeout_s: int = 90,
        tentativas: int = 3,
        espera: wait_base | None = None,
    ) -> None:
        self._principal = principal
        self._fallback = fallback
        self._cache = cache
        self._preco = preco or PrecoTokens()
        self._timeout_s = timeout_s
        self._tentativas = tentativas
        self._espera = espera or wait_exponential(multiplier=1, min=1, max=20)

    def extrair(
        self,
        *,
        sha256: str,
        prompt_versao: str,
        hint_usado: str,
        system: str,
        texto: str | None,
        imagens: list[bytes] | None,
        schema: type[T],
        gasto_mensal_brl: Decimal = Decimal(0),
        orcamento_mensal_brl: Decimal = Decimal(0),
    ) -> ResultadoExtracao:
        chave = (sha256, prompt_versao, hint_usado, self._principal.modelo)
        if self._cache is not None and (guardado := self._cache.get(chave)) is not None:
            return ResultadoExtracao(guardado, self._principal.provider.name, True, False)

        if orcamento_mensal_brl > 0 and gasto_mensal_brl >= orcamento_mensal_brl:
            raise LLMOrcamentoExcedido("Orçamento mensal de LLM da organização esgotado.")

        usou_fallback = False
        alvo = self._principal
        try:
            resultado = self._chamar(alvo, system, texto, imagens, schema)
        except LLMError as erro:
            if self._fallback is None:
                raise
            logger.warning("llm_fallback", provider=alvo.provider.name, motivo=type(erro).__name__)
            alvo = self._fallback
            usou_fallback = True
            resultado = self._chamar(alvo, system, texto, imagens, schema)

        resultado.usage.custo_estimado = self._preco.custo(
            resultado.usage.tokens_entrada, resultado.usage.tokens_saida
        )
        if self._cache is not None:
            self._cache.put(chave, resultado)
        return ResultadoExtracao(resultado, alvo.provider.name, False, usou_fallback)

    def _chamar(
        self,
        alvo: Alvo,
        system: str,
        texto: str | None,
        imagens: list[bytes] | None,
        schema: type[T],
    ) -> LLMResult:
        retrying = Retrying(
            retry=retry_if_exception_type(LLMTransientError),
            stop=stop_after_attempt(self._tentativas),
            wait=self._espera,
            reraise=True,
        )
        return retrying(
            alvo.provider.extract_structured,
            system=system,
            texto=texto,
            imagens=imagens,
            schema=schema,
            modelo=alvo.modelo,
            timeout_s=self._timeout_s,
        )
