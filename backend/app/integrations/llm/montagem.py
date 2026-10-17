from __future__ import annotations

import re
import unicodedata

from app.integrations.llm.hints import PROMPTS_DIR

PROMPT_VERSAO = "v1"
PROMPT_ARQUIVO = f"extracao_fatura.{PROMPT_VERSAO}.md"

_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TELEFONE = re.compile(r"(?<!\d)(?:\(\d{2}\)\s?|\d{2}\s)9?\d{4}-\d{4}(?!\d)")

PALAVRAS_CHAVE: dict[str, re.Pattern[str]] = {
    "ENEL_SP": re.compile(r"enel distribuicao sao paulo"),
    "ENEL_RJ": re.compile(r"enel distribuicao rio"),
    "EDP_SP": re.compile(r"edp sao paulo"),
    "EDP_ES": re.compile(r"edp espirito santo"),
    "CPFL_PAULISTA": re.compile(r"cpfl paulista"),
    "CPFL_PIRATININGA": re.compile(r"cpfl piratininga"),
    "ELEKTRO": re.compile(r"\belektro\b"),
}


def montar_system_prompt(hint_md: str) -> str:
    base = (PROMPTS_DIR / PROMPT_ARQUIVO).read_text(encoding="utf-8").strip()
    return f"{base}\n\n--- HINT DA DISTRIBUIDORA ---\n{hint_md.strip()}"


def minimizar_texto(texto: str) -> str:
    """Remove CPF, e-mails e telefones antes de enviar o texto ao provedor (§10.4)."""
    texto = _CPF.sub("[CPF OMITIDO]", texto)
    texto = _EMAIL.sub("[EMAIL OMITIDO]", texto)
    return _TELEFONE.sub("[TELEFONE OMITIDO]", texto)


def detectar_distribuidora(texto: str) -> str | None:
    """Sigla da distribuidora por palavras-chave; None se ausente ou ambígua."""
    normalizado = unicodedata.normalize("NFKD", " ".join(texto.casefold().split()))
    normalizado = re.sub(r"[\u0300-\u036f]", "", normalizado)
    encontradas = [sigla for sigla, padrao in PALAVRAS_CHAVE.items() if padrao.search(normalizado)]
    return encontradas[0] if len(encontradas) == 1 else None
