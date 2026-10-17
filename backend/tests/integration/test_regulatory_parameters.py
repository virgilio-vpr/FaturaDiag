from collections.abc import AsyncIterator, Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import AuditLog, AuthSession, Organizacao, ParametroRegulatorio, Usuario
from app.main import app
from app.modules.auth.security import create_token
from app.modules.tarifas.parametros import (
    PARAMETROS_INICIAIS,
    SEED_VALID_FROM,
    ParametroRegulatorioNaoEncontrado,
    carregar_parametros_regulatorios,
    limpar_cache_parametros,
    semear_parametros_regulatorios,
)
from sqlalchemy import delete, select


def test_regulatory_parameter_seed_is_complete_idempotent_and_keeps_declared_statuses() -> None:
    with SessionLocal() as session:
        created = semear_parametros_regulatorios(session, vigencia_inicio=date(2099, 1, 1))
        records = session.scalars(
            select(ParametroRegulatorio).where(
                ParametroRegulatorio.vigencia_inicio == date(2099, 1, 1)
            )
        ).all()
        repeated_seed = semear_parametros_regulatorios(session, vigencia_inicio=date(2099, 1, 1))

        assert created == len(PARAMETROS_INICIAIS) == len(records)
        assert repeated_seed == 0
        assert {record.chave for record in records} == set(PARAMETROS_INICIAIS)
        assert all(
            record.status == ("VALIDADO" if record.chave == "subgrupos_prioritarios" else "VALIDAR")
            for record in records
        )
        session.rollback()


def test_loader_resolves_half_open_versions_as_immutable_domain_object() -> None:
    first_date = date(2098, 1, 1)
    next_date = date(2098, 7, 1)
    with SessionLocal() as session:
        semear_parametros_regulatorios(session, vigencia_inicio=first_date)
        tolerance = session.scalar(
            select(ParametroRegulatorio).where(
                ParametroRegulatorio.chave == "tolerancia_ultrapassagem",
                ParametroRegulatorio.vigencia_inicio == first_date,
            )
        )
        assert tolerance is not None
        tolerance.vigencia_fim = next_date
        session.add(
            ParametroRegulatorio(
                chave=tolerance.chave,
                valor=0.08,
                vigencia_inicio=next_date,
                status="VALIDADO",
                fonte="Fonte validada de teste",
            )
        )
        session.flush()

        before_boundary = carregar_parametros_regulatorios(
            session, data=date(2098, 6, 30), usar_cache=False
        )
        on_boundary = carregar_parametros_regulatorios(session, data=next_date, usar_cache=False)
        with pytest.raises(ParametroRegulatorioNaoEncontrado):
            carregar_parametros_regulatorios(session, data=date(2097, 12, 31), usar_cache=False)

        assert before_boundary.tolerancia_ultrapassagem == Decimal("0.05")
        assert on_boundary.tolerancia_ultrapassagem == Decimal("0.08")
        assert "tolerancia_ultrapassagem" in before_boundary.pendentes_validacao
        assert "tolerancia_ultrapassagem" not in on_boundary.pendentes_validacao
        assert before_boundary.modalidades_verde_elegiveis == ("A3a", "A4", "AS")
        assert before_boundary.janela_indutiva == "06:00-24:00"
        with pytest.raises(FrozenInstanceError):
            before_boundary.tolerancia_ultrapassagem = Decimal("0.10")  # type: ignore[misc]
        session.rollback()


@pytest.fixture
def regulatory_admin() -> Iterator[tuple[UUID, UUID, str, set[str], date | None]]:
    organization_id, user_id, session_id = uuid4(), uuid4(), uuid4()
    seed_date = SEED_VALID_FROM
    updated_start = date(2027, 1, 1)
    with SessionLocal.begin() as session:
        previous = session.scalar(
            select(ParametroRegulatorio).where(
                ParametroRegulatorio.chave == "tolerancia_ultrapassagem",
                ParametroRegulatorio.vigencia_inicio == seed_date,
            )
        )
        original_end = previous.vigencia_fim if previous is not None else None
        existing_seed_keys = set(
            session.scalars(
                select(ParametroRegulatorio.chave).where(
                    ParametroRegulatorio.vigencia_inicio == seed_date
                )
            ).all()
        )
        organization = Organizacao(id=organization_id, nome=f"Parâmetros {organization_id}")
        session.add(organization)
        session.flush()
        session.add(
            Usuario(
                id=user_id,
                organizacao_id=organization_id,
                email=f"{user_id.hex}@example.com",
                nome="Admin de teste",
                senha_hash="unused",
                papel="ADMIN",
            )
        )
        session.flush()
        session.add(
            AuthSession(
                id=session_id,
                usuario_id=user_id,
                expira_em=datetime.now(UTC) + timedelta(days=Settings().refresh_token_days),
            )
        )
        semear_parametros_regulatorios(session, vigencia_inicio=seed_date)

    token = create_token(
        user_id=user_id,
        session_id=session_id,
        version=0,
        token_type="access",
        settings=Settings(),
    )
    yield user_id, organization_id, token, existing_seed_keys, original_end

    with SessionLocal.begin() as session:
        session.execute(delete(AuditLog).where(AuditLog.organizacao_id == organization_id))
        session.execute(
            delete(ParametroRegulatorio).where(
                ParametroRegulatorio.chave == "tolerancia_ultrapassagem",
                ParametroRegulatorio.vigencia_inicio == updated_start,
            )
        )
        if "tolerancia_ultrapassagem" in existing_seed_keys:
            previous = session.scalar(
                select(ParametroRegulatorio).where(
                    ParametroRegulatorio.chave == "tolerancia_ultrapassagem",
                    ParametroRegulatorio.vigencia_inicio == seed_date,
                )
            )
            if previous is not None:
                previous.vigencia_fim = original_end
        created_seed_keys = set(PARAMETROS_INICIAIS) - existing_seed_keys
        if created_seed_keys:
            session.execute(
                delete(ParametroRegulatorio).where(
                    ParametroRegulatorio.vigencia_inicio == seed_date,
                    ParametroRegulatorio.chave.in_(created_seed_keys),
                )
            )
        session.execute(delete(AuthSession).where(AuthSession.id == session_id))
        session.execute(delete(Usuario).where(Usuario.id == user_id))
        session.execute(delete(Organizacao).where(Organizacao.id == organization_id))
    limpar_cache_parametros()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_admin_parameter_api_versions_values_and_invalidates_cache(
    api_client: httpx.AsyncClient,
    regulatory_admin: tuple[UUID, UUID, str, set[str], date | None],
) -> None:
    user_id, _organization_id, token, _existing_keys, _original_end = regulatory_admin
    headers = {"Authorization": f"Bearer {token}"}
    get_response = await api_client.get(
        "/api/v1/admin/parametros",
        params={"data": SEED_VALID_FROM.isoformat()},
        headers=headers,
    )

    assert get_response.status_code == 200
    body = get_response.json()
    assert len(body["itens"]) == len(PARAMETROS_INICIAIS)
    assert "tolerancia_ultrapassagem" in body["pendentes_validacao"]

    update_response = await api_client.put(
        "/api/v1/admin/parametros",
        headers=headers,
        json={
            "chave": "tolerancia_ultrapassagem",
            "valor": 0.06,
            "vigencia_inicio": "2027-01-01",
            "fonte": "Resolução validada em teste",
            "status": "VALIDADO",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["validado_por"] == str(user_id)
    assert update_response.json()["validado_em"] is not None
    invalid = await api_client.put(
        "/api/v1/admin/parametros",
        headers=headers,
        json={
            "chave": "chave_desconhecida",
            "valor": 1,
            "vigencia_inicio": "2028-01-01",
        },
    )
    assert invalid.status_code == 422

    next_version_response = await api_client.get(
        "/api/v1/admin/parametros",
        params={"data": "2027-01-01"},
        headers=headers,
    )
    assert next_version_response.status_code == 200
    assert "tolerancia_ultrapassagem" not in next_version_response.json()["pendentes_validacao"]
    with SessionLocal() as session:
        previous = session.scalar(
            select(ParametroRegulatorio).where(
                ParametroRegulatorio.chave == "tolerancia_ultrapassagem",
                ParametroRegulatorio.vigencia_inicio == SEED_VALID_FROM,
            )
        )
        assert previous is not None
        assert previous.vigencia_fim == date(2027, 1, 1)

    with SessionLocal.begin() as session:
        user = session.get(Usuario, user_id)
        assert user is not None
        user.papel = "ANALISTA"
    forbidden = await api_client.get("/api/v1/admin/parametros", headers=headers)
    assert forbidden.status_code == 403
