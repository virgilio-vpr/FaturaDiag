from __future__ import annotations


def pdf_com_texto(paginas: list[list[str]]) -> bytes:
    """Gera um PDF mínimo (Helvetica) com as linhas de cada página, sem dependências extras."""
    objetos: list[bytes] = []
    n_paginas = len(paginas)
    primeiro_page = 4
    kids = " ".join(f"{primeiro_page + 2 * i} 0 R" for i in range(n_paginas))
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objetos.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_paginas} >>".encode())
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, linhas in enumerate(paginas):
        content_id = primeiro_page + 2 * i + 1
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        partes = ["BT /F1 9 Tf 20 820 Td 11 TL"]
        for linha in linhas:
            seguro = linha.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            partes.append(f"({seguro}) Tj T*")
        partes.append("ET")
        stream = "\n".join(partes).encode("latin-1")
        objetos.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    saida = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for numero, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += f"{numero} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        saida += f"{offset:010d} 00000 n \n".encode()
    saida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(saida)
