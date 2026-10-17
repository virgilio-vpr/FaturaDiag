from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
HINTS_DIR = PROMPTS_DIR / "hints"
HINT_GENERICO = "_generico"


@dataclass(frozen=True)
class HintArquivo:
    nome: str
    conteudo: str
    especifico: bool


def carregar_hint_arquivo(sigla: str | None) -> HintArquivo:
    """Hint em arquivo da distribuidora; cai no genérico quando não há específico."""
    if sigla:
        nome = sigla.strip().casefold()
        if nome.isidentifier() and not nome.startswith("_"):
            caminho = HINTS_DIR / f"{nome}.md"
            if caminho.is_file():
                return HintArquivo(nome, caminho.read_text(encoding="utf-8"), True)
    conteudo = (HINTS_DIR / f"{HINT_GENERICO}.md").read_text(encoding="utf-8")
    return HintArquivo(HINT_GENERICO, conteudo, False)
