from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import AuditLog, AuthSession, Cliente, Organizacao, Usuario
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
def client_actors() -> Iterator[tuple[dict[str, tuple[UUID, UUID, str]], tuple[UUID, UUID]]]:
    organization_a_id, organization_b_id = uuid4(), uuid4()
    actor_specs = {
        "admin_a": (organization_a_id, "ADMIN"),
        "analyst_a": (organization_a_id, "ANALISTA"),
        "client_a": (organization_a_id, "CLIENTE"),
        "admin_b": (organization_b_id, "ADMIN"),
    }
    user_ids = {name: uuid4() for name in actor_specs}
    session_ids = {name: uuid4() for name in actor_specs}
    settings = Settings()

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Organizacao(id=organization_a_id, nome=f"Tenant A {organization_a_id}"),
                Organizacao(id=organization_b_id, nome=f"Tenant B {organization_b_id}"),
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
                    id=session_ids[name],
                    usuario_id=user_ids[name],
                    expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
                )
                for name in actor_specs
            ]
        )

    actors = {
        name: (
            organization_id,
            user_ids[name],
            create_token(
                user_id=user_ids[name],
                session_id=session_ids[name],
                version=0,
                token_type="access",
                settings=settings,
            ),
        )
        for name, (organization_id, _) in actor_specs.items()
    }
    yield actors, (organization_a_id, organization_b_id)

    with SessionLocal.begin() as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(
            delete(Cliente).where(
                Cliente.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(delete(AuthSession).where(AuthSession.id.in_(list(session_ids.values()))))
        session.execute(delete(Usuario).where(Usuario.id.in_(list(user_ids.values()))))
        session.execute(
            delete(Organizacao).where(Organizacao.id.in_([organization_a_id, organization_b_id]))
        )


@pytest.mark.anyio
async def test_client_list_requires_authentication() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/clientes")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_customer_crud_search_pagination_and_audit(
    client: httpx.AsyncClient,
    client_actors: tuple[dict[str, tuple[UUID, UUID, str]], tuple[UUID, UUID]],
) -> None:
    actors, _ = client_actors
    admin_headers = {"Authorization": f"Bearer {actors['admin_a'][2]}"}
    created = []
    for name in ("Cliente Alfa", "Cliente Beta", "Cliente Gama"):
        response = await client.post(
            "/api/v1/clientes",
            headers=admin_headers,
            json={"razao_social": name, "observacoes": "Cadastro de teste"},
        )
        assert response.status_code == 201
        created.append(response.json())

    search_response = await client.get(
        "/api/v1/clientes",
        params={"q": "beta"},
        headers=admin_headers,
    )
    assert search_response.status_code == 200
    assert [item["razao_social"] for item in search_response.json()["items"]] == ["Cliente Beta"]

    first_page = await client.get(
        "/api/v1/clientes",
        params={"limit": 2},
        headers=admin_headers,
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    next_cursor = first_page.json()["next_cursor"]
    assert next_cursor is not None
    second_page = await client.get(
        "/api/v1/clientes",
        params={"limit": 2, "cursor": next_cursor},
        headers=admin_headers,
    )
    assert second_page.status_code == 200
    paged_ids = {item["id"] for item in first_page.json()["items"] + second_page.json()["items"]}
    assert paged_ids == {item["id"] for item in created}

    customer_id = UUID(created[0]["id"])
    update_response = await client.patch(
        f"/api/v1/clientes/{customer_id}",
        headers=admin_headers,
        json={"nome_fantasia": "Alfa Atualizado"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["nome_fantasia"] == "Alfa Atualizado"

    delete_response = await client.delete(
        f"/api/v1/clientes/{customer_id}",
        headers=admin_headers,
    )
    assert delete_response.status_code == 204
    assert (
        await client.get(f"/api/v1/clientes/{customer_id}", headers=admin_headers)
    ).status_code == 404
    remaining = await client.get("/api/v1/clientes", headers=admin_headers)
    assert len(remaining.json()["items"]) == 2

    with SessionLocal() as session:
        audit_actions = set(
            session.scalars(
                select(AuditLog.acao).where(
                    AuditLog.organizacao_id == actors["admin_a"][0],
                    AuditLog.entidade == "cliente",
                )
            ).all()
        )
    assert {"CLIENTE_CRIADO", "CLIENTE_ATUALIZADO", "CLIENTE_EXCLUIDO"}.issubset(audit_actions)


@pytest.mark.anyio
async def test_customer_routes_enforce_roles_and_tenant_scope(
    client: httpx.AsyncClient,
    client_actors: tuple[dict[str, tuple[UUID, UUID, str]], tuple[UUID, UUID]],
) -> None:
    actors, _organization_ids = client_actors
    admin_a_headers = {"Authorization": f"Bearer {actors['admin_a'][2]}"}
    admin_b_headers = {"Authorization": f"Bearer {actors['admin_b'][2]}"}
    analyst_headers = {"Authorization": f"Bearer {actors['analyst_a'][2]}"}
    client_headers = {"Authorization": f"Bearer {actors['client_a'][2]}"}

    created_a = await client.post(
        "/api/v1/clientes",
        headers=admin_a_headers,
        json={"razao_social": "Cliente A"},
    )
    created_b = await client.post(
        "/api/v1/clientes",
        headers=admin_b_headers,
        json={"razao_social": "Cliente B"},
    )
    assert created_a.status_code == 201
    assert created_b.status_code == 201
    cliente_a_id, cliente_b_id = created_a.json()["id"], created_b.json()["id"]

    own_list = await client.get("/api/v1/clientes", headers=admin_a_headers)
    assert [item["id"] for item in own_list.json()["items"]] == [cliente_a_id]
    assert (
        await client.get(f"/api/v1/clientes/{cliente_b_id}", headers=admin_a_headers)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/clientes/{cliente_b_id}",
            headers=admin_a_headers,
            json={"razao_social": "Tentativa de alteração cross-tenant"},
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/clientes/{cliente_b_id}", headers=admin_a_headers)
    ).status_code == 404

    analyst_create = await client.post(
        "/api/v1/clientes",
        headers=analyst_headers,
        json={"razao_social": "Cliente do analista"},
    )
    assert analyst_create.status_code == 201
    forbidden = await client.get("/api/v1/clientes", headers=client_headers)
    assert forbidden.status_code == 403
    assert (
        await client.get(f"/api/v1/clientes/{cliente_b_id}", headers=admin_b_headers)
    ).status_code == 200


@pytest.mark.anyio
async def test_customer_cnpj_is_unique_per_organization(
    client: httpx.AsyncClient,
    client_actors: tuple[dict[str, tuple[UUID, UUID, str]], tuple[UUID, UUID]],
) -> None:
    actors, _ = client_actors
    headers_a = {"Authorization": f"Bearer {actors['admin_a'][2]}"}
    headers_b = {"Authorization": f"Bearer {actors['admin_b'][2]}"}
    payload = {"razao_social": "Cliente CNPJ", "cnpj": "00000000000000"}

    assert (
        await client.post("/api/v1/clientes", headers=headers_a, json=payload)
    ).status_code == 201
    duplicate_same_org = await client.post("/api/v1/clientes", headers=headers_a, json=payload)
    same_cnpj_other_org = await client.post("/api/v1/clientes", headers=headers_b, json=payload)

    assert duplicate_same_org.status_code == 409
    assert same_cnpj_other_org.status_code == 201


@pytest.mark.anyio
async def test_customer_list_validates_pagination_bounds(
    client: httpx.AsyncClient,
    client_actors: tuple[dict[str, tuple[UUID, UUID, str]], tuple[UUID, UUID]],
) -> None:
    actors, _ = client_actors
    headers = {"Authorization": f"Bearer {actors['admin_a'][2]}"}

    too_many = await client.get("/api/v1/clientes?limit=201", headers=headers)
    invalid_cursor = await client.get("/api/v1/clientes?cursor=not-a-uuid", headers=headers)

    assert too_many.status_code == 422
    assert invalid_cursor.status_code == 422
