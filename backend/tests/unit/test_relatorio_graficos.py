from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

import pytest
from app.domain.energia.acl import CenarioPreco, EntradaACL, simular_acl
from app.domain.energia.demanda_otima import otimizar_azul, otimizar_verde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.modules.diagnosticos.snapshot import para_json
from app.reports import charts
from tests.support.diagnosticos import PARAMETROS, D

MESES = [
    {
        "referencia": f"2026-{mes:02d}",
        "dm_ponta_kw": str(250 + mes),
        "dm_fora_ponta_kw": str(300 + mes),
        "consumo_ponta_kwh": "10000",
        "consumo_fora_ponta_kwh": "90000",
    }
    for mes in range(1, 13)
]
INSUMOS_VERDE: dict[str, Any] = {"modalidade_atual": "VERDE", "dc_unica_kw": "500", "meses": MESES}
INSUMOS_AZUL: dict[str, Any] = {
    "modalidade_atual": "AZUL",
    "dc_ponta_kw": "300",
    "dc_fora_ponta_kw": "400",
    "meses": MESES,
}


def _verde() -> dict[str, Any]:
    dm = [D(m["dm_ponta_kw"]) for m in MESES]
    fp = [D(m["dm_fora_ponta_kw"]) for m in MESES]
    return {
        "demanda_otima": para_json(otimizar_verde(dm, fp, D("40"), D("0.05"), D("2"), D("30"))),
        "acl": None,
    }


def _azul() -> dict[str, Any]:
    dm = [D(m["dm_ponta_kw"]) for m in MESES]
    fp = [D(m["dm_fora_ponta_kw"]) for m in MESES]
    resultado = otimizar_azul(dm, fp, D("60"), D("20"), D("0.05"), D("2"), D("30"))
    return {"demanda_otima": para_json(resultado), "acl": None}


def _acl(parametros: ParametrosRegulatorios = PARAMETROS) -> dict[str, Any]:
    entrada = EntradaACL(
        consumo_mwh_mes=D("100"),
        te_cativa_rs_mwh=D("300"),
        encargos_rs_mwh=D("20"),
        custos_fixos_mes=D("1000"),
    )
    cenarios = (
        CenarioPreco("conservador", D("280")),
        CenarioPreco("base", D("230")),
        CenarioPreco("otimista", D("200")),
    )
    return {"demanda_otima": None, "acl": para_json(simular_acl(entrada, cenarios, parametros))}


def _texto(svg: str) -> str:
    raiz = ElementTree.fromstring(svg)  # SVG precisa ser XML válido
    assert raiz.tag.endswith("svg")
    return " ".join(el.text.strip() for el in raiz.iter() if el.text and el.text.strip())


def test_consumo_por_posto_e_svg_valido_com_rotulos() -> None:
    svg = charts.grafico_consumo_ponta_fora_ponta(INSUMOS_VERDE)
    assert svg is not None
    texto = _texto(svg)
    assert "Consumo por posto horário (kWh)" in texto
    assert "Ponta" in texto and "Fora de ponta" in texto and "2026-12" in texto
    assert "80.000" in texto  # separador de milhar pt-BR


def test_demanda_verde_usa_dc_unica_e_azul_dc_por_posto() -> None:
    verde = charts.grafico_demanda_medida_contratada(INSUMOS_VERDE)
    azul = charts.grafico_demanda_medida_contratada(INSUMOS_AZUL)
    assert verde is not None and azul is not None
    assert "Dc" in _texto(verde) and "Dc ponta" not in _texto(verde)
    assert "Dc ponta" in _texto(azul) and "Dc fora de ponta" in _texto(azul)


def test_custo_por_demanda_destaca_dc_otima_verde_e_azul() -> None:
    verde, azul = _verde(), _azul()
    svg_verde = charts.grafico_custo_por_demanda(verde)
    svg_azul = charts.grafico_custo_por_demanda(azul)
    assert svg_verde is not None and svg_azul is not None
    assert f"Dc ótima {int(D(verde['demanda_otima']['dc_otima_kw']))} kW" in _texto(svg_verde)
    texto_azul = _texto(svg_azul)
    assert texto_azul.count("Dc ótima") == 2 and "Fora de ponta" in texto_azul


def test_cativo_livre_mostra_cenarios_e_sensibilidade() -> None:
    svg = charts.grafico_cativo_livre(_acl())
    assert svg is not None
    texto = _texto(svg)
    assert {"conservador", "base", "otimista"} <= set(texto.replace("\n", " ").split())
    assert "Sensibilidade ao preço" in texto and "280,00 R$/MWh" in texto


def test_curva_de_carga_tipica() -> None:
    curva = [
        {"hora": h, "dia_util_kw": str(100 + h), "fim_de_semana_kw": str(80 + h)} for h in range(24)
    ]
    sem_fds = [{"hora": h, "dia_util_kw": "100", "fim_de_semana_kw": None} for h in range(24)]
    completo, parcial = (
        charts.grafico_curva_carga_tipica(curva),
        (charts.grafico_curva_carga_tipica(sem_fds)),
    )
    assert completo is not None and parcial is not None
    assert "Fim de semana" in _texto(completo) and "Fim de semana" not in _texto(parcial)


def test_sem_dados_omite_grafico_em_vez_de_estimar() -> None:
    assert charts.grafico_consumo_ponta_fora_ponta({"meses": []}) is None
    assert charts.grafico_demanda_medida_contratada({}) is None
    assert charts.grafico_custo_por_demanda({"demanda_otima": None}) is None
    assert charts.grafico_custo_por_demanda({"demanda_otima": {"curva": []}}) is None
    assert charts.grafico_cativo_livre({"acl": None}) is None
    assert charts.grafico_curva_carga_tipica([]) is None
    assert charts.gerar_graficos({}, {}) == {}


def test_valor_ausente_na_serie_e_erro_explicito() -> None:
    resultado = _verde()
    resultado["demanda_otima"]["curva"][0]["custo_anual"] = None
    with pytest.raises(ValueError, match="valor ausente"):
        charts.grafico_custo_por_demanda(resultado)


def test_gerar_graficos_e_deterministico_e_respeita_cor_da_organizacao() -> None:
    insumos, resultado = INSUMOS_VERDE, {**_verde(), **_acl()}
    resultado["demanda_otima"] = _verde()["demanda_otima"]

    primeira = charts.gerar_graficos(insumos, resultado, cor_primaria="#12ab34")
    segunda = charts.gerar_graficos(insumos, resultado, cor_primaria="#12ab34")

    assert set(primeira) == {"consumo_postos", "demanda", "custo_demanda", "cativo_livre"}
    assert primeira == segunda
    assert all("#12ab34" in svg for svg in primeira.values())
    assert "<script" not in "".join(primeira.values())
