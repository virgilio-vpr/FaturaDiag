from __future__ import annotations

from collections.abc import AsyncIterator
from io import BytesIO

import httpx
import pypdfium2 as pdfium
import pytest
from app.db import SessionLocal
from app.db.models import Arquivo, AuditLog, Fatura
from app.main import app
from sqlalchemy import func, select
from tests.integration.conftest import FaturasEnv


def make_pdf(paginas: int = 1, marca: int = 0) -> bytes:
    document = pdfium.PdfDocument.new()
    for _ in range(paginas):
        document.new_page(200 + marca, 200)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _files(content: bytes, name: str = "../../etc/fatura.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"arquivo": (name, content, "application/pdf")}


@pytest.mark.anyio
async def test_upload_creates_fatura_and_stores_file(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    response = await client.post(
        "/api/v1/faturas",
        headers=faturas_env.headers["analista_a"],
        files=_files(make_pdf()),
        data={"unidade_id": str(faturas_env.unidade_a)},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "ENVIADA"
    with SessionLocal() as session:
        arquivo = session.scalars(
            select(Arquivo).where(Arquivo.organizacao_id == faturas_env.org_a)
        ).one()
        assert arquivo.nome_original is None
        assert ".." not in arquivo.storage_key
        assert faturas_env.storage.exists(arquivo.storage_key)
        audit = session.scalar(
            select(func.count()).where(
                AuditLog.organizacao_id == faturas_env.org_a, AuditLog.acao == "FATURA_ENVIADA"
            )
        )
        assert audit == 1


@pytest.mark.anyio
async def test_duplicate_content_returns_same_fatura(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    pdf = make_pdf()
    first = await client.post(
        "/api/v1/faturas", headers=faturas_env.headers["analista_a"], files=_files(pdf)
    )
    second = await client.post(
        "/api/v1/faturas", headers=faturas_env.headers["analista_a"], files=_files(pdf)
    )
    assert first.json()["id"] == second.json()["id"]
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(Fatura)
            .where(Fatura.organizacao_id == faturas_env.org_a)
        )
        assert total == 1


@pytest.mark.anyio
async def test_same_content_in_other_tenant_is_independent(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    pdf = make_pdf()
    a = await client.post(
        "/api/v1/faturas", headers=faturas_env.headers["analista_a"], files=_files(pdf)
    )
    b = await client.post(
        "/api/v1/faturas", headers=faturas_env.headers["analista_b"], files=_files(pdf)
    )
    assert a.status_code == b.status_code == 202
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.anyio
async def test_idempotency_key_returns_original(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = {**faturas_env.headers["analista_a"], "Idempotency-Key": "chave-1"}
    first = await client.post("/api/v1/faturas", headers=headers, files=_files(make_pdf(marca=1)))
    second = await client.post("/api/v1/faturas", headers=headers, files=_files(make_pdf(marca=2)))
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.anyio
async def test_invalid_uploads_are_rejected(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    wrong = await client.post("/api/v1/faturas", headers=headers, files=_files(b"MZ\x90 exe"))
    assert wrong.status_code == 415
    pages = await client.post("/api/v1/faturas", headers=headers, files=_files(make_pdf(13)))
    assert pages.status_code == 422


@pytest.mark.anyio
async def test_unit_from_other_tenant_is_not_found(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    response = await client.post(
        "/api/v1/faturas",
        headers=faturas_env.headers["analista_a"],
        files=_files(make_pdf()),
        data={"unidade_id": str(faturas_env.unidade_b)},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_cliente_role_cannot_upload(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    response = await client.post(
        "/api/v1/faturas", headers=faturas_env.headers["cliente_a"], files=_files(make_pdf())
    )
    assert response.status_code == 403
    anonymous = await client.post("/api/v1/faturas", files=_files(make_pdf()))
    assert anonymous.status_code == 401
