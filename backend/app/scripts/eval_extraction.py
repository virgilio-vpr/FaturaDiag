"""Avaliação da extração (T-5.8): acurácia por campo, distribuidora e hint, custo e latência.

Por padrão usa fixtures SINTÉTICAS e respostas gravadas (`FakeProvider`), sem rede. A avaliação
ao vivo (`--live`) usa o provedor configurado no `.env`, gera custo e deve ser manual.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.integrations.llm.extrator import Alvo, ExtratorLLM, PrecoTokens
from app.integrations.llm.factory import criar_extrator
from app.integrations.llm.fake import FakeProvider
from app.integrations.llm.schemas import FaturaExtraida
from app.modules.faturas.extracao import HintResolvido, executar_extracao, resolver_hint_arquivo
from app.scripts.pdf_sintetico import pdf_com_texto

RAIZ_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
VARIANTES = ("com_hint", "sem_hint")
META_GANHO_HINT = Decimal("0.05")
CONFIANCA_GRAVADA = 0.95
CAMPOS_ESTRUTURAIS = ("itens", "observacoes_extrator")
TOLERANCIA_TOTAL_RS = Decimal("0.05")


@dataclass(frozen=True)
class Caso:
    sigla: str
    nome: str
    linhas: list[str]
    esperado: dict[str, Any]
    ajustes: dict[str, dict[str, Any]]


@dataclass
class Placar:
    acertos: int = 0
    total: int = 0

    @property
    def taxa(self) -> Decimal:
        return Decimal(self.acertos) / Decimal(self.total) if self.total else Decimal(0)


@dataclass
class Relatorio:
    live: bool
    por_campo: dict[str, dict[str, Placar]] = field(default_factory=dict)
    por_distribuidora: dict[str, dict[str, Placar]] = field(default_factory=dict)
    por_hint: dict[str, Placar] = field(default_factory=dict)
    geral: dict[str, Placar] = field(default_factory=dict)
    custo_brl: dict[str, Decimal] = field(default_factory=dict)
    latencia_ms: dict[str, list[float]] = field(default_factory=dict)

    @property
    def ganho_hint(self) -> Decimal:
        return self.geral["com_hint"].taxa - self.geral["sem_hint"].taxa

    @property
    def atinge_meta(self) -> bool:
        return self.ganho_hint >= META_GANHO_HINT


def carregar_casos(raiz: Path = RAIZ_FIXTURES) -> list[Caso]:
    casos: list[Caso] = []
    for arquivo in sorted((raiz / "faturas").glob("*/*.json")):
        sigla, nome = arquivo.parent.name, arquivo.stem
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        gravado = raiz / "llm" / f"{sigla}__{nome}.json"
        ajustes = json.loads(gravado.read_text(encoding="utf-8")) if gravado.is_file() else {}
        casos.append(
            Caso(
                sigla,
                nome,
                list(dados["linhas"]),
                dict(dados["esperado"]),
                {v: dict(ajustes.get(v, {})) for v in VARIANTES},
            )
        )
    return casos


def resposta_gravada(esperado: dict[str, Any], ajustes: dict[str, Any]) -> dict[str, Any]:
    """Resposta do LLM = valores esperados com os erros gravados da variante aplicados."""
    valores = {**esperado, **ajustes}
    resposta: dict[str, Any] = {}
    for nome in FaturaExtraida.model_fields:
        if nome in CAMPOS_ESTRUTURAIS:
            continue
        valor = valores.get(nome)
        resposta[nome] = {
            "valor": valor,
            "confianca": CONFIANCA_GRAVADA if valor is not None else 0.0,
            "evidencia": None,
            "pagina": 1,
        }
    resposta["itens"] = valores.get("itens", [])
    resposta["observacoes_extrator"] = []
    return resposta


def valores_iguais(esperado: Any, obtido: Any) -> bool:
    if esperado is None or obtido is None:
        return esperado is None and obtido is None
    try:
        return Decimal(str(esperado)) == Decimal(str(obtido))
    except InvalidOperation:
        return str(esperado) == str(obtido)


def _resolver_para(variante: str) -> Callable[[str | None], HintResolvido]:
    if variante == "com_hint":
        return resolver_hint_arquivo
    return lambda _sigla: resolver_hint_arquivo(None)


def _extrator_gravado(caso: Caso, variante: str, settings: Settings) -> ExtratorLLM:
    resposta = resposta_gravada(caso.esperado, caso.ajustes[variante])
    return ExtratorLLM(
        Alvo(FakeProvider([resposta]), "gravado"),
        preco=PrecoTokens(
            settings.llm_preco_entrada_brl_por_mtok, settings.llm_preco_saida_brl_por_mtok
        ),
    )


def avaliar(
    casos: list[Caso],
    *,
    live: bool = False,
    settings: Settings | None = None,
) -> Relatorio:
    settings = settings or Settings()
    relatorio = Relatorio(live=live)
    extrator_ao_vivo = criar_extrator(settings) if live else None
    for variante in VARIANTES:
        relatorio.geral[variante] = Placar()
        relatorio.custo_brl[variante] = Decimal(0)
        relatorio.latencia_ms[variante] = []
    for caso in casos:
        conteudo = pdf_com_texto([caso.linhas])
        sha = hashlib.sha256(conteudo).hexdigest()
        for variante in VARIANTES:
            extrator = extrator_ao_vivo or _extrator_gravado(caso, variante, settings)
            inicio = time.perf_counter()
            resultado = executar_extracao(
                extrator,
                conteudo=conteudo,
                mime="application/pdf",
                sha256=sha,
                tolerancia_divergencia_rs=TOLERANCIA_TOTAL_RS,
                resolver_hint=_resolver_para(variante),
            )
            relatorio.latencia_ms[variante].append((time.perf_counter() - inicio) * 1000)
            relatorio.custo_brl[variante] += Decimal(
                str(resultado.resultado.usage.custo_estimado or 0)
            )
            for nome in FaturaExtraida.model_fields:
                if nome in CAMPOS_ESTRUTURAIS:
                    continue
                acertou = valores_iguais(
                    caso.esperado.get(nome), getattr(resultado.extraida, nome).valor
                )
                chaves = (
                    relatorio.por_campo.setdefault(nome, {}).setdefault(variante, Placar()),
                    relatorio.por_distribuidora.setdefault(caso.sigla, {}).setdefault(
                        variante, Placar()
                    ),
                    relatorio.por_hint.setdefault(f"{variante}:{resultado.hint_usado}", Placar()),
                    relatorio.geral[variante],
                )
                for placar in chaves:
                    placar.total += 1
                    placar.acertos += int(acertou)
    return relatorio


def _pct(placar: Placar | None) -> str:
    return f"{placar.taxa * 100:6.1f}%" if placar and placar.total else "     -"


def formatar(relatorio: Relatorio) -> str:
    modo = "AO VIVO" if relatorio.live else "FIXTURES SINTÉTICAS + respostas gravadas"
    linhas = [f"Avaliação de extração — {modo}"]
    if not relatorio.live:
        linhas.append(
            "ATENÇÃO: dados sintéticos validam o harness; NÃO representam a acurácia real (D-11)."
        )
    linhas += ["", "Acurácia geral", "  variante     acurácia"]
    linhas += [f"  {v:<10} {_pct(relatorio.geral[v])}" for v in VARIANTES]
    linhas += ["", "Por distribuidora        com_hint  sem_hint"]
    for sigla, placares in sorted(relatorio.por_distribuidora.items()):
        linhas.append(
            f"  {sigla:<22} {_pct(placares.get('com_hint'))} {_pct(placares.get('sem_hint'))}"
        )
    linhas += ["", "Por hint usado"]
    linhas += [f"  {chave:<30} {_pct(p)}" for chave, p in sorted(relatorio.por_hint.items())]
    erros = {
        nome: placares
        for nome, placares in relatorio.por_campo.items()
        if any(p.acertos < p.total for p in placares.values())
    }
    linhas += ["", "Campos com erro        com_hint  sem_hint"]
    linhas += [
        f"  {nome:<30} {_pct(p.get('com_hint'))} {_pct(p.get('sem_hint'))}"
        for nome, p in sorted(erros.items())
    ] or ["  (nenhum)"]
    linhas += ["", "Custo e latência"]
    for v in VARIANTES:
        latencias = relatorio.latencia_ms[v]
        media = sum(latencias) / len(latencias) if latencias else 0.0
        linhas.append(
            f"  {v:<10} custo R$ {relatorio.custo_brl[v]:.4f}   latência média {media:.1f} ms"
        )
    meta = "ATINGIDA" if relatorio.atinge_meta else "NÃO atingida"
    linhas += [
        "",
        f"Ganho do hint específico: {relatorio.ganho_hint * 100:+.1f} p.p. "
        f"(meta ≥ {META_GANHO_HINT * 100:.0f} p.p.: {meta})",
    ]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=RAIZ_FIXTURES)
    parser.add_argument("--live", action="store_true", help="usa o LLM configurado (gera custo)")
    parser.add_argument("--exigir-meta", action="store_true", help="falha se o ganho < meta")
    args = parser.parse_args(argv)
    casos = carregar_casos(args.fixtures)
    if not casos:
        print("Nenhuma fixture encontrada.", file=sys.stderr)
        return 2
    relatorio = avaliar(casos, live=args.live)
    print(formatar(relatorio))
    return 1 if args.exigir_meta and not relatorio.atinge_meta else 0


if __name__ == "__main__":
    raise SystemExit(main())
