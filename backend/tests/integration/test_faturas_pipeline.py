from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.db import SessionLocal
from app.db.models import AuditLog, Extracao, Fatura, FaturaItem, UnidadeConsumidora
from app.integrations.llm.base import LLMPermanentError
from app.main import app
from sqlalchemy import func, select
from tests.integration.conftest import FaturasEnv
from tests.integration.test_faturas_upload import _files, make_pdf
from tests.support.extracao import campo, fatura_extraida_dict


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _codigo_uc(env: FaturasEnv) -> str:
    with SessionLocal() as session:
        uc = session.get(UnidadeConsumidora, env.unidade_a)
        assert uc is not None
        return uc.codigo_uc


async def _enviar(
    client: httpx.AsyncClient, env: FaturasEnv, *, marca: int = 0, resposta: Any = None
) -> UUID:
    env.llm["resposta"] = (
        resposta if resposta is not None else fatura_extraida_dict(codigo_uc=campo(_codigo_uc(env)))
    )
    response = await client.post(
        "/api/v1/faturas",
        headers=env.headers["analista_a"],
        files=_files(make_pdf(marca=marca)),
        data={"unidade_id": str(env.unidade_a)},
    )
    assert response.status_code == 202
    return UUID(response.json()["id"])


@pytest.mark.anyio
async def test_upload_runs_pipeline_and_persists_extraction(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    fatura_id = await _enviar(client, faturas_env)
    response = await client.get(
        f"/api/v1/faturas/{fatura_id}", headers=faturas_env.headers["analista_a"]
    )
    body = response.json()
    assert body["status"] == "EXTRAIDA"
    assert body["valor_total"] == "1000.00"
    assert body["mes_referencia"] == "2026-03-01"
    assert body["codigo_uc"] == _codigo_uc(faturas_env)
    assert len(body["itens"]) == 2
    assert not [a for a in body["alertas"] if a["severidade"] == "BLOQUEANTE"]
    with SessionLocal() as session:
        extracao = session.scalars(select(Extracao).where(Extracao.fatura_id == fatura_id)).one()
        assert extracao.provider == "fake"
        assert extracao.custo_estimado >= 0
        acoes = session.scalars(
            select(AuditLog.depois).where(
                AuditLog.organizacao_id == faturas_env.org_a, AuditLog.acao == "FATURA_STATUS"
            )
        ).all()
        assert [a["status"] for a in acoes if a] == ["EXTRAINDO", "EXTRAIDA"]


@pytest.mark.anyio
async def test_extraction_failure_marks_falha_extracao(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    fatura_id = await _enviar(client, faturas_env, resposta=LLMPermanentError("falhou"))
    body = (
        await client.get(f"/api/v1/faturas/{fatura_id}", headers=faturas_env.headers["analista_a"])
    ).json()
    assert body["status"] == "FALHA_EXTRACAO"
    assert body["alertas"][0]["codigo"] == "FALHA_EXTRACAO"
    assert body["alertas"][0]["severidade"] == "BLOQUEANTE"


@pytest.mark.anyio
async def test_tenant_isolation_and_roles(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    fatura_id = await _enviar(client, faturas_env)
    url = f"/api/v1/faturas/{fatura_id}"
    other = faturas_env.headers["analista_b"]
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.get(f"{url}/arquivo", headers=other)).status_code == 404
    assert (await client.put(f"{url}/dados", headers=other, json={})).status_code == 404
    assert (await client.post(f"{url}/validar", headers=other)).status_code == 404
    assert (await client.post(f"{url}/reextrair", headers=other)).status_code == 404
    assert (await client.get("/api/v1/faturas", headers=other)).json() == []

    cliente = faturas_env.headers["cliente_a"]
    assert (await client.get(url, headers=cliente)).status_code == 200
    assert len((await client.get("/api/v1/faturas", headers=cliente)).json()) == 1
    assert (await client.put(f"{url}/dados", headers=cliente, json={})).status_code == 403
    assert (await client.post(f"{url}/validar", headers=cliente)).status_code == 403
    assert (await client.post(f"{url}/reextrair", headers=cliente)).status_code == 403


@pytest.mark.anyio
async def test_download_original_file(client: httpx.AsyncClient, faturas_env: FaturasEnv) -> None:
    fatura_id = await _enviar(client, faturas_env)
    response = await client.get(
        f"/api/v1/faturas/{fatura_id}/arquivo", headers=faturas_env.headers["analista_a"]
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"%PDF")


@pytest.mark.anyio
async def test_validation_requires_no_blocking_alerts(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    fatura_id = await _enviar(client, faturas_env)
    url = f"/api/v1/faturas/{fatura_id}"

    edited = await client.put(f"{url}/dados", headers=headers, json={"valor_total": "2500.00"})
    assert edited.status_code == 200
    assert edited.json()["status"] == "EM_REVISAO"
    assert any(a["severidade"] == "BLOQUEANTE" for a in edited.json()["alertas"])

    blocked = await client.post(f"{url}/validar", headers=headers)
    assert blocked.status_code == 422
    assert blocked.json()["errors"]

    fixed = await client.put(f"{url}/dados", headers=headers, json={"valor_total": "1000.00"})
    assert fixed.status_code == 200
    ok = await client.post(f"{url}/validar", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["status"] == "VALIDADA"
    assert ok.json()["validada_em"] is not None
    with SessionLocal() as session:
        fatura = session.get(Fatura, fatura_id)
        assert fatura is not None
        assert fatura.validada_por is not None


@pytest.mark.anyio
async def test_invalid_transitions_return_409(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    fatura_id = await _enviar(client, faturas_env)
    url = f"/api/v1/faturas/{fatura_id}"
    assert (await client.post(f"{url}/validar", headers=headers)).status_code == 200
    assert (await client.post(f"{url}/validar", headers=headers)).status_code == 409
    assert (await client.post(f"{url}/reextrair", headers=headers)).status_code == 409

    edited = await client.put(f"{url}/dados", headers=headers, json={"dias_faturados": 31})
    assert edited.status_code == 200
    assert edited.json()["status"] == "EM_REVISAO"
    assert edited.json()["validada_em"] is not None


@pytest.mark.anyio
async def test_edit_replaces_items_and_audits(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    fatura_id = await _enviar(client, faturas_env)
    itens = [{"descricao": "Total", "categoria": "OUTROS", "valor": "1000.00"}]
    response = await client.put(
        f"/api/v1/faturas/{fatura_id}/dados", headers=headers, json={"itens": itens}
    )
    assert response.status_code == 200
    assert [i["descricao"] for i in response.json()["itens"]] == ["Total"]
    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(FaturaItem)
                .where(FaturaItem.fatura_id == fatura_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).where(
                    AuditLog.organizacao_id == faturas_env.org_a,
                    AuditLog.acao == "FATURA_DADOS_EDITADOS",
                )
            )
            == 1
        )
    bad = await client.put(
        f"/api/v1/faturas/{fatura_id}/dados", headers=headers, json={"subgrupo": "B3"}
    )
    assert bad.status_code == 422


@pytest.mark.anyio
async def test_reextract_creates_new_extraction(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    fatura_id = await _enviar(client, faturas_env)
    faturas_env.llm["resposta"] = fatura_extraida_dict(
        codigo_uc=campo(_codigo_uc(faturas_env)), valor_total=campo("1000.00")
    )
    response = await client.post(f"/api/v1/faturas/{fatura_id}/reextrair", headers=headers)
    assert response.status_code == 202
    body = (await client.get(f"/api/v1/faturas/{fatura_id}", headers=headers)).json()
    assert body["status"] == "EXTRAIDA"
    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Extracao).where(Extracao.fatura_id == fatura_id)
            )
            == 2
        )


@pytest.mark.anyio
async def test_duplicate_month_is_flagged_not_crashing(
    client: httpx.AsyncClient, faturas_env: FaturasEnv
) -> None:
    headers = faturas_env.headers["analista_a"]
    await _enviar(client, faturas_env, marca=0)
    second = await _enviar(client, faturas_env, marca=5)
    body = (await client.get(f"/api/v1/faturas/{second}", headers=headers)).json()
    assert body["status"] == "EXTRAIDA"
    assert body["mes_referencia"] is None
    assert any(a["codigo"] == "DUPLICADA" for a in body["alertas"])
    conflict = await client.put(
        f"/api/v1/faturas/{second}/dados", headers=headers, json={"mes_referencia": "2026-03-15"}
    )
    assert conflict.status_code == 409
