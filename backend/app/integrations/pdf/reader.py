from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

import pdfplumber
import pypdfium2 as pdfium

MIN_CHARS_POR_PAGINA = 200
TERMOS_FATURA = ("kwh", "demanda", "fatura", "nota fiscal")
DPI_MIN, DPI_MAX = 200, 300


class OrigemDocumento(StrEnum):
    PDF_NATIVO = "PDF_NATIVO"
    PDF_ESCANEADO = "PDF_ESCANEADO"
    IMAGEM = "IMAGEM"


@dataclass(frozen=True)
class LeituraPdf:
    texto_por_pagina: list[str]

    @property
    def paginas(self) -> int:
        return len(self.texto_por_pagina)

    @property
    def texto(self) -> str:
        return "\n".join(self.texto_por_pagina)

    @property
    def chars_por_pagina(self) -> float:
        if not self.texto_por_pagina:
            return 0.0
        return sum(len(t) for t in self.texto_por_pagina) / len(self.texto_por_pagina)


def extrair_texto_pdf(data: bytes) -> LeituraPdf:
    with pdfplumber.open(BytesIO(data)) as pdf:
        return LeituraPdf([(page.extract_text() or "") for page in pdf.pages])


def classificar_origem(mime: str, leitura: LeituraPdf | None) -> OrigemDocumento:
    if mime != "application/pdf" or leitura is None:
        return OrigemDocumento.IMAGEM
    if leitura.chars_por_pagina >= MIN_CHARS_POR_PAGINA and _tem_termos(leitura.texto):
        return OrigemDocumento.PDF_NATIVO
    return OrigemDocumento.PDF_ESCANEADO


def rasterizar_pdf(data: bytes, *, dpi: int = 200) -> list[bytes]:
    if not DPI_MIN <= dpi <= DPI_MAX:
        raise ValueError(f"dpi deve estar entre {DPI_MIN} e {DPI_MAX}.")
    document = pdfium.PdfDocument(data)
    try:
        paginas: list[bytes] = []
        for page in document:
            bitmap = page.render(scale=dpi / 72)
            buffer = BytesIO()
            bitmap.to_pil().convert("RGB").save(buffer, format="PNG")
            paginas.append(buffer.getvalue())
        return paginas
    finally:
        document.close()


def _tem_termos(texto: str) -> bool:
    normalizado = unicodedata.normalize("NFKD", texto.casefold())
    normalizado = re.sub(r"[\u0300-\u036f]", "", normalizado)
    return any(termo in normalizado for termo in TERMOS_FATURA)
