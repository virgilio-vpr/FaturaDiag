from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import AuthSession, Organizacao, Usuario
from app.main import app
from app.modules.auth.security import create_token
from sqlalchemy import delete


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
def tenant_principals() -> Iterator[tuple[UUID, UUID, UUID, UUID, str, str, UUID]]:
    organization_a_id, organization_b_id = uuid4(), uuid4()
    user_a_id, user_b_id = uuid4(), uuid4()
    session_a_id, session_b_id = uuid4(), uuid4()
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
                    id=user_a_id,
                    organizacao_id=organization_a_id,
                    email=f"{user_a_id.hex}@example.com",
                    nome="Usuario da organizacao A",
                    senha_hash="unused",
                    papel="ANALISTA",
                ),
                Usuario(
                    id=user_b_id,
                    organizacao_id=organization_b_id,
                    email=f"{user_b_id.hex}@example.com",
                    nome="Usuario da organizacao B",
                    senha_hash="unused",
                    papel="ANALISTA",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                AuthSession(
                    id=session_a_id,
                    usuario_id=user_a_id,
                    expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
                ),
                AuthSession(
                    id=session_b_id,
                    usuario_id=user_b_id,
                    expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
                ),
            ]
        )

    access_token_a = create_token(
        user_id=user_a_id,
        session_id=session_a_id,
        version=0,
        token_type="access",
        settings=settings,
    )
    access_token_b = create_token(
        user_id=user_b_id,
        session_id=session_b_id,
        version=0,
        token_type="access",
        settings=settings,
    )
    yield (
        organization_a_id,
        organization_b_id,
        user_a_id,
        user_b_id,
        access_token_a,
        access_token_b,
        session_a_id,
    )

    with SessionLocal.begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.id.in_([session_a_id, session_b_id])))
        session.execute(delete(Usuario).where(Usuario.id.in_([user_a_id, user_b_id])))
        session.execute(
            delete(Organizacao).where(Organizacao.id.in_([organization_a_id, organization_b_id]))
        )


@pytest.mark.parametrize("tenant_route", ["me", "logout"])
@pytest.mark.anyio
async def test_organization_a_cannot_read_or_revoke_organization_b_session(
    client: httpx.AsyncClient,
    tenant_principals: tuple[UUID, UUID, UUID, UUID, str, str, UUID],
    tenant_route: str,
) -> None:
    organization_a_id, organization_b_id, user_a_id, user_b_id, token_a, token_b, _ = (
        tenant_principals
    )
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    if tenant_route == "me":
        response = await client.get(
            f"/api/v1/auth/me?usuario_id={user_b_id}&organizacao_id={organization_b_id}",
            headers=headers_a,
        )

        assert response.status_code == 200
        assert response.json()["id"] == str(user_a_id)
        assert response.json()["organizacao_id"] == str(organization_a_id)
        assert str(user_b_id) not in response.text
        assert str(organization_b_id) not in response.text
        return

    logout_response = await client.post("/api/v1/auth/logout", headers=headers_a)

    assert logout_response.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers_a)).status_code == 401
    other_tenant_response = await client.get("/api/v1/auth/me", headers=headers_b)
    assert other_tenant_response.status_code == 200
    assert other_tenant_response.json()["id"] == str(user_b_id)
    assert other_tenant_response.json()["organizacao_id"] == str(organization_b_id)


@pytest.mark.anyio
async def test_user_a_cannot_pair_user_b_identity_with_user_a_session(
    client: httpx.AsyncClient,
    tenant_principals: tuple[UUID, UUID, UUID, UUID, str, str, UUID],
) -> None:
    _organization_a_id, _organization_b_id, _user_a_id, user_b_id, _, _, session_a_id = (
        tenant_principals
    )
    forged_identity_token = create_token(
        user_id=user_b_id,
        session_id=session_a_id,
        version=0,
        token_type="access",
        settings=Settings(),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {forged_identity_token}"},
    )

    assert response.status_code == 401
