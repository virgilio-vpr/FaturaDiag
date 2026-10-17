from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import filetype
import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError
from pypdfium2 import PdfiumError

pillow_heif.register_heif_opener()

PDF_MIME = "application/pdf"
JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
HEIC_MIMES = {"image/heic", "image/heif"}
EXTENSOES = {PDF_MIME: "pdf", JPEG_MIME: "jpg", PNG_MIME: "png"}


class ArquivoInvalidoError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ArquivoValidado:
    mime: str
    extensao: str
    conteudo: bytes


def validar_arquivo(data: bytes, *, max_bytes: int, max_paginas: int) -> ArquivoValidado:
    if not data:
        raise ArquivoInvalidoError("Arquivo vazio.", 422)
    if len(data) > max_bytes:
        raise ArquivoInvalidoError("Arquivo excede o tamanho máximo permitido.", 413)

    kind = filetype.guess(data)
    mime = kind.mime if kind is not None else None
    if mime == PDF_MIME:
        _validar_pdf(data, max_paginas)
        return ArquivoValidado(PDF_MIME, "pdf", data)
    if mime in (JPEG_MIME, PNG_MIME):
        _validar_imagem(data)
        return ArquivoValidado(mime, EXTENSOES[mime], data)
    if mime in HEIC_MIMES:
        return ArquivoValidado(JPEG_MIME, "jpg", _heic_para_jpeg(data))
    raise ArquivoInvalidoError("Tipo de arquivo não suportado. Envie PDF, JPG, PNG ou HEIC.", 415)


def _validar_pdf(data: bytes, max_paginas: int) -> None:
    try:
        document = pdfium.PdfDocument(data)
        paginas = len(document)
        document.close()
    except PdfiumError as error:
        raise ArquivoInvalidoError("PDF corrompido ou protegido.", 422) from error
    if paginas < 1 or paginas > max_paginas:
        raise ArquivoInvalidoError(f"O PDF deve ter entre 1 e {max_paginas} páginas.", 422)


def _validar_imagem(data: bytes) -> None:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ArquivoInvalidoError("Imagem corrompida ou inválida.", 422) from error


def _heic_para_jpeg(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            output = BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=92)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ArquivoInvalidoError("Imagem HEIC corrompida ou inválida.", 422) from error
    return output.getvalue()
