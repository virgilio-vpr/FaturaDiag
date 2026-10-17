from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import (
    AuditLog,
    AuthSession,
    Cliente,
    ContratoDemanda,
    Distribuidora,
    Organizacao,
    UnidadeConsumidora,
    Usuario,
)
from app.main import app
from app.modules.auth.security import create_token
from sqlalchemy import delete, select


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
def unidade_context() -> Iterator[dict[str, UUID | str]]:
    organization_a_id, organization_b_id = uuid4(), uuid4()
    client_a_id, client_b_id = uuid4(), uuid4()
    distributor_id = uuid4()
    actor_specs = {
        "admin_a": (organization_a_id, "ADMIN"),
        "analyst_a": (organization_a_id, "ANALISTA"),
        "client_user_a": (organization_a_id, "CLIENTE"),
        "admin_b": (organization_b_id, "ADMIN"),
    }
    user_ids = {name: uuid4() for name in actor_specs}
    auth_session_ids = {name: uuid4() for name in actor_specs}
    settings = Settings()

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Organizacao(id=organization_a_id, nome=f"UC Tenant A {organization_a_id}"),
                Organizacao(id=organization_b_id, nome=f"UC Tenant B {organization_b_id}"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Usuario(
                    id=user_ids[name],
                    organizacao_id=organization_id,
                    email=f"{user_ids[name].hex}@example.com",
                    nome=name,
                    senha_hash="unused",
                    papel=role,
                )
                for name, (organization_id, role) in actor_specs.items()
            ]
        )
        session.flush()
        session.add_all(
            [
                AuthSession(
                    id=auth_session_ids[name],
                    usuario_id=user_ids[name],
                    expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
                )
                for name in actor_specs
            ]
        )
        session.add_all(
            [
                Cliente(
                    id=client_a_id,
                    organizacao_id=organization_a_id,
                    razao_social="Cliente A",
                ),
                Cliente(
                    id=client_b_id,
                    organizacao_id=organization_b_id,
                    razao_social="Cliente B",
                ),
                Distribuidora(
                    id=distributor_id,
                    sigla=f"TEST_{distributor_id.hex[:8]}",
                    nome="Distribuidora de teste",
                    ufs=["SP"],
                ),
            ]
        )

    tokens = {
        name: create_token(
            user_id=user_ids[name],
            session_id=auth_session_ids[name],
            version=0,
            token_type="access",
            settings=settings,
        )
        for name in actor_specs
    }
    yield {
        "organization_a_id": organization_a_id,
        "organization_b_id": organization_b_id,
        "client_a_id": client_a_id,
        "client_b_id": client_b_id,
        "distributor_id": distributor_id,
        "admin_a_token": tokens["admin_a"],
        "analyst_a_token": tokens["analyst_a"],
        "client_user_a_token": tokens["client_user_a"],
        "admin_b_token": tokens["admin_b"],
        "admin_a_id": user_ids["admin_a"],
    }

    with SessionLocal.begin() as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(
            delete(ContratoDemanda).where(
                ContratoDemanda.uc_id.in_(
                    select(UnidadeConsumidora.id).where(
                        UnidadeConsumidora.organizacao_id.in_(
                            [organization_a_id, organization_b_id]
                        )
                    )
                )
            )
        )
        session.execute(
            delete(UnidadeConsumidora).where(
                UnidadeConsumidora.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(
            delete(Cliente).where(
                Cliente.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(
            delete(AuthSession).where(AuthSession.id.in_(list(auth_session_ids.values())))
        )
        session.execute(delete(Usuario).where(Usuario.id.in_(list(user_ids.values()))))
        session.execute(delete(Distribuidora).where(Distribuidora.id == distributor_id))
        session.execute(
            delete(Organizacao).where(Organizacao.id.in_([organization_a_id, organization_b_id]))
        )


def unit_payload(
    distributor_id: UUID,
    *,
    subgrupo: str = "A4",
    tipo_rede: str = "AEREA",
) -> dict[str, object]:
    return {
        "distribuidora_id": str(distributor_id),
        "codigo_uc": f"UC-{uuid4().hex[:12]}",
        "apelido": "Unidade de teste",
        "uf": "SP",
        "municipio": "Campinas",
        "subgrupo": subgrupo,
        "tipo_rede": tipo_rede,
        "ambiente": "CATIVO",
        "tensao_kv": "13.800",
    }


@pytest.mark.anyio
async def test_customer_unit_and_green_contract_are_created(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
) -> None:
    headers = {"Authorization": f"Bearer {unidade_context['admin_a_token']}"}
    response = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers,
        json=unit_payload(unidade_context["distributor_id"]),
    )

    assert response.status_code == 201
    unit = response.json()
    assert unit["subgrupo"] == "A4"
    assert unit["tipo_rede"] == "AEREA"

    contract_response = await client.post(
        f"/api/v1/unidades/{unit['id']}/contratos",
        headers=headers,
        json={
            "modalidade": "VERDE",
            "demanda_unica_kw": "30",
            "vigencia_inicio": "2026-01-01",
        },
    )
    assert contract_response.status_code == 201
    assert Decimal(contract_response.json()["demanda_unica_kw"]) == Decimal("30.000")

    contracts = await client.get(f"/api/v1/unidades/{unit['id']}/contratos", headers=headers)
    assert contracts.status_code == 200
    assert len(contracts.json()) == 1


@pytest.mark.anyio
async def test_blue_contract_is_valid_for_a1(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
) -> None:
    headers = {"Authorization": f"Bearer {unidade_context['analyst_a_token']}"}
    unit_response = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers,
        json=unit_payload(unidade_context["distributor_id"], subgrupo="A1"),
    )
    assert unit_response.status_code == 201

    contract_response = await client.post(
        f"/api/v1/unidades/{unit_response.json()['id']}/contratos",
        headers=headers,
        json={
            "modalidade": "AZUL",
            "demanda_ponta_kw": "30",
            "demanda_fora_ponta_kw": "45",
            "vigencia_inicio": "2026-01-01",
        },
    )

    assert contract_response.status_code == 201
    assert contract_response.json()["modalidade"] == "AZUL"


@pytest.mark.anyio
async def test_ineligible_green_contract_for_a3_is_rejected(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
) -> None:
    headers = {"Authorization": f"Bearer {unidade_context['admin_a_token']}"}
    unit_response = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers,
        json=unit_payload(unidade_context["distributor_id"], subgrupo="A3"),
    )
    assert unit_response.status_code == 201

    response = await client.post(
        f"/api/v1/unidades/{unit_response.json()['id']}/contratos",
        headers=headers,
        json={
            "modalidade": "VERDE",
            "demanda_unica_kw": "100",
            "vigencia_inicio": "2026-01-01",
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_as_unit_requires_subterranean_network(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
) -> None:
    headers = {"Authorization": f"Bearer {unidade_context['admin_a_token']}"}

    response = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers,
        json=unit_payload(
            unidade_context["distributor_id"],
            subgrupo="AS",
            tipo_rede="AEREA",
        ),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "contract_payload",
    [
        {"modalidade": "VERDE", "vigencia_inicio": "2026-01-01"},
        {
            "modalidade": "AZUL",
            "demanda_ponta_kw": "30",
            "vigencia_inicio": "2026-01-01",
        },
        {
            "modalidade": "VERDE",
            "demanda_unica_kw": "25",
            "vigencia_inicio": "2026-01-01",
        },
    ],
)
@pytest.mark.anyio
async def test_contract_constraints_reject_missing_or_below_minimum_demand(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
    contract_payload: dict[str, str],
) -> None:
    headers = {"Authorization": f"Bearer {unidade_context['admin_a_token']}"}
    unit_response = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers,
        json=unit_payload(unidade_context["distributor_id"]),
    )
    assert unit_response.status_code == 201

    response = await client.post(
        f"/api/v1/unidades/{unit_response.json()['id']}/contratos",
        headers=headers,
        json=contract_payload,
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_unit_routes_are_tenant_scoped_and_client_role_is_forbidden(
    client: httpx.AsyncClient,
    unidade_context: dict[str, UUID | str],
) -> None:
    headers_a = {"Authorization": f"Bearer {unidade_context['admin_a_token']}"}
    headers_b = {"Authorization": f"Bearer {unidade_context['admin_b_token']}"}
    client_headers = {"Authorization": f"Bearer {unidade_context['client_user_a_token']}"}

    user_a_creation = await client.post(
        f"/api/v1/clientes/{unidade_context['client_a_id']}/unidades",
        headers=headers_a,
        json=unit_payload(unidade_context["distributor_id"]),
    )
    user_b_creation = await client.post(
        f"/api/v1/clientes/{unidade_context['client_b_id']}/unidades",
        headers=headers_b,
        json=unit_payload(unidade_context["distributor_id"]),
    )
    assert user_a_creation.status_code == 201
    assert user_b_creation.status_code == 201
    unit_b_id = user_b_creation.json()["id"]

    assert (await client.get(f"/api/v1/unidades/{unit_b_id}", headers=headers_a)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/unidades/{unit_b_id}",
            headers=headers_a,
            json={"apelido": "Tentativa cross-tenant"},
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/clientes/{unidade_context['client_b_id']}/unidades",
            headers=headers_a,
        )
    ).status_code == 404
    assert (await client.get("/api/v1/clientes", headers=client_headers)).status_code == 403
