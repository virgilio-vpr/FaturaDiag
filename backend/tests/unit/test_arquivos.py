from __future__ import annotations

from io import BytesIO

import pytest
from app.modules.faturas.arquivos import ArquivoInvalidoError, validar_arquivo
from PIL import Image


def _pdf(paginas: int = 1) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    for _ in range(paginas):
        document.new_page(200, 200)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _image(fmt: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format=fmt)
    return buffer.getvalue()


def test_accepts_pdf_jpg_png() -> None:
    assert validar_arquivo(_pdf(), max_bytes=10_000_000, max_paginas=12).mime == "application/pdf"
    assert (
        validar_arquivo(_image("JPEG"), max_bytes=10_000_000, max_paginas=12).mime == "image/jpeg"
    )
    assert validar_arquivo(_image("PNG"), max_bytes=10_000_000, max_paginas=12).mime == "image/png"


def test_heic_is_converted_to_jpeg() -> None:
    import pillow_heif

    pillow_heif.register_heif_opener()
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="HEIF")
    result = validar_arquivo(buffer.getvalue(), max_bytes=10_000_000, max_paginas=12)
    assert result.mime == "image/jpeg"
    assert result.conteudo[:3] == b"\xff\xd8\xff"


def test_rejects_wrong_magic_bytes_even_with_pdf_name() -> None:
    with pytest.raises(ArquivoInvalidoError) as error:
        validar_arquivo(b"MZ\x90\x00 not a pdf", max_bytes=1000, max_paginas=12)
    assert error.value.status_code == 415


def test_rejects_too_large() -> None:
    with pytest.raises(ArquivoInvalidoError) as error:
        validar_arquivo(_pdf(), max_bytes=10, max_paginas=12)
    assert error.value.status_code == 413


def test_rejects_too_many_pages() -> None:
    with pytest.raises(ArquivoInvalidoError) as error:
        validar_arquivo(_pdf(3), max_bytes=10_000_000, max_paginas=2)
    assert error.value.status_code == 422


def test_rejects_corrupt_pdf() -> None:
    with pytest.raises(ArquivoInvalidoError):
        validar_arquivo(b"%PDF-1.7\ncorrompido", max_bytes=10_000_000, max_paginas=12)


def test_rejects_empty() -> None:
    with pytest.raises(ArquivoInvalidoError):
        validar_arquivo(b"", max_bytes=10_000_000, max_paginas=12)
