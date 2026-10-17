from __future__ import annotations

import base64
import json
from time import perf_counter
from typing import Any, TypeVar

import httpx
from app.integrations.llm.base import (
    LLMPermanentError,
    LLMResult,
    LLMTransientError,
    LLMUsage,
)
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class OpenAICompatProvider:
    """Adaptador para APIs compatíveis com Chat Completions (OpenAI e equivalentes).

    Usa REST via httpx, sem SDK. O modelo e a URL base vêm sempre da configuração.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not base_url:
            raise ValueError("LLM_API_KEY e LLM_BASE_URL são obrigatórios para o adaptador real.")
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = client or httpx.Client()

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
        conteudo: list[dict[str, Any]] = []
        if texto:
            conteudo.append({"type": "text", "text": texto})
        for imagem in imagens or []:
            encoded = base64.b64encode(imagem).decode("ascii")
            conteudo.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
            )
        corpo = {
            "model": modelo,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": conteudo},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            },
        }
        inicio = perf_counter()
        try:
            resposta = self._client.post(
                self._url,
                json=corpo,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout_s,
            )
        except httpx.TimeoutException as error:
            raise LLMTransientError("Timeout na chamada ao provedor de LLM.") from error
        except httpx.TransportError as error:
            raise LLMTransientError("Falha de transporte na chamada ao provedor de LLM.") from error
        latencia_ms = int((perf_counter() - inicio) * 1000)

        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise LLMTransientError(f"Provedor de LLM indisponível (HTTP {resposta.status_code}).")
        if resposta.status_code >= 400:
            raise LLMPermanentError(
                f"Provedor de LLM recusou a chamada (HTTP {resposta.status_code})."
            )
        return self._interpretar(resposta, schema, modelo, latencia_ms)

    @staticmethod
    def _interpretar(
        resposta: httpx.Response, schema: type[T], modelo: str, latencia_ms: int
    ) -> LLMResult:
        try:
            dados = resposta.json()
            bruto = dados["choices"][0]["message"]["content"]
            parsed = schema.model_validate(json.loads(bruto)).model_dump(mode="json")
            uso = dados.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as error:
            raise LLMPermanentError("Resposta do provedor fora do schema esperado.") from error
        return LLMResult(
            parsed=parsed,
            usage=LLMUsage(
                tokens_entrada=int(uso.get("prompt_tokens", 0)),
                tokens_saida=int(uso.get("completion_tokens", 0)),
                latencia_ms=latencia_ms,
            ),
            modelo=modelo,
            bruto=bruto,
        )
