from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from app.integrations.llm.schemas import FaturaExtraida
from app.modules.faturas.validacoes import Alerta, Severidade

# Rótulos (regex, sem distinção de caixa) que antecedem o valor na mesma linha do texto nativo.
RotulosPorCampo = Mapping[str, tuple[str, ...]]

ROTULOS_GENERICOS: RotulosPorCampo = {
    "valor_total": (r"total\s+a\s+pagar", r"valor\s+total\s+da\s+fatura", r"total\s+da\s+fatura"),
    "consumo_ponta_kwh": (r"consumo\s+(?:na\s+)?ponta", r"energia\s+ativa\s+ponta"),
    "consumo_fora_ponta_kwh": (
        r"consumo\s+(?:fora\s+(?:de\s+)?ponta|fora\s+ponta)",
        r"energia\s+ativa\s+fora\s+ponta",
    ),
    "demanda_contratada_unica_kw": (r"demanda\s+contratada(?!\s+(?:ponta|fora))",),
    "demanda_contratada_ponta_kw": (r"demanda\s+contratada\s+ponta",),
    "demanda_contratada_fora_ponta_kw": (r"demanda\s+contratada\s+fora\s+(?:de\s+)?ponta",),
    "demanda_medida_ponta_kw": (r"demanda\s+medida\s+ponta",),
    "demanda_medida_fora_ponta_kw": (r"demanda\s+medida\s+fora\s+(?:de\s+)?ponta",),
}

# Rótulos próprios de cada distribuidora (chave = sigla em minúsculas); têm precedência sobre
# os genéricos. Calibrar com amostras reais anonimizadas (D-11).
ROTULOS_POR_DISTRIBUIDORA: dict[str, RotulosPorCampo] = {}

TOLERANCIA_GRANDEZA = Decimal("0.01")
_NUMERO = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?![\d,])")


def parse_numero_br(texto: str) -> Decimal | None:
    """'1.234,56' → Decimal('1234.56'); devolve o primeiro número do trecho."""
    achado = _NUMERO.search(texto)
    if achado is None:
        return None
    inteiro = achado.group(1).replace(".", "")
    fracao = achado.group(2) or "0"
    try:
        return Decimal(f"{inteiro}.{fracao}")
    except InvalidOperation:
        return None


def rotulos_para(sigla: str | None) -> RotulosPorCampo:
    especificos = ROTULOS_POR_DISTRIBUIDORA.get(sigla.casefold(), {}) if sigla else {}
    return {
        campo: (*especificos.get(campo, ()), *padroes)
        for campo, padroes in ROTULOS_GENERICOS.items()
    }


def _valor_na_linha(texto: str, padroes: tuple[str, ...]) -> Decimal | None:
    for padrao in padroes:
        regex = re.compile(padrao, re.IGNORECASE)
        for linha in texto.splitlines():
            achado = regex.search(linha)
            if achado is None:
                continue
            valor = parse_numero_br(linha[achado.end() :])
            if valor is not None:
                return valor
    return None


def extrair_campos_criticos(texto: str, sigla: str | None) -> dict[str, Decimal]:
    campos: dict[str, Decimal] = {}
    for campo, padroes in rotulos_para(sigla).items():
        valor = _valor_na_linha(texto, padroes)
        if valor is not None:
            campos[campo] = valor
    return campos


def checagem_cruzada(
    texto: str,
    extraida: FaturaExtraida,
    *,
    sigla: str | None,
    tolerancia_total_rs: Decimal,
) -> list[Alerta]:
    """E6: compara o resultado do LLM com a leitura determinística do texto nativo."""
    alertas: list[Alerta] = []
    for campo, lido in extrair_campos_criticos(texto, sigla).items():
        do_llm: Decimal | None = getattr(extraida, campo).valor
        if do_llm is None:
            continue
        tolerancia = tolerancia_total_rs if campo == "valor_total" else TOLERANCIA_GRANDEZA
        if abs(do_llm - lido) > tolerancia:
            alertas.append(
                Alerta(
                    "CROSSCHECK_DIVERGE",
                    Severidade.AVISO,
                    f"LLM ({do_llm}) difere da leitura direta do texto ({lido}).",
                    campo,
                )
            )
    return alertas
