"""Gráficos do relatório (§12.2): matplotlib sem pyplot, exportados como SVG.

Os gráficos leem apenas o snapshot JSON do diagnóstico (valores Decimal como texto) e nunca
recalculam resultados. Float é usado só como coordenada de desenho. Sem dados suficientes,
a função devolve `None` e o gráfico é omitido, sem estimar nada.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from threading import Lock
from typing import Any

import matplotlib as mpl
from babel.numbers import format_decimal
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

COR_PRIMARIA_PADRAO = "#1f4e79"
COR_APOIO = "#8a9bab"
COR_ALERTA = "#c0392b"
FONTE = "DejaVu Sans"
_RC: dict[Any, Any] = {"svg.fonttype": "none", "svg.hashsalt": "faturadiag", "font.family": FONTE}

_LOCK = Lock()
Snapshot = Mapping[str, Any]


def _dec(valor: object) -> Decimal | None:
    if valor is None:
        return None
    return Decimal(str(valor))


def _num(valor: object) -> float | None:
    numero = _dec(valor)
    return None if numero is None else float(numero)


def _req(valor: object) -> float:
    numero = _num(valor)
    if numero is None:
        raise ValueError("Snapshot do diagnóstico com valor ausente para o gráfico.")
    return numero


def _br(valor: float, casas: int = 0) -> str:
    return format_decimal(
        valor, format="#,##0" + ("." + "0" * casas if casas else ""), locale="pt_BR"
    )


def _eixo_br(eixo: Axes, *, x: bool = False, y: bool = True, casas: int = 0) -> None:
    formatador = FuncFormatter(lambda v, _p: _br(v, casas))
    if x:
        eixo.xaxis.set_major_formatter(formatador)
    if y:
        eixo.yaxis.set_major_formatter(formatador)


def _novo(titulo: str, *, largura: float = 7.0, altura: float = 3.2) -> tuple[Figure, Axes]:
    figura = Figure(figsize=(largura, altura), layout="constrained")
    eixo = figura.add_subplot()
    eixo.set_title(titulo, fontsize=10, loc="left")
    eixo.grid(axis="y", color="#e3e8ed", linewidth=0.7)
    eixo.set_axisbelow(True)
    for lado in ("top", "right"):
        eixo.spines[lado].set_visible(False)
    return figura, eixo


def _svg(figura: Figure, titulo: str) -> str:
    buffer = io.StringIO()
    figura.savefig(
        buffer,
        format="svg",
        metadata={"Date": None, "Title": titulo, "Creator": "FaturaDiag"},
    )
    return buffer.getvalue()


def _meses(snapshot_insumos: Snapshot) -> list[Mapping[str, Any]]:
    return list(snapshot_insumos.get("meses") or [])


def _rotulos(meses: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(m["referencia"]) for m in meses]


def grafico_consumo_ponta_fora_ponta(
    insumos: Snapshot, *, cor_primaria: str = COR_PRIMARIA_PADRAO
) -> str | None:
    """Barras agrupadas de consumo (kWh) na ponta e fora de ponta por mês."""
    meses = _meses(insumos)
    if not meses:
        return None
    titulo = "Consumo por posto horário (kWh)"
    with _contexto():
        figura, eixo = _novo(titulo)
        posicoes = list(range(len(meses)))
        largura = 0.38
        eixo.bar(
            [p - largura / 2 for p in posicoes],
            [_num(m["consumo_ponta_kwh"]) or 0 for m in meses],
            largura,
            label="Ponta",
            color=cor_primaria,
        )
        eixo.bar(
            [p + largura / 2 for p in posicoes],
            [_num(m["consumo_fora_ponta_kwh"]) or 0 for m in meses],
            largura,
            label="Fora de ponta",
            color=COR_APOIO,
        )
        eixo.set_xticks(posicoes, _rotulos(meses), rotation=45 if len(meses) > 6 else 0)
        eixo.set_ylabel("kWh")
        _eixo_br(eixo)
        eixo.legend(frameon=False, fontsize=8)
        return _svg(figura, titulo)


def grafico_demanda_medida_contratada(
    insumos: Snapshot, *, cor_primaria: str = COR_PRIMARIA_PADRAO
) -> str | None:
    """Dm por mês e Dc vigente (linha); Verde usa uma Dc única, Azul uma por posto."""
    meses = _meses(insumos)
    if not meses:
        return None
    titulo = "Demanda medida × contratada (kW)"
    verde = insumos.get("modalidade_atual") == "VERDE"
    with _contexto():
        figura, eixo = _novo(titulo)
        rotulos = _rotulos(meses)
        if verde:
            eixo.plot(
                rotulos,
                [max(_num(m["dm_ponta_kw"]) or 0, _num(m["dm_fora_ponta_kw"]) or 0) for m in meses],
                marker="o",
                color=cor_primaria,
                label="Dm (maior entre postos)",
            )
            _linha_dc(eixo, rotulos, insumos.get("dc_unica_kw"), "Dc", COR_ALERTA)
        else:
            eixo.plot(
                rotulos,
                [_num(m["dm_ponta_kw"]) or 0 for m in meses],
                marker="o",
                color=cor_primaria,
                label="Dm ponta",
            )
            eixo.plot(
                rotulos,
                [_num(m["dm_fora_ponta_kw"]) or 0 for m in meses],
                marker="o",
                color=COR_APOIO,
                label="Dm fora de ponta",
            )
            _linha_dc(eixo, rotulos, insumos.get("dc_ponta_kw"), "Dc ponta", COR_ALERTA)
            _linha_dc(eixo, rotulos, insumos.get("dc_fora_ponta_kw"), "Dc fora de ponta", "#e08e0b")
        eixo.set_ylabel("kW")
        eixo.tick_params(axis="x", rotation=45 if len(meses) > 6 else 0)
        _eixo_br(eixo)
        eixo.legend(frameon=False, fontsize=8)
        return _svg(figura, titulo)


def _linha_dc(eixo: Axes, rotulos: Sequence[str], dc: object, nome: str, cor: str) -> None:
    valor = _num(dc)
    if valor is not None:
        eixo.plot(rotulos, [valor] * len(rotulos), linestyle="--", color=cor, label=nome)


def grafico_custo_por_demanda(
    resultado: Snapshot, *, cor_primaria: str = COR_PRIMARIA_PADRAO
) -> str | None:
    """Custo anual × Dc candidata, destacando a Dc ótima (curva do motor, não recalculada)."""
    otima = resultado.get("demanda_otima")
    if not otima:
        return None
    postos = (
        [("Ponta", otima["ponta"]), ("Fora de ponta", otima["fora_ponta"])]
        if "ponta" in otima
        else [("Demanda única", otima)]
    )
    postos = [(nome, p) for nome, p in postos if p.get("curva")]
    if not postos:
        return None
    titulo = "Custo anual × demanda contratada (R$)"
    with _contexto():
        figura, eixo = _novo(titulo)
        cores = [cor_primaria, COR_APOIO]
        for (nome, posto), cor in zip(postos, cores, strict=False):
            eixo.plot(
                [_req(p["dc_kw"]) for p in posto["curva"]],
                [_req(p["custo_anual"]) for p in posto["curva"]],
                color=cor,
                label=nome,
            )
            dc_otima = _req(posto["dc_otima_kw"])
            custo_otimo = _req(posto["custo_anual_otimo"])
            eixo.plot(
                [dc_otima],
                [custo_otimo],
                marker="*",
                markersize=11,
                color=COR_ALERTA,
                linestyle="none",
            )
            eixo.annotate(
                f"Dc ótima {_br(dc_otima)} kW",
                (dc_otima, custo_otimo),
                textcoords="offset points",
                xytext=(6, 8),
                fontsize=8,
            )
        eixo.set_xlabel("Dc candidata (kW)")
        eixo.set_ylabel("R$/ano")
        _eixo_br(eixo, x=True)
        eixo.legend(frameon=False, fontsize=8)
        return _svg(figura, titulo)


def grafico_cativo_livre(
    resultado: Snapshot, *, cor_primaria: str = COR_PRIMARIA_PADRAO
) -> str | None:
    """Custo mensal cativo × livre por cenário de preço e sensibilidade da economia ao preço."""
    acl = resultado.get("acl")
    if not acl or not acl.get("cenarios"):
        return None
    cenarios = acl["cenarios"]
    sensibilidade = acl.get("sensibilidade") or []
    titulo = "Mercado cativo × livre (R$/mês)"
    with _contexto():
        figura = Figure(figsize=(7.0, 3.4), layout="constrained")
        eixos = figura.subplots(1, 2 if sensibilidade else 1, squeeze=False)[0]
        barras = eixos[0]
        barras.set_title(titulo, fontsize=10, loc="left")
        posicoes = list(range(len(cenarios)))
        largura = 0.38
        barras.bar(
            [p - largura / 2 for p in posicoes],
            [_req(c["custo_cativo_mes"]) for c in cenarios],
            largura,
            label="Cativo",
            color=COR_APOIO,
        )
        barras.bar(
            [p + largura / 2 for p in posicoes],
            [_req(c["custo_livre_mes"]) for c in cenarios],
            largura,
            label="Livre",
            color=cor_primaria,
        )
        barras.set_xticks(
            posicoes,
            [f"{c['nome']}\n{_br(_req(c['preco_rs_mwh']), 2)} R$/MWh" for c in cenarios],
            fontsize=8,
        )
        _eixo_br(barras)
        barras.legend(frameon=False, fontsize=8)
        if sensibilidade:
            linha = eixos[1]
            linha.set_title("Sensibilidade ao preço", fontsize=10, loc="left")
            linha.plot(
                [_req(p["preco_rs_mwh"]) for p in sensibilidade],
                [_req(p["economia_mensal"]) for p in sensibilidade],
                marker="o",
                color=cor_primaria,
            )
            linha.axhline(0, color=COR_ALERTA, linewidth=0.8)
            linha.set_xlabel("Preço da energia (R$/MWh)")
            linha.set_ylabel("Economia mensal (R$)")
            _eixo_br(linha, x=True)
        for eixo in eixos:
            eixo.grid(axis="y", color="#e3e8ed", linewidth=0.7)
            for lado in ("top", "right"):
                eixo.spines[lado].set_visible(False)
        return _svg(figura, titulo)


def grafico_curva_carga_tipica(
    curva: Sequence[Mapping[str, Any]], *, cor_primaria: str = COR_PRIMARIA_PADRAO
) -> str | None:
    """Curva de carga típica (kW por hora do dia), a partir da memória de massa já resumida.

    Cada ponto: `{"hora": int, "dia_util_kw": str, "fim_de_semana_kw": str | None}`.
    """
    if not curva:
        return None
    titulo = "Curva de carga típica (kW)"
    with _contexto():
        figura, eixo = _novo(titulo)
        horas = [int(p["hora"]) for p in curva]
        eixo.plot(
            horas,
            [_req(p["dia_util_kw"]) for p in curva],
            color=cor_primaria,
            label="Dia útil",
        )
        if all(p.get("fim_de_semana_kw") is not None for p in curva):
            eixo.plot(
                horas,
                [_req(p["fim_de_semana_kw"]) for p in curva],
                color=COR_APOIO,
                label="Fim de semana",
            )
        eixo.set_xlabel("Hora do dia")
        eixo.set_ylabel("kW")
        eixo.set_xticks(range(0, 24, 3))
        _eixo_br(eixo)
        eixo.legend(frameon=False, fontsize=8)
        return _svg(figura, titulo)


def gerar_graficos(
    insumos: Snapshot,
    resultado: Snapshot,
    *,
    curva_carga_tipica: Sequence[Mapping[str, Any]] = (),
    cor_primaria: str = COR_PRIMARIA_PADRAO,
) -> dict[str, str]:
    """Gera os gráficos possíveis a partir do snapshot; chaves ausentes = sem dados."""
    candidatos = {
        "curva_carga": grafico_curva_carga_tipica(curva_carga_tipica, cor_primaria=cor_primaria),
        "consumo_postos": grafico_consumo_ponta_fora_ponta(insumos, cor_primaria=cor_primaria),
        "demanda": grafico_demanda_medida_contratada(insumos, cor_primaria=cor_primaria),
        "custo_demanda": grafico_custo_por_demanda(resultado, cor_primaria=cor_primaria),
        "cativo_livre": grafico_cativo_livre(resultado, cor_primaria=cor_primaria),
    }
    return {nome: svg for nome, svg in candidatos.items() if svg is not None}


@contextmanager
def _contexto() -> Iterator[None]:
    """rcParams são globais: aplica-os sob lock e só durante o desenho."""
    with _LOCK, mpl.rc_context(_RC):
        yield
