from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.db import SessionLocal
from app.db.models import AuditLog, Diagnostico, ParametroRegulatorio
from app.main import app
from app.modules.diagnosticos import service
from app.modules.tarifas.parametros import gravar_parametro_regulatorio, limpar_cache_parametros
from httpx import ASGITransport
from sqlalchemy import delete, select
from tests.support.diagnosticos import PARAMETROS, criar_fatura, semear_tarifas, usuario_id

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


def _status(diagnostico_id: str | UUID) -> str:
    with SessionLocal() as session:
        return session.scalars(
            select(Diagnostico.status).where(Diagnostico.id == UUID(str(diagnostico_id)))
        ).one()


def _publicar(diagnostico_id: str) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            Diagnostico.__table__.update()
            .where(Diagnostico.id == UUID(diagnostico_id))
            .values(status="PUBLICADO")
        )


async def _diagnosticar(client: httpx.AsyncClient, env: Any, fatura_id: UUID) -> str:
    resp = await client.post(
        URL,
        headers=env.headers["analista_a"],
        json={"uc_id": str(env.unidade_a), "escopo": "FATURA_UNICA", "fatura_id": str(fatura_id)},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.anyio
async def test_editar_fatura_marca_apenas_diagnosticos_dependentes_como_stale(
    client: httpx.AsyncClient, env: Any
) -> None:
    h = env.headers["analista_a"]
    fatura = criar_fatura(env, 3)
    outra = criar_fatura(env, 4)
    dependente = await _diagnosticar(client, env, fatura)
    independente = await _diagnosticar(client, env, outra)
    publicado = await _diagnosticar(client, env, fatura)
    _publicar(publicado)

    edicao = await client.put(
        f"/api/v1/faturas/{fatura}/dados", headers=h, json={"dias_faturados": 31}
    )

    assert edicao.status_code == 200, edicao.text
    assert _status(dependente) == "STALE"
    assert _status(publicado) == "STALE"
    assert _status(independente) == "RASCUNHO"
    with SessionLocal() as session:
        eventos = session.scalars(
            select(AuditLog).where(
                AuditLog.acao == "DIAGNOSTICO_STALE", AuditLog.entidade_id == dependente
            )
        ).all()
    assert len(eventos) == 1 and eventos[0].depois["motivo"] == f"fatura:{fatura}"  # type: ignore[index]


@pytest.mark.anyio
async def test_stale_nao_aceita_nova_simulacao_nem_revisao(
    client: httpx.AsyncClient, env: Any
) -> None:
    h = env.headers["analista_a"]
    fatura = criar_fatura(env, 3)
    diagnostico = await _diagnosticar(client, env, fatura)
    await client.put(f"/api/v1/faturas/{fatura}/dados", headers=h, json={"dias_faturados": 31})

    revisao = await client.post(f"{URL}/{diagnostico}/revisar", headers=h)

    assert revisao.status_code == 409
    assert (await client.get(f"{URL}/{diagnostico}", headers=h)).json()["status"] == "STALE"


@pytest.mark.anyio
async def test_contrato_sobreposto_invalida_e_fora_do_periodo_nao(
    client: httpx.AsyncClient, env: Any
) -> None:
    h = env.headers["analista_a"]
    marco = await _diagnosticar(client, env, criar_fatura(env, 3))
    junho = await _diagnosticar(client, env, criar_fatura(env, 6))
    url = f"/api/v1/unidades/{env.unidade_a}/contratos"

    futuro = await client.post(
        url,
        headers=h,
        json={"modalidade": "VERDE", "demanda_unica_kw": "400", "vigencia_inicio": "2026-05-01"},
    )
    assert futuro.status_code == 201, futuro.text
    assert _status(marco) == "RASCUNHO" and _status(junho) == "STALE"

    passado = await client.post(
        url,
        headers=h,
        json={
            "modalidade": "VERDE",
            "demanda_unica_kw": "300",
            "vigencia_inicio": "2026-01-01",
            "vigencia_fim": "2026-04-01",
        },
    )
    assert passado.status_code == 201, passado.text
    assert _status(marco) == "STALE"


@pytest.mark.anyio
async def test_alterar_subgrupo_invalida_mas_apelido_nao(
    client: httpx.AsyncClient, env: Any
) -> None:
    h = env.headers["analista_a"]
    diagnostico = await _diagnosticar(client, env, criar_fatura(env, 3))
    url = f"/api/v1/unidades/{env.unidade_a}"

    apelido = await client.patch(url, headers=h, json={"apelido": "Matriz"})
    igual = await client.patch(url, headers=h, json={"subgrupo": "A4"})
    assert apelido.status_code == 200 and igual.status_code == 200
    assert _status(diagnostico) == "RASCUNHO"

    alterado = await client.patch(url, headers=h, json={"subgrupo": "A3a"})
    assert alterado.status_code == 200, alterado.text
    assert _status(diagnostico) == "STALE"


def _diagnostico_direto(env: Any, periodo_fim: date) -> UUID:
    diagnostico_id = uuid4()
    with SessionLocal.begin() as session:
        session.add(
            Diagnostico(
                id=diagnostico_id,
                organizacao_id=env.org_a,
                uc_id=env.unidade_a,
                escopo="FATURA_UNICA",
                periodo_inicio=periodo_fim,
                periodo_fim=periodo_fim,
                status="REVISADO",
                versao_motor="0.1.0",
                insumos_snapshot={"fontes": {"faturas": []}},
                parametros_snapshot={},
                resultado={},
                economia_mensal_estimada=Decimal(0),
                economia_anual_estimada=Decimal(0),
            )
        )
    return diagnostico_id


def test_parametro_alterado_invalida_diagnosticos_na_vigencia(env: Any) -> None:
    dentro = _diagnostico_direto(env, date(2091, 3, 1))
    antes = _diagnostico_direto(env, date(2089, 3, 1))
    depois = _diagnostico_direto(env, date(2096, 3, 1))
    admin = usuario_id(env.org_a)
    args: dict[str, Any] = {
        "chave": "tolerancia_ultrapassagem",
        "vigencia_inicio": date(2090, 1, 1),
        "vigencia_fim": date(2095, 1, 1),
        "fonte": "teste sintético",
        "status": "VALIDADO",
        "usuario_id": admin,
        "organizacao_id": env.org_a,
        "ip": None,
    }
    try:
        with SessionLocal() as session:
            gravar_parametro_regulatorio(session, valor=0.07, **args)
        assert _status(dentro) == "STALE"
        assert _status(antes) == "REVISADO" and _status(depois) == "REVISADO"

        with SessionLocal.begin() as session:
            session.execute(
                Diagnostico.__table__.update()
                .where(Diagnostico.id == dentro)
                .values(status="REVISADO")
            )
        with SessionLocal() as session:
            gravar_parametro_regulatorio(session, valor=0.07, **args)
        assert _status(dentro) == "REVISADO"

        with SessionLocal() as session:
            gravar_parametro_regulatorio(session, valor=0.06, **args)
        assert _status(dentro) == "STALE"
        assert _status(depois) == "REVISADO"
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(ParametroRegulatorio).where(
                    ParametroRegulatorio.vigencia_inicio == date(2090, 1, 1)
                )
            )
        limpar_cache_parametros()
