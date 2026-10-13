from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_health_endpoint_returns_ok_and_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Request-ID"])


@pytest.mark.anyio
async def test_ready_endpoint_reports_healthy_dependencies(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.main.check_dependencies",
        lambda _settings: {"database": True, "storage": True},
    )

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "ok", "storage": "ok"},
    }


@pytest.mark.anyio
async def test_ready_endpoint_returns_problem_when_dependency_is_unavailable(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.main.check_dependencies",
        lambda _settings: {"database": False, "storage": True},
    )

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["errors"] == [{"dependency": "database", "status": "unavailable"}]


@pytest.mark.anyio
async def test_http_errors_use_problem_details(client: httpx.AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
        "instance": "/missing",
        "errors": [],
    }


@pytest.mark.anyio
async def test_cors_allows_configured_frontend_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
