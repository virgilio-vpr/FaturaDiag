"""Montagem do relatório PDF (§12): contexto a partir do snapshot → Jinja2 → WeasyPrint.

Nada é recalculado aqui: todos os números vêm do snapshot do diagnóstico. Dado ausente é
exibido como “—” e nunca estimado (§17.4).
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import matplotlib
from app.reports import formatacao as f
from app.reports.charts import COR_PRIMARIA_PADRAO, gerar_graficos
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from weasyprint.urls import URLFetcher

PASTA = Path(__file__).parent
PASTA_TEMPLATES = PASTA / "templates"
TEMPLATE = "relatorio.html.j2"
PASTA_FONTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
RESSALVA = (
    "Estimativas preliminares baseadas nos documentos fornecidos; sujeitas à validação técnica "
    "e às regras vigentes da ANEEL/distribuidora. Não constitui garantia de economia."
)
_COR_VALIDA = re.compile(r"^#[0-9a-fA-F]{6}$")
_MIMES_LOGO = {"image/png", "image/jpeg"}
_ORDEM_SEVERIDADE = {"ALTA": 0, "MEDIA": 1, "BAIXA": 2, "INFO": 3}
_ROTULO_SEVERIDADE = {"ALTA": "Alta", "MEDIA": "Média", "BAIXA": "Baixa", "INFO": "Informativo"}
_ROTULO_ESCOPO = {"FATURA_UNICA": "Fatura única", "HISTORICO": "Histórico de faturas"}
TOP_ACHADOS = 3


@dataclass(frozen=True, slots=True)
class MarcaOrganizacao:
    nome: str
    cnpj: str | None = None
    cor_primaria: str | None = None
    logo: bytes | None = None
    logo_mime: str | None = None
    responsavel_tecnico_nome: str | None = None
    responsavel_tecnico_crea: str | None = None
    art_numero: str | None = None


@dataclass(frozen=True, slots=True)
class DadosRelatorio:
    """Tudo o que o relatório precisa, já lido do diagnóstico congelado."""

    diagnostico_id: str
    escopo: str
    periodo_inicio: str
    periodo_fim: str
    status: str
    versao_motor: str
    economia_anual_estimada: str
    economia_mensal_estimada: str
    insumos: Mapping[str, Any]
    resultado: Mapping[str, Any]
    parametros: Mapping[str, Any]
    marca: MarcaOrganizacao
    versao_relatorio: int
    gerado_em: datetime
    cliente: str | None = None
    unidade: str | None = None
    simulacoes_acl: Sequence[Mapping[str, Any]] = ()
    curva_carga_tipica: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    notas: str | None = None


def _cor(marca: MarcaOrganizacao) -> str:
    # Valida o formato: a cor entra em CSS e em SVG.
    return (
        marca.cor_primaria
        if marca.cor_primaria and _COR_VALIDA.match(marca.cor_primaria)
        else (COR_PRIMARIA_PADRAO)
    )


def _logo_uri(marca: MarcaOrganizacao) -> str | None:
    if not marca.logo or marca.logo_mime not in _MIMES_LOGO:
        return None
    return f"data:{marca.logo_mime};base64,{base64.b64encode(marca.logo).decode()}"


def _achados(resultado: Mapping[str, Any]) -> list[dict[str, Any]]:
    brutos = list(resultado.get("achados") or [])

    def chave(a: Mapping[str, Any]) -> tuple[int, Decimal]:
        economia = (
            Decimal(str(a["economia_anual_estimada"]))
            if a.get("economia_anual_estimada")
            else Decimal(0)
        )
        return (_ORDEM_SEVERIDADE.get(str(a["severidade"]), 9), -economia)

    ordenados = sorted(brutos, key=chave)
    return [
        {
            "codigo": a["codigo"],
            "severidade": _ROTULO_SEVERIDADE.get(str(a["severidade"]), str(a["severidade"])),
            "severidade_codigo": str(a["severidade"]),
            "titulo": a["titulo"],
            "descricao": a["descricao"],
            "economia": f.moeda(a.get("economia_anual_estimada"))
            if a.get("economia_anual_estimada") is not None
            else None,
            "evidencias": list(a.get("evidencias") or []),
            "recomendacao": a["recomendacao"],
            "premissas": list(a.get("premissas") or []),
        }
        for a in ordenados
    ]


def _faixa_acl(resultado: Mapping[str, Any]) -> dict[str, str] | None:
    """Faixa conservador–base da simulação ACL, quando os cenários existem no snapshot."""
    acl = resultado.get("acl")
    if not acl:
        return None
    por_nome = {str(c["nome"]).lower(): c for c in acl["cenarios"]}
    if "conservador" not in por_nome or "base" not in por_nome:
        return None
    return {
        "conservador": f.moeda(por_nome["conservador"]["economia_anual"]),
        "base": f.moeda(por_nome["base"]["economia_anual"]),
    }


_PARAMETROS_PERCENTUAIS = {"tolerancia_ultrapassagem", "limiar_subutilizacao"}
_ROTULOS_PARAMETROS = {
    "tolerancia_ultrapassagem": "Tolerância de ultrapassagem",
    "multiplicador_ultrapassagem": "Multiplicador de ultrapassagem",
    "fator_potencia_referencia": "Fator de potência de referência",
    "intervalo_apuracao_fp_min": "Intervalo de apuração do FP (min)",
    "janela_indutiva": "Janela de reativo indutivo",
    "janela_capacitiva": "Janela de reativo capacitivo",
    "demanda_minima_contratada_kw": "Demanda mínima contratada (kW)",
    "modalidades_verde_elegiveis": "Subgrupos elegíveis à modalidade Verde",
    "modalidades_azul_obrigatorias": "Subgrupos com modalidade Azul obrigatória",
    "subgrupos_prioritarios": "Subgrupos prioritários",
    "carga_minima_as_kw": "Carga mínima AS (kW)",
    "limite_varejista_kw": "Limite do consumidor varejista (kW)",
    "prazo_notificacao_migracao_acl_dias": "Prazo de notificação de migração ao ACL (dias)",
    "limiar_subutilizacao": "Limiar de subutilização",
    "tolerancia_divergencia_item_rs": "Tolerância de divergência por item (R$)",
    "vigencia_referencia": "Data de referência dos parâmetros",
}


def _valor_parametro(chave: str, valor: Any) -> str:
    if isinstance(valor, list):
        return ", ".join(str(v) for v in valor) or f.NAO_DISPONIVEL
    if chave in _PARAMETROS_PERCENTUAIS:
        return f.percentual(valor)
    if chave == "vigencia_referencia":
        return f.data(valor)
    if isinstance(valor, str) and re.fullmatch(r"-?\d+(\.\d+)?", valor):
        casas = len(valor.split(".")[1]) if "." in valor else 0
        return f.numero(valor, casas)
    return str(valor)


def _parametros(parametros: Mapping[str, Any], pendentes: Sequence[str]) -> list[dict[str, Any]]:
    linhas = []
    for chave, rotulo in _ROTULOS_PARAMETROS.items():
        if chave in parametros:
            linhas.append(
                {
                    "rotulo": rotulo,
                    "valor": _valor_parametro(chave, parametros[chave]),
                    "pendente": chave in pendentes,
                }
            )
    return linhas


def _indicadores(resultado: Mapping[str, Any]) -> list[dict[str, str]]:
    ind = resultado.get("indicadores") or {}
    return [
        {"rotulo": "Fator de carga", "valor": f.percentual(ind.get("fator_de_carga"))},
        {"rotulo": "Utilização da demanda", "valor": f.percentual(ind.get("utilizacao_demanda"))},
        {"rotulo": "Consumo na ponta", "valor": f.percentual(ind.get("pct_consumo_ponta"))},
        {"rotulo": "Custo médio (R$/MWh)", "valor": f.numero(ind.get("custo_medio_rs_mwh"), 2)},
    ]


def _simulacoes(simulacoes: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    linhas = []
    for s in simulacoes:
        cenario = s["resultado"]["cenario"]
        linhas.append(
            {
                "cenario": str(s["cenario"]).capitalize(),
                "preco": f.numero(cenario["preco_rs_mwh"], 2),
                "economia_mensal": f.moeda(cenario["economia_mensal"]),
                "economia_anual": f.moeda(cenario["economia_anual"]),
                "payback": f.numero(cenario["payback_meses"], 1)
                if cenario.get("payback_meses") is not None
                else f.NAO_DISPONIVEL,
            }
        )
    return linhas


def montar_contexto(dados: DadosRelatorio) -> dict[str, Any]:
    cor = _cor(dados.marca)
    resultado = dados.resultado
    achados = _achados(resultado)
    pendentes = list(resultado.get("parametros_pendentes") or [])
    premissas = list(resultado.get("premissas_montagem") or []) + list(
        resultado.get("premissas") or []
    )
    graficos = gerar_graficos(
        dados.insumos,
        resultado,
        curva_carga_tipica=dados.curva_carga_tipica,
        cor_primaria=cor,
    )
    marca = dados.marca
    return {
        "cor_primaria": cor,
        "logo_uri": _logo_uri(marca),
        "organizacao": {"nome": marca.nome, "cnpj": marca.cnpj},
        "titulo": "Diagnóstico energético de fatura",
        "cliente": dados.cliente,
        "unidade": dados.unidade,
        "escopo": _ROTULO_ESCOPO.get(dados.escopo, dados.escopo),
        "periodo": f"{f.referencia(dados.periodo_inicio)} a {f.referencia(dados.periodo_fim)}",
        "meses": resultado.get("meses"),
        "indicativo": bool(resultado.get("indicativo")),
        "economia_anual": f.moeda(dados.economia_anual_estimada),
        "economia_mensal": f.moeda(dados.economia_mensal_estimada),
        "faixa_acl": _faixa_acl(resultado),
        "indicadores": _indicadores(resultado),
        "top_achados": achados[:TOP_ACHADOS],
        "achados": achados,
        "plano": [
            {
                "ordem": i,
                "titulo": a["titulo"],
                "severidade": a["severidade"],
                "retorno": a["economia"] or "Sem estimativa de economia",
                "acao": a["recomendacao"],
            }
            for i, a in enumerate(achados, start=1)
            if a["severidade_codigo"] != "INFO" or a["economia"]
        ],
        "graficos": graficos,
        "simulacoes_acl": _simulacoes(dados.simulacoes_acl),
        "premissas": premissas,
        "parametros": _parametros(dados.parametros, pendentes),
        "parametros_pendentes": pendentes,
        "versao_motor": dados.versao_motor,
        "versao_relatorio": dados.versao_relatorio,
        "status_diagnostico": dados.status,
        "diagnostico_id": dados.diagnostico_id,
        "gerado_em": f"{f.data(dados.gerado_em)} {dados.gerado_em.strftime('%H:%M')}",
        "notas": dados.notas,
        "ressalva": RESSALVA,
        "responsavel": {
            "nome": marca.responsavel_tecnico_nome,
            "crea": marca.responsavel_tecnico_crea,
            "art": marca.art_numero,
        },
        "fontes_css": {
            "regular": (PASTA_FONTES / "DejaVuSans.ttf").as_uri(),
            "bold": (PASTA_FONTES / "DejaVuSans-Bold.ttf").as_uri(),
        },
        "fmt": f,
    }


def renderizar_html(dados: DadosRelatorio) -> str:
    ambiente = Environment(
        loader=FileSystemLoader(PASTA_TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
    )
    return ambiente.get_template(TEMPLATE).render(**montar_contexto(dados))


class _BuscadorRestrito(URLFetcher):  # type: ignore[misc]
    """Só carrega as fontes embutidas; bloqueia rede e demais arquivos locais (anti-SSRF/LFI)."""

    def __init__(self) -> None:
        super().__init__(allowed_protocols={"data", "file"})

    def fetch(self, url: str, headers: Any = None) -> Any:
        if url.startswith("file:") and Path(unquote(urlparse(url).path)).parent != PASTA_FONTES:
            raise ValueError(f"Recurso local bloqueado no relatório: {url[:80]}")
        return super().fetch(url, headers)


def renderizar_pdf(dados: DadosRelatorio) -> bytes:
    pdf: bytes = HTML(string=renderizar_html(dados), url_fetcher=_BuscadorRestrito()).write_pdf()
    return pdf
