from __future__ import annotations

from io import BytesIO

import pytest
from app.integrations.pdf import (
    OrigemDocumento,
    classificar_origem,
    extrair_texto_pdf,
    rasterizar_pdf,
)
from PIL import Image
from tests.support.pdf import pdf_com_texto

LINHAS_FATURA = [
    "DISTRIBUIDORA EXEMPLO - NOTA FISCAL / FATURA DE ENERGIA ELETRICA",
    "Demanda Contratada Ponta 500 kW   Demanda Fora Ponta 600 kW",
    "Consumo Ponta 12.345,000 kWh  Consumo Fora Ponta 98.765,000 kWh",
] * 4


def test_extrai_texto_por_pagina() -> None:
    leitura = extrair_texto_pdf(pdf_com_texto([LINHAS_FATURA, ["Segunda pagina kWh"]]))
    assert leitura.paginas == 2
    assert "Demanda Contratada" in leitura.texto_por_pagina[0]
    assert "Segunda pagina" in leitura.texto_por_pagina[1]
    assert leitura.chars_por_pagina == pytest.approx(
        sum(len(t) for t in leitura.texto_por_pagina) / 2
    )


def test_pdf_com_texto_e_termos_e_nativo() -> None:
    leitura = extrair_texto_pdf(pdf_com_texto([LINHAS_FATURA]))
    assert classificar_origem("application/pdf", leitura) is OrigemDocumento.PDF_NATIVO


def test_pdf_com_pouco_texto_e_escaneado() -> None:
    leitura = extrair_texto_pdf(pdf_com_texto([["kWh Demanda"]]))
    assert classificar_origem("application/pdf", leitura) is OrigemDocumento.PDF_ESCANEADO


def test_pdf_com_muito_texto_sem_termos_e_escaneado() -> None:
    leitura = extrair_texto_pdf(pdf_com_texto([["lorem ipsum dolor sit amet " * 5] * 8]))
    assert leitura.chars_por_pagina >= 200
    assert classificar_origem("application/pdf", leitura) is OrigemDocumento.PDF_ESCANEADO


def test_imagem_e_classificada_como_imagem() -> None:
    assert classificar_origem("image/png", None) is OrigemDocumento.IMAGEM
    assert classificar_origem("image/jpeg", None) is OrigemDocumento.IMAGEM


def test_rasteriza_paginas_em_dpi_pedido() -> None:
    pdf = pdf_com_texto([LINHAS_FATURA, LINHAS_FATURA])
    imagens = rasterizar_pdf(pdf, dpi=200)
    assert len(imagens) == 2
    largura, altura = Image.open(BytesIO(imagens[0])).size
    assert largura == pytest.approx(595 / 72 * 200, abs=2)
    assert altura == pytest.approx(842 / 72 * 200, abs=2)


def test_dpi_fora_da_faixa_e_rejeitado() -> None:
    with pytest.raises(ValueError):
        rasterizar_pdf(pdf_com_texto([LINHAS_FATURA]), dpi=50)
