from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import AuthSession, Organizacao, Usuario
from app.main import app
from app.modules.auth.security import create_token, hash_password
from sqlalchemy import delete


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    host_id = uuid4().int & 0xFFFFFF
    host = f"10.{host_id >> 16}.{host_id >> 8 & 255}.{host_id & 255}"
    transport = httpx.ASGITransport(app=app, client=(host, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
def user_record() -> Iterator[tuple[UUID, str, str]]:
    user_id = uuid4()
    email = f"{user_id.hex}@example.com"
    password = "senha-de-teste-forte"
    with SessionLocal.begin() as session:
        organization = Organizacao(nome=f"Organizacao {user_id}")
        session.add(organization)
        session.flush()
        user = Usuario(
            id=user_id,
            organizacao_id=organization.id,
            email=email,
            nome="Analista Teste",
            senha_hash=hash_password(password),
        )
        session.add(user)
    yield user_id, email, password
    with SessionLocal.begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.usuario_id == user_id))
        session.execute(delete(Usuario).where(Usuario.id == user_id))
        session.execute(delete(Organizacao).where(Organizacao.id == user.organizacao_id))


@pytest.mark.anyio
async def test_login_and_me_return_authenticated_user(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    user_id, email, password = user_record

    response = await client.post("/api/v1/auth/login", json={"email": email, "senha": password})

    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == Settings().access_token_minutes * 60
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(user_id)
    assert me_response.json()["email"] == email
    assert "senha_hash" not in me_response.json()


@pytest.mark.anyio
async def test_wrong_password_is_rejected_without_exposing_account_state(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    _, email, _ = user_record

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "senha": "senha-incorreta"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciais inválidas."


@pytest.mark.anyio
async def test_inactive_user_cannot_log_in(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    user_id, email, password = user_record
    with SessionLocal.begin() as session:
        user = session.get(Usuario, user_id)
        assert user is not None
        user.ativo = False

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "senha": password},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciais inválidas."


@pytest.mark.anyio
async def test_expired_access_token_is_rejected(client: httpx.AsyncClient) -> None:
    settings = Settings()
    token = create_token(
        user_id=uuid4(),
        session_id=uuid4(),
        version=0,
        token_type="access",
        settings=settings,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_failed_logins_apply_progressively_longer_lockouts(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    user_id, email, _ = user_record
    settings = Settings()

    for _ in range(settings.auth_max_failed_attempts):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "senha": "senha-incorreta"},
        )
        assert response.status_code == 401

    with SessionLocal.begin() as session:
        user = session.get(Usuario, user_id)
        assert user is not None
        first_lockout = user.bloqueado_ate
        assert first_lockout is not None
        assert user.login_falhas_consecutivas == settings.auth_max_failed_attempts
        user.bloqueado_ate = datetime.now(UTC) - timedelta(seconds=1)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "senha": "senha-incorreta"},
    )
    assert response.status_code == 401

    with SessionLocal() as session:
        user = session.get(Usuario, user_id)
        assert user is not None
        assert user.bloqueado_ate is not None
        assert user.login_falhas_consecutivas == settings.auth_max_failed_attempts + 1
        assert (user.bloqueado_ate - datetime.now(UTC)).total_seconds() >= (
            settings.auth_lockout_base_seconds * 2 - 2
        )


@pytest.mark.anyio
async def test_refresh_rotates_token_and_rejects_reuse(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    _, email, password = user_record
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "senha": password},
    )
    original_tokens = login_response.json()

    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_tokens["refresh_token"]},
    )

    assert refresh_response.status_code == 200
    rotated_tokens = refresh_response.json()
    assert rotated_tokens["refresh_token"] != original_tokens["refresh_token"]
    assert (
        await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_tokens["refresh_token"]},
        )
    ).status_code == 401
    assert (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {rotated_tokens['access_token']}"},
        )
    ).status_code == 200


@pytest.mark.anyio
async def test_logout_revokes_access_token(
    client: httpx.AsyncClient, user_record: tuple[UUID, str, str]
) -> None:
    _, email, password = user_record
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "senha": password},
    )
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    logout_response = await client.post("/api/v1/auth/logout", headers=headers)

    assert logout_response.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


@pytest.mark.anyio
async def test_login_is_rate_limited_by_client_ip(client: httpx.AsyncClient) -> None:
    for _ in range(10):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.com", "senha": "senha-incorreta"},
        )
        assert response.status_code == 401

    limited_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "senha": "senha-incorreta"},
    )

    assert limited_response.status_code == 429
    assert limited_response.headers["content-type"].startswith("application/problem+json")
