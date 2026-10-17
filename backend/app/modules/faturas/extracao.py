from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.integrations.llm.base import LLMResult
from app.integrations.llm.extrator import ExtratorLLM
from app.integrations.llm.extrator import ResultadoExtracao as RetornoLLM
from app.integrations.llm.hints import HINT_GENERICO, carregar_hint_arquivo
from app.integrations.llm.montagem import (
    PROMPT_VERSAO,
    detectar_distribuidora,
    minimizar_texto,
    montar_system_prompt,
)
from app.integrations.llm.schemas import FaturaExtraida
from app.integrations.pdf import (
    OrigemDocumento,
    classificar_origem,
    extrair_texto_pdf,
    rasterizar_pdf,
)
from app.modules.faturas.crosscheck import checagem_cruzada
from app.modules.faturas.validacoes import Alerta, ContextoValidacao, validar_extracao

CONFIANCA_DISTRIBUIDORA = 0.80


@dataclass(frozen=True)
class HintResolvido:
    nome: str
    conteudo: str
    especifico: bool


HintResolver = Callable[[str | None], HintResolvido]


def resolver_hint_arquivo(sigla: str | None) -> HintResolvido:
    hint = carregar_hint_arquivo(sigla)
    return HintResolvido(hint.nome, hint.conteudo, hint.especifico)


@dataclass(frozen=True)
class ResultadoExtracao:
    extraida: FaturaExtraida
    resultado: LLMResult
    provider: str
    origem: OrigemDocumento
    metodo: str
    hint_usado: str
    distribuidora_sigla: str | None
    alertas: list[Alerta]
    cache_hit: bool
    usou_fallback: bool
    texto_nativo: str | None


def executar_extracao(
    extrator: ExtratorLLM,
    *,
    conteudo: bytes,
    mime: str,
    sha256: str,
    tolerancia_divergencia_rs: Decimal,
    uc_codigo: str | None = None,
    fatura_duplicada: bool = False,
    resolver_hint: HintResolver = resolver_hint_arquivo,
    gasto_mensal_brl: Decimal = Decimal(0),
    orcamento_mensal_brl: Decimal = Decimal(0),
) -> ResultadoExtracao:
    """Etapas E2–E5 do pipeline: origem, hint, extração via LLM e validação determinística."""
    leitura = extrair_texto_pdf(conteudo) if mime == "application/pdf" else None
    origem = classificar_origem(mime, leitura)
    texto: str | None = None
    imagens: list[bytes] | None = None
    if origem is OrigemDocumento.PDF_NATIVO and leitura is not None:
        texto = minimizar_texto(leitura.texto)
    elif origem is OrigemDocumento.PDF_ESCANEADO:
        imagens = rasterizar_pdf(conteudo)
    else:
        imagens = [conteudo]
    metodo = "TEXTO_NATIVO" if texto is not None else "VISAO"

    sigla = detectar_distribuidora(leitura.texto) if leitura is not None else None
    hint = resolver_hint(sigla)

    def chamar(hint_atual: HintResolvido) -> tuple[FaturaExtraida, RetornoLLM]:
        retorno = extrator.extrair(
            sha256=sha256,
            prompt_versao=PROMPT_VERSAO,
            hint_usado=hint_atual.nome,
            system=montar_system_prompt(hint_atual.conteudo),
            texto=texto,
            imagens=imagens,
            schema=FaturaExtraida,
            gasto_mensal_brl=gasto_mensal_brl,
            orcamento_mensal_brl=orcamento_mensal_brl,
        )
        return FaturaExtraida.model_validate(retorno.resultado.parsed), retorno

    extraida, retorno = chamar(hint)

    # Imagens: o LLM identifica a distribuidora; se houver hint específico, reexecuta com ele.
    if sigla is None and extraida.distribuidora.confianca >= CONFIANCA_DISTRIBUIDORA:
        identificada = detectar_distribuidora(extraida.distribuidora.valor or "")
        if identificada is not None:
            sigla = identificada
            novo_hint = resolver_hint(sigla)
            if novo_hint.nome != hint.nome:
                hint = novo_hint
                extraida, retorno = chamar(hint)

    contexto = ContextoValidacao(
        tolerancia_divergencia_rs=tolerancia_divergencia_rs,
        uc_codigo=uc_codigo,
        distribuidora_sigla=sigla,
        hint_especifico=hint.especifico and hint.nome != HINT_GENERICO,
        fatura_duplicada=fatura_duplicada,
    )
    alertas = validar_extracao(extraida, contexto)
    if origem is OrigemDocumento.PDF_NATIVO and leitura is not None:
        alertas += checagem_cruzada(
            leitura.texto,
            extraida,
            sigla=sigla,
            tolerancia_total_rs=tolerancia_divergencia_rs,
        )
    return ResultadoExtracao(
        extraida=extraida,
        resultado=retorno.resultado,
        provider=retorno.provider,
        origem=origem,
        metodo=metodo,
        hint_usado=hint.nome,
        distribuidora_sigla=sigla,
        alertas=alertas,
        cache_hit=retorno.cache_hit,
        usou_fallback=retorno.usou_fallback,
        texto_nativo=texto,
    )
