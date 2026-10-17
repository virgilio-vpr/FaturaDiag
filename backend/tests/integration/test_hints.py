from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import (
    AuditLog,
    AuthSession,
    Distribuidora,
    HintDistribuidora,
    Organizacao,
    Usuario,
)
from app.main import app
from app.modules.auth.security import create_token
from app.modules.tarifas.hints import HintAmbiguoError, resolver_hint
from sqlalchemy import delete, select


@pytest.fixture
def hint_actors() -> Iterator[tuple[UUID, UUID, str, str]]:
    organization_id, admin_id, analyst_id = uuid4(), uuid4(), uuid4()
    session_ids = {"admin": uuid4(), "analyst": uuid4()}
    distributor_id = uuid4()
    with SessionLocal.begin() as session:
        session.add(Organizacao(id=organization_id, nome=f"Hints {organization_id}"))
        session.flush()
        session.add_all(
            [
                Usuario(
                    id=admin_id,
                    organizacao_id=organization_id,
                    email=f"{admin_id.hex}@example.com",
                    nome="Admin de hints",
                    senha_hash="unused",
                    papel="ADMIN",
                ),
                Usuario(
                    id=analyst_id,
                    organizacao_id=organization_id,
                    email=f"{analyst_id.hex}@example.com",
                    nome="Analista de hints",
                    senha_hash="unused",
                    papel="ANALISTA",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                AuthSession(
                    id=session_ids[role],
                    usuario_id=user_id,
                    expira_em=datetime.now(UTC) + timedelta(days=Settings().refresh_token_days),
                )
                for role, user_id in (("admin", admin_id), ("analyst", analyst_id))
            ]
        )
        session.add(
            Distribuidora(
                id=distributor_id,
                sigla=f"HINT_TEST_{distributor_id.hex[:8]}",
                nome="Distribuidora de teste de hints",
                ufs=["SP"],
            )
        )

    settings = Settings()
    admin_token = create_token(
        user_id=admin_id,
        session_id=session_ids["admin"],
        version=0,
        token_type="access",
        settings=settings,
    )
    analyst_token = create_token(
        user_id=analyst_id,
        session_id=session_ids["analyst"],
        version=0,
        token_type="access",
        settings=settings,
    )
    yield distributor_id, organization_id, admin_token, analyst_token

    with SessionLocal.begin() as session:
        session.execute(delete(AuditLog).where(AuditLog.organizacao_id == organization_id))
        session.execute(
            delete(HintDistribuidora).where(HintDistribuidora.distribuidora_id == distributor_id)
        )
        session.execute(delete(AuthSession).where(AuthSession.id.in_(list(session_ids.values()))))
        session.execute(delete(Usuario).where(Usuario.id.in_([admin_id, analyst_id])))
        session.execute(delete(Organizacao).where(Organizacao.id == organization_id))
        session.execute(delete(Distribuidora).where(Distribuidora.id == distributor_id))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_hint_versioning_resolution_update_and_admin_access(
    api_client: httpx.AsyncClient,
    hint_actors: tuple[UUID, UUID, str, str],
) -> None:
    distributor_id, organization_id, admin_token, analyst_token = hint_actors
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    first_version = await api_client.post(
        f"/api/v1/admin/hints/{distributor_id}/versionar",
        headers=admin_headers,
        json={
            "versao": "v1",
            "arquivo_md": "# Hint v1\nParticularidades antigas.",
            "vigencia_inicio": "2026-01-01",
        },
    )
    assert first_version.status_code == 201
    assert first_version.json()["ativo"] is True
    assert first_version.json()["vigencia_fim"] is None

    second_version = await api_client.post(
        f"/api/v1/admin/hints/{distributor_id}/versionar",
        headers=admin_headers,
        json={
            "versao": "v2",
            "arquivo_md": "# Hint v2\nParticularidades atuais.",
            "vigencia_inicio": "2026-07-01",
        },
    )
    assert second_version.status_code == 201
    assert second_version.json()["ativo"] is True
    assert second_version.json()["vigencia_fim"] is None

    future_version = await api_client.post(
        f"/api/v1/admin/hints/{distributor_id}/versionar",
        headers=admin_headers,
        json={
            "versao": "v3",
            "arquivo_md": "# Hint v3\nNovo layout futuro.",
            "vigencia_inicio": "2028-01-01",
        },
    )
    assert future_version.status_code == 201
    assert future_version.json()["ativo"] is False
    with SessionLocal() as session:
        first = session.scalar(
            select(HintDistribuidora).where(
                HintDistribuidora.distribuidora_id == distributor_id,
                HintDistribuidora.versao == "v1",
            )
        )
        distributor = session.get(Distribuidora, distributor_id)
        assert first is not None
        assert first.vigencia_fim == date(2026, 7, 1)
        assert first.ativo is False
        assert distributor is not None
        assert distributor.tem_hint is True
        current = session.scalar(
            select(HintDistribuidora).where(
                HintDistribuidora.distribuidora_id == distributor_id,
                HintDistribuidora.versao == "v2",
            )
        )
        assert current is not None
        assert current.ativo is True
        assert current.vigencia_fim == date(2028, 1, 1)

        assert (
            resolver_hint(
                session,
                distribuidora_id=distributor_id,
                data=date(2025, 12, 31),
            )
            is None
        )
        assert (
            resolver_hint(
                session,
                distribuidora_id=distributor_id,
                data=date(2026, 1, 1),
            ).versao
            == "v1"
        )
        assert (
            resolver_hint(
                session,
                distribuidora_id=distributor_id,
                data=date(2026, 6, 30),
            ).versao
            == "v1"
        )
        assert (
            resolver_hint(
                session,
                distribuidora_id=distributor_id,
                data=date(2026, 7, 1),
            ).versao
            == "v2"
        )
        assert (
            resolver_hint(
                session,
                distribuidora_id=distributor_id,
                data=date(2028, 1, 1),
            ).versao
            == "v3"
        )

    list_response = await api_client.get(
        "/api/v1/admin/hints",
        params={"distribuidora_id": str(distributor_id), "data": "2026-06-30"},
        headers=admin_headers,
    )
    assert list_response.status_code == 200
    assert [hint["versao"] for hint in list_response.json()["itens"]] == ["v1"]

    update_response = await api_client.put(
        "/api/v1/admin/hints",
        headers=admin_headers,
        json={
            "distribuidora_id": str(distributor_id),
            "versao": "v2",
            "arquivo_md": "# Hint v2\nConteúdo corrigido.",
        },
    )
    assert update_response.status_code == 200
    assert "Conteúdo corrigido" in update_response.json()["arquivo_md"]

    duplicate_version = await api_client.post(
        f"/api/v1/admin/hints/{distributor_id}/versionar",
        headers=admin_headers,
        json={
            "versao": "v2",
            "arquivo_md": "# Duplicado",
            "vigencia_inicio": "2027-01-01",
        },
    )
    assert duplicate_version.status_code == 409

    empty_hint = await api_client.post(
        f"/api/v1/admin/hints/{distributor_id}/versionar",
        headers=admin_headers,
        json={"versao": "v3", "arquivo_md": "  ", "vigencia_inicio": "2028-01-01"},
    )
    assert empty_hint.status_code == 422

    forbidden = await api_client.get("/api/v1/admin/hints", headers=analyst_headers)
    assert forbidden.status_code == 403

    with SessionLocal() as session:
        audit_actions = set(
            session.scalars(
                select(AuditLog.acao).where(
                    AuditLog.organizacao_id == organization_id,
                    AuditLog.entidade == "hint_distribuidora",
                )
            ).all()
        )
    assert {
        "HINT_DISTRIBUIDORA_VERSIONADO",
        "HINT_DISTRIBUIDORA_VIGENCIA_ENCERRADA",
        "HINT_DISTRIBUIDORA_ATUALIZADO",
    }.issubset(audit_actions)

    with SessionLocal.begin() as session:
        session.add(
            HintDistribuidora(
                distribuidora_id=distributor_id,
                versao="overlap",
                arquivo_md="# Hint sobreposto",
                vigencia_inicio=date(2026, 6, 1),
                vigencia_fim=date(2026, 8, 1),
            )
        )
    with SessionLocal() as session:
        with pytest.raises(HintAmbiguoError):
            resolver_hint(session, distribuidora_id=distributor_id, data=date(2026, 6, 15))
    ambiguous_list = await api_client.get(
        "/api/v1/admin/hints",
        params={"distribuidora_id": str(distributor_id), "data": "2026-06-15"},
        headers=admin_headers,
    )
    assert ambiguous_list.status_code == 409
