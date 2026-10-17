from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import AuthSession, Organizacao, Usuario
from app.db.repository import BaseRepository, TenantRequiredError, TenantScopeError
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.security import create_token
from app.modules.auth.service import AuthContext
from fastapi import Depends, FastAPI
from sqlalchemy import delete


@pytest.fixture
def tenant_records() -> Iterator[tuple[UUID, UUID, UUID, UUID]]:
    org_a_id, org_b_id = uuid4(), uuid4()
    user_a_id, user_b_id = uuid4(), uuid4()
    with SessionLocal.begin() as session:
        org_a = Organizacao(id=org_a_id, nome=f"Tenant A {org_a_id}")
        org_b = Organizacao(id=org_b_id, nome=f"Tenant B {org_b_id}")
        session.add_all([org_a, org_b])
        session.flush()
        session.add_all(
            [
                Usuario(
                    id=user_a_id,
                    organizacao_id=org_a_id,
                    email=f"{user_a_id.hex}@example.com",
                    nome="Usuario A",
                    senha_hash="unused",
                    papel="ANALISTA",
                ),
                Usuario(
                    id=user_b_id,
                    organizacao_id=org_b_id,
                    email=f"{user_b_id.hex}@example.com",
                    nome="Usuario B",
                    senha_hash="unused",
                    papel="ANALISTA",
                ),
            ]
        )
    yield org_a_id, user_a_id, org_b_id, user_b_id
    with SessionLocal.begin() as session:
        session.execute(delete(Usuario).where(Usuario.id.in_([user_a_id, user_b_id])))
        session.execute(delete(Organizacao).where(Organizacao.id.in_([org_a_id, org_b_id])))


@pytest.fixture
def authenticated_user() -> Iterator[tuple[UUID, UUID, str]]:
    organization_id, user_id = uuid4(), uuid4()
    settings = Settings()
    with SessionLocal.begin() as session:
        organization = Organizacao(id=organization_id, nome=f"Organizacao {organization_id}")
        session.add(organization)
        session.flush()
        user = Usuario(
            id=user_id,
            organizacao_id=organization_id,
            email=f"{user_id.hex}@example.com",
            nome="Usuario de autorizacao",
            senha_hash="unused",
            papel="ANALISTA",
        )
        session.add(user)
        session.flush()
        auth_session = AuthSession(
            usuario_id=user_id,
            expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
        session.add(auth_session)
        session.flush()
        token = create_token(
            user_id=user_id,
            session_id=auth_session.id,
            version=auth_session.versao_token,
            token_type="access",
            settings=settings,
        )
    yield user_id, organization_id, token
    with SessionLocal.begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.usuario_id == user_id))
        session.execute(delete(Usuario).where(Usuario.id == user_id))
        session.execute(delete(Organizacao).where(Organizacao.id == organization_id))


def test_repository_requires_an_organization_id() -> None:
    with SessionLocal() as session, pytest.raises(TenantRequiredError):
        BaseRepository(session, Usuario)


def test_repository_rejects_models_without_tenant_scope() -> None:
    with SessionLocal() as session, pytest.raises(TenantScopeError):
        BaseRepository(session, Organizacao, uuid4())


def test_repository_reads_only_records_from_its_organization(
    tenant_records: tuple[UUID, UUID, UUID, UUID],
) -> None:
    org_a_id, user_a_id, _org_b_id, user_b_id = tenant_records
    with SessionLocal() as session:
        repository = BaseRepository(session, Usuario, org_a_id)

        assert repository.get(user_a_id) is not None
        assert repository.get(user_b_id) is None
        assert [user.id for user in repository.list()] == [user_a_id]


def test_repository_rejects_adding_an_entity_from_another_organization(
    tenant_records: tuple[UUID, UUID, UUID, UUID],
) -> None:
    org_a_id, _user_a_id, org_b_id, _user_b_id = tenant_records
    entity = Usuario(
        organizacao_id=org_b_id,
        email=f"{uuid4().hex}@example.com",
        nome="Usuario fora do escopo",
        senha_hash="unused",
        papel="ANALISTA",
    )
    with SessionLocal() as session:
        repository = BaseRepository(session, Usuario, org_a_id)
        with pytest.raises(TenantScopeError):
            repository.add(entity)
        assert entity not in session


@pytest.mark.parametrize(
    ("user_role", "required_role", "expected_status"),
    [
        (Papel.ADMIN, Papel.ADMIN, 200),
        (Papel.ANALISTA, Papel.ANALISTA, 200),
        (Papel.CLIENTE, Papel.CLIENTE, 200),
        (Papel.PARCEIRO, Papel.PARCEIRO, 200),
        (Papel.ANALISTA, Papel.ADMIN, 403),
    ],
)
@pytest.mark.anyio
async def test_role_dependency_allows_only_configured_roles(
    authenticated_user: tuple[UUID, UUID, str],
    user_role: Papel,
    required_role: Papel,
    expected_status: int,
) -> None:
    user_id, _organization_id, access_token = authenticated_user
    with SessionLocal.begin() as session:
        user = session.get(Usuario, user_id)
        assert user is not None
        user.papel = user_role.value

    test_app = FastAPI()

    @test_app.get("/protected")
    def protected(
        auth: Annotated[AuthContext, Depends(requer_papel(required_role))],
    ) -> dict[str, str]:
        return {"papel": auth.user.papel}

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/protected",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == {"papel": user_role.value}


def test_role_dependency_requires_at_least_one_known_role() -> None:
    with pytest.raises(ValueError):
        requer_papel()
    with pytest.raises(ValueError):
        requer_papel("SUPERUSER")
