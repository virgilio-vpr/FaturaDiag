from __future__ import annotations

from decimal import Decimal

from app.core.settings import Settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.extrator import Alvo, CacheExtracao, ExtratorLLM, PrecoTokens
from app.integrations.llm.fake import FakeProvider
from app.integrations.llm.openai_adapter import OpenAICompatProvider


def criar_provider(nome: str, settings: Settings) -> LLMProvider:
    nome = nome.strip().casefold()
    if nome == "fake":
        return FakeProvider()
    if nome == "openai":
        return OpenAICompatProvider(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
        )
    raise ValueError(f"LLM_PROVIDER desconhecido: {nome!r}.")


def criar_extrator(settings: Settings, cache: CacheExtracao | None = None) -> ExtratorLLM:
    principal = Alvo(criar_provider(settings.llm_provider, settings), settings.llm_model)
    fallback = None
    if settings.llm_fallback_provider:
        fallback = Alvo(
            criar_provider(settings.llm_fallback_provider, settings), settings.llm_fallback_model
        )
    return ExtratorLLM(
        principal,
        fallback=fallback,
        cache=cache,
        preco=PrecoTokens(
            settings.llm_preco_entrada_brl_por_mtok, settings.llm_preco_saida_brl_por_mtok
        ),
        timeout_s=settings.llm_timeout_s,
    )


def orcamento_mensal(settings: Settings) -> Decimal:
    return settings.llm_monthly_budget_brl
