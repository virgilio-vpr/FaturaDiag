from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.db import SessionLocal
from app.db.models import Diagnostico, SimulacaoACL
from app.main import app
from app.modules.diagnosticos import service
from httpx import ASGITransport
from sqlalchemy import select
from tests.support.diagnosticos import PARAMETROS, criar_fatura, semear_tarifas

URL = "/api/v1/diagnosticos"
ACL = {
    "entrada": {
        "consumo_mwh_mes": "100",
        "te_cativa_rs_mwh": "300",
        "encargos_rs_mwh": "20",
        "custos_fixos_mes": "1000",
    },
    "cenarios": [
        {"nome": "conservador", "preco_rs_mwh": "280"},
        {"nome": "base", "preco_rs_mwh": "230"},
        {"nome": "otimista", "preco_rs_mwh": "200"},
    ],
}


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


def _corpo(env: Any, fatura_id: Any) -> dict[str, Any]:
    return {"uc_id": str(env.unidade_a), "escopo": "FATURA_UNICA", "fatura_id": str(fatura_id)}


async def _criar(client: httpx.AsyncClient, env: Any, mes: int = 3) -> dict[str, Any]:
    resp = await client.post(
        URL, headers=env.headers["analista_a"], json=_corpo(env, criar_fatura(env, mes))
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _definir_status(diagnostico_id: str, status: str) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            Diagnostico.__table__.update()
            .where(Diagnostico.id == diagnostico_id)
            .values(status=status)
        )


@pytest.mark.anyio
async def test_criacao_idempotente_e_consulta(client: httpx.AsyncClient, env: Any) -> None:
    headers = {**env.headers["analista_a"], "Idempotency-Key": "k-1"}
    corpo = _corpo(env, criar_fatura(env, 3))

    primeira = await client.post(URL, headers=headers, json=corpo)
    segunda = await client.post(URL, headers=headers, json=corpo)
    detalhe = await client.get(f"{URL}/{primeira.json()['id']}", headers=headers)

    assert primeira.status_code == 201 and segunda.status_code == 201
    assert primeira.json()["id"] == segunda.json()["id"]
    dados = detalhe.json()
    assert dados["status"] == "RASCUNHO"
    assert isinstance(dados["economia_anual_estimada"], str)
    assert dados["achados"] and all(isinstance(a["trace"], dict) for a in dados["achados"])
    assert dados["fontes"]["faturas"] == [corpo["fatura_id"]]
    assert dados["parametros_pendentes"] == ["tolerancia_ultrapassagem"]
    with SessionLocal() as session:
        assert len(session.scalars(select(Diagnostico)).all()) == 1


@pytest.mark.anyio
async def test_erros_problem_json(client: httpx.AsyncClient, env: Any) -> None:
    h = env.headers["analista_a"]
    pendente = criar_fatura(env, 4, status="EM_REVISAO")
    incompleta = criar_fatura(env, 5, consumo_ponta_kwh=None)
    de_b = criar_fatura(env, 4, org="b")

    nao_validada = await client.post(URL, headers=h, json=_corpo(env, pendente))
    insuficiente = await client.post(URL, headers=h, json=_corpo(env, incompleta))
    outro_tenant = await client.post(URL, headers=h, json=_corpo(env, de_b))
    sem_fatura = await client.post(URL, headers=h, json=_corpo(env, uuid4()))
    escopo = await client.post(
        URL, headers=h, json={"uc_id": str(env.unidade_a), "escopo": "FATURA_UNICA"}
    )

    assert nao_validada.status_code == 409
    assert insuficiente.status_code == 422
    assert insuficiente.headers["content-type"].startswith("application/problem+json")
    assert insuficiente.json()["errors"][0]["code"] == "insumos_insuficientes"
    assert outro_tenant.status_code == 404
    assert sem_fatura.status_code == 404
    assert escopo.status_code == 422


@pytest.mark.anyio
async def test_cliente_so_le_publicados_e_nao_escreve(client: httpx.AsyncClient, env: Any) -> None:
    diag = await _criar(client, env)
    cliente = env.headers["cliente_a"]

    assert (await client.get(f"{URL}/{diag['id']}", headers=cliente)).status_code == 404
    assert (await client.post(URL, headers=cliente, json=_corpo(env, uuid4()))).status_code == 403
    assert (await client.post(f"{URL}/{diag['id']}/revisar", headers=cliente)).status_code == 403
    assert (
        await client.patch(f"{URL}/{diag['id']}", headers=cliente, json={"notas": "x"})
    ).status_code == 403
    _definir_status(diag["id"], "PUBLICADO")
    assert (await client.get(f"{URL}/{diag['id']}", headers=cliente)).status_code == 200


@pytest.mark.anyio
async def test_isolamento_entre_tenants(client: httpx.AsyncClient, env: Any) -> None:
    diag = await _criar(client, env)
    b = env.headers["analista_b"]

    assert (await client.get(f"{URL}/{diag['id']}", headers=b)).status_code == 404
    assert (await client.post(f"{URL}/{diag['id']}/revisar", headers=b)).status_code == 404
    assert (
        await client.post(f"{URL}/{diag['id']}/simulacoes-acl", headers=b, json=ACL)
    ).status_code == 404
    assert (
        await client.patch(f"{URL}/{diag['id']}", headers=b, json={"notas": "x"})
    ).status_code == 404


@pytest.mark.anyio
async def test_notas_e_revisao(client: httpx.AsyncClient, env: Any) -> None:
    h = env.headers["analista_a"]
    diag = await _criar(client, env)

    patch = await client.patch(f"{URL}/{diag['id']}", headers=h, json={"notas": "conferido"})
    revisado = await client.post(f"{URL}/{diag['id']}/revisar", headers=h)
    de_novo = await client.post(f"{URL}/{diag['id']}/revisar", headers=h)

    assert patch.json()["notas"] == "conferido"
    assert revisado.status_code == 200
    assert revisado.json()["status"] == "REVISADO"
    assert revisado.json()["revisado_por"] and revisado.json()["revisado_em"]
    assert de_novo.status_code == 409
    _definir_status(diag["id"], "PUBLICADO")
    assert (
        await client.patch(f"{URL}/{diag['id']}", headers=h, json={"notas": "y"})
    ).status_code == 409


@pytest.mark.anyio
async def test_simulacao_demanda_pura(client: httpx.AsyncClient, env: Any) -> None:
    h = env.headers["analista_a"]
    meses = ["280"] * 12
    verde = await client.post(
        "/api/v1/simulacoes/demanda",
        headers=h,
        json={
            "modalidade": "VERDE",
            "dm_ponta_kw": meses,
            "dm_fora_ponta_kw": ["300"] * 12,
            "tarifa_unica_rs_kw": "40",
            "dc_atual_kw": "500",
        },
    )
    azul = await client.post(
        "/api/v1/simulacoes/demanda",
        headers=h,
        json={
            "modalidade": "AZUL",
            "dm_ponta_kw": meses,
            "dm_fora_ponta_kw": ["300"] * 12,
            "tarifa_ponta_rs_kw": "60",
            "tarifa_fora_ponta_rs_kw": "20",
        },
    )
    sem_tarifa = await client.post(
        "/api/v1/simulacoes/demanda",
        headers=h,
        json={"modalidade": "VERDE", "dm_ponta_kw": meses, "dm_fora_ponta_kw": meses},
    )
    com_float = await client.post(
        "/api/v1/simulacoes/demanda",
        headers=h,
        json={
            "modalidade": "VERDE",
            "dm_ponta_kw": meses,
            "dm_fora_ponta_kw": meses,
            "tarifa_unica_rs_kw": 40.5,
        },
    )

    assert verde.status_code == 200, verde.text
    resultado = verde.json()["resultado"]["resultado"]
    assert resultado["dc_otima_kw"] == "286"
    assert resultado["economia_anual"] is not None
    assert azul.status_code == 200 and "ponta" in azul.json()["resultado"]["resultado"]
    assert sem_tarifa.status_code == 422
    assert com_float.status_code == 422
    assert (
        await client.post("/api/v1/simulacoes/demanda", headers=env.headers["cliente_a"], json={})
    ).status_code == 403


@pytest.mark.anyio
async def test_simulacao_acl_pura_nao_persiste(client: httpx.AsyncClient, env: Any) -> None:
    h = env.headers["analista_a"]

    ok = await client.post("/api/v1/simulacoes/acl", headers=h, json=ACL)
    negativo = await client.post(
        "/api/v1/simulacoes/acl",
        headers=h,
        json={**ACL, "entrada": {**ACL["entrada"], "consumo_mwh_mes": "-1"}},
    )

    assert ok.status_code == 200, ok.text
    resultado = ok.json()["resultado"]
    assert len(resultado["cenarios"]) == 3 and resultado["break_even_rs_mwh"]
    assert negativo.status_code == 422
    with SessionLocal() as session:
        assert session.scalars(select(SimulacaoACL)).all() == []


@pytest.mark.anyio
async def test_simulacao_acl_persistida(client: httpx.AsyncClient, env: Any) -> None:
    h = env.headers["analista_a"]
    diag = await _criar(client, env)

    resp = await client.post(f"{URL}/{diag['id']}/simulacoes-acl", headers=h, json=ACL)
    invalida = await client.post(
        f"{URL}/{diag['id']}/simulacoes-acl",
        headers=h,
        json={**ACL, "cenarios": [{"nome": "x", "preco_rs_mwh": "1"}]},
    )
    detalhe = await client.get(f"{URL}/{diag['id']}", headers=h)

    assert resp.status_code == 201, resp.text
    assert {s["cenario"] for s in resp.json()} == {"CONSERVADOR", "BASE", "OTIMISTA"}
    assert invalida.status_code == 422
    assert len(detalhe.json()["simulacoes_acl"]) == 3
    _definir_status(diag["id"], "STALE")
    assert (
        await client.post(f"{URL}/{diag['id']}/simulacoes-acl", headers=h, json=ACL)
    ).status_code == 409
