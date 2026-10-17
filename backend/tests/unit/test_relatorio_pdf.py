from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pdfplumber
import pytest
from app.reports import formatacao as f
from app.reports.builder import (
    RESSALVA,
    DadosRelatorio,
    MarcaOrganizacao,
    montar_contexto,
    renderizar_html,
    renderizar_pdf,
)
from app.scripts.report_sample import dados_amostra

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)


def _paginas(pdf: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [" ".join((p.extract_text() or "").split()) for p in doc.pages]


def test_formatacao_pt_br() -> None:
    assert f.moeda("1234.5") == "R$ 1.234,50"
    assert f.moeda("-10") == "-R$ 10,00"
    assert f.percentual("0.125") == "12,5 %"
    assert f.data("2026-03-05") == "05/03/2026"
    assert f.referencia("2026-03-01") == "03/2026"
    assert f.moeda(None) == f.NAO_DISPONIVEL == f.numero("")


def test_pdf_tem_numeros_chave_ressalva_e_paginas_a4() -> None:
    dados = dados_amostra()
    pdf = renderizar_pdf(dados)
    paginas = _paginas(pdf)
    texto = " ".join(paginas)
    assert 3 <= len(paginas) <= 5
    assert f.moeda(dados.economia_anual_estimada) in texto
    assert f.moeda(dados.economia_mensal_estimada) in texto
    assert " ".join(RESSALVA.split()) in texto
    assert f"Motor de cálculo {dados.versao_motor}" in texto
    assert "18/10/2026" in texto and "Fulano de Tal" in texto
    assert "(a validar)" in texto  # parâmetro pendente sinalizado
    assert all(f"Página {i} de {len(paginas)}" in p for i, p in enumerate(paginas, start=1))
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert round(doc.pages[0].width) == 595 and round(doc.pages[0].height) == 842  # A4


def test_linguagem_nunca_promete_economia() -> None:
    html = renderizar_html(dados_amostra()).lower()
    assert "garantid" not in html.replace("não constitui garantia de economia", "")
    assert "economia anual potencial (estimativa)" in html


def test_cor_e_logo_da_organizacao() -> None:
    marca = MarcaOrganizacao(
        nome="Org", cor_primaria="#12ab34", logo=PNG_1X1, logo_mime="image/png"
    )
    html = renderizar_html(dados_amostra(marca))
    assert "--cor: #12ab34" in html and "data:image/png;base64," in html
    assert "#12ab34" in montar_contexto(dados_amostra(marca))["graficos"]["consumo_postos"]


def test_cor_invalida_e_logo_de_tipo_nao_suportado_sao_ignorados() -> None:
    marca = MarcaOrganizacao(
        nome="Org", cor_primaria="red;}</style><script>", logo=b"<svg/>", logo_mime="image/svg+xml"
    )
    html = renderizar_html(dados_amostra(marca))
    assert "<script>" not in html and "--cor: #1f4e79" in html
    assert "data:image/svg" not in html


def test_nome_da_organizacao_e_escapado() -> None:
    marca = MarcaOrganizacao(nome='<b>X</b>" Ltda')
    html = renderizar_html(dados_amostra(marca))
    assert "<b>X</b>" not in html and "&lt;b&gt;X&lt;/b&gt;" in html


def test_dado_ausente_vira_travessao_e_nao_e_estimado() -> None:
    dados = dados_amostra()
    resultado: dict[str, Any] = {**dados.resultado, "indicadores": {}, "acl": None}
    texto = " ".join(_paginas(renderizar_pdf(replace(dados, resultado=resultado))))
    assert "Custo médio (R$/MWh) — — — —" in texto


def test_sem_achados_e_sem_responsavel() -> None:
    dados = dados_amostra(MarcaOrganizacao(nome="Org"))
    resultado: dict[str, Any] = {**dados.resultado, "achados": [], "acl": None}
    texto = " ".join(_paginas(renderizar_pdf(replace(dados, resultado=resultado))))
    assert "Nenhum achado identificado" in texto and "Responsável técnico: —" in texto


def test_recurso_externo_e_bloqueado_na_renderizacao() -> None:
    from app.reports.builder import _BuscadorRestrito

    with pytest.raises(ValueError, match="bloqueado"):
        _BuscadorRestrito().fetch("file:///etc/passwd")
    with pytest.raises(ValueError, match="disallowed"):
        _BuscadorRestrito().fetch("http://169.254.169.254/")


def test_contexto_e_deterministico_para_o_mesmo_snapshot() -> None:
    dados: DadosRelatorio = replace(dados_amostra(), gerado_em=datetime(2026, 1, 1, tzinfo=UTC))
    assert renderizar_html(dados) == renderizar_html(dados)
