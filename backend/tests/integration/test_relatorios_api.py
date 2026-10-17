from __future__ import annotations

import io
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pdfplumber
import pytest
from app.db import SessionLocal
from app.db.models import Arquivo, AuditLog, Diagnostico, Organizacao, Relatorio
from app.main import app
from app.modules.diagnosticos import service
from app.reports.builder import RESSALVA
from httpx import ASGITransport
from sqlalchemy import select
from tests.support.diagnosticos import PARAMETROS, criar_fatura, semear_tarifas

URL = "/api/v1/diagnosticos"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
def env(faturas_env, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(service, "carregar_parametros_regulatorios", lambda *_a, **_k: PARAMETROS)
    semear_tarifas(faturas_env.distribuidora)
    yield faturas_env


def _status(diagnostico_id: str, status: str) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            Diagnostico.__table__.update()
            .where(Diagnostico.id == UUID(diagnostico_id))
            .values(status=status)
        )


async def _diagnosticar(client: httpx.AsyncClient, env: Any) -> str:
    resp = await client.post(
        URL,
        headers=env.headers["analista_a"],
        json={
            "uc_id": str(env.unidade_a),
            "escopo": "FATURA_UNICA",
            "fatura_id": str(criar_fatura(env, 3)),
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _texto(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return " ".join(" ".join((p.extract_text() or "").split()) for p in doc.pages)


@pytest.mark.anyio
async def test_gera_versiona_audita_e_baixa(client: httpx.AsyncClient, env: Any) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            Organizacao.__table__.update()
            .where(Organizacao.id == env.org_a)
            .values(responsavel_tecnico_nome="Eng. Teste", cor_primaria="#12ab34")
        )
    diagnostico = await _diagnosticar(client, env)
    headers = env.headers["analista_a"]

    primeiro = await client.post(f"{URL}/{diagnostico}/relatorio", headers=headers)
    segundo = await client.post(f"{URL}/{diagnostico}/relatorio", headers=headers)
    assert primeiro.status_code == 202, primeiro.text
    assert (primeiro.json()["versao"], segundo.json()["versao"]) == (1, 2)
    assert primeiro.json()["id"] != segundo.json()["id"]

    baixado = await client.get(
        f"/api/v1/relatorios/{primeiro.json()['id']}/download", headers=headers
    )
    assert baixado.status_code == 200
    assert baixado.headers["content-type"] == "application/pdf"
    assert baixado.content.startswith(b"%PDF")
    texto = _texto(baixado.content)
    assert " ".join(RESSALVA.split()) in texto and "Eng. Teste" in texto
    assert "Cliente A" in texto

    with SessionLocal() as session:
        arquivos = session.scalars(select(Arquivo).where(Arquivo.mime == "application/pdf")).all()
        assert len(arquivos) == 2
        acoes = session.scalars(
            select(AuditLog.acao).where(AuditLog.organizacao_id == env.org_a)
        ).all()
        assert acoes.count("relatorio.gerar") == 2


@pytest.mark.anyio
async def test_diagnostico_stale_ou_inexistente_e_papeis(
    client: httpx.AsyncClient, env: Any
) -> None:
    diagnostico = await _diagnosticar(client, env)
    url = f"{URL}/{diagnostico}/relatorio"
    assert (await client.post(url, headers=env.headers["cliente_a"])).status_code == 403
    assert (await client.post(url, headers=env.headers["analista_b"])).status_code == 404
    assert (
        await client.post(f"{URL}/{uuid4()}/relatorio", headers=env.headers["analista_a"])
    ).status_code == 404
    _status(diagnostico, "STALE")
    assert (await client.post(url, headers=env.headers["analista_a"])).status_code == 409
    with SessionLocal() as session:
        assert session.scalars(select(Relatorio)).first() is None


@pytest.mark.anyio
async def test_download_cliente_so_publicado_e_isolamento_de_tenant(
    client: httpx.AsyncClient, env: Any
) -> None:
    diagnostico = await _diagnosticar(client, env)
    gerado = await client.post(f"{URL}/{diagnostico}/relatorio", headers=env.headers["analista_a"])
    download = f"/api/v1/relatorios/{gerado.json()['id']}/download"

    assert (await client.get(download, headers=env.headers["cliente_a"])).status_code == 404
    assert (await client.get(download, headers=env.headers["analista_b"])).status_code == 404
    assert (await client.get(download)).status_code == 401
    _status(diagnostico, "PUBLICADO")
    assert (await client.get(download, headers=env.headers["cliente_a"])).status_code == 200
    assert (
        await client.get(
            f"/api/v1/relatorios/{uuid4()}/download", headers=env.headers["analista_a"]
        )
    ).status_code == 404
