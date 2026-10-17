from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.core.audit import AuditEventError, registrar_evento_auditoria
from app.db import SessionLocal
from app.db.models import AuditLog, Organizacao, Usuario
from sqlalchemy import delete


@pytest.fixture
def audit_tenants() -> Iterator[tuple[UUID, UUID, UUID, UUID]]:
    organization_a_id, organization_b_id = uuid4(), uuid4()
    user_a_id, user_b_id = uuid4(), uuid4()
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
                    nome="Audit actor A",
                    senha_hash="unused",
                    papel="ADMIN",
                ),
                Usuario(
                    id=user_b_id,
                    organizacao_id=organization_b_id,
                    email=f"{user_b_id.hex}@example.com",
                    nome="Audit actor B",
                    senha_hash="unused",
                    papel="ADMIN",
                ),
            ]
        )
    yield organization_a_id, user_a_id, organization_b_id, user_b_id
    with SessionLocal.begin() as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.organizacao_id.in_([organization_a_id, organization_b_id])
            )
        )
        session.execute(delete(Usuario).where(Usuario.id.in_([user_a_id, user_b_id])))
        session.execute(
            delete(Organizacao).where(Organizacao.id.in_([organization_a_id, organization_b_id]))
        )


def test_audit_event_persists_structured_changes_with_tenant_and_actor(
    audit_tenants: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a_id, user_a_id, _, _ = audit_tenants
    with SessionLocal.begin() as session:
        event = registrar_evento_auditoria(
            session,
            organizacao_id=organization_a_id,
            usuario_id=user_a_id,
            acao="CLIENTE_ATUALIZADO",
            entidade="cliente",
            entidade_id="cliente-123",
            antes={"nome": "Nome anterior"},
            depois={"nome": "Nome novo"},
            ip="192.0.2.10",
        )
        event_id = event.id

    with SessionLocal() as session:
        stored_event = session.get(AuditLog, event_id)

        assert stored_event is not None
        assert stored_event.organizacao_id == organization_a_id
        assert stored_event.usuario_id == user_a_id
        assert stored_event.acao == "CLIENTE_ATUALIZADO"
        assert stored_event.entidade == "cliente"
        assert stored_event.entidade_id == "cliente-123"
        assert stored_event.antes == {"nome": "Nome anterior"}
        assert stored_event.depois == {"nome": "Nome novo"}
        assert stored_event.ip == "192.0.2.10"
        assert stored_event.ts is not None


def test_audit_event_rejects_actor_from_another_organization(
    audit_tenants: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a_id, _, _, user_b_id = audit_tenants
    with SessionLocal.begin() as session, pytest.raises(AuditEventError):
        registrar_evento_auditoria(
            session,
            organizacao_id=organization_a_id,
            usuario_id=user_b_id,
            acao="CLIENTE_ATUALIZADO",
            entidade="cliente",
            entidade_id="cliente-123",
            depois={"nome": "Nome novo"},
        )


def test_audit_event_redacts_credentials_and_normalizes_json_values(
    audit_tenants: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a_id, user_a_id, _, _ = audit_tenants
    with SessionLocal.begin() as session:
        event = registrar_evento_auditoria(
            session,
            organizacao_id=organization_a_id,
            usuario_id=user_a_id,
            acao="USUARIO_ATUALIZADO",
            entidade="usuario",
            entidade_id=str(user_a_id),
            antes={"senha_hash": "hash antigo", "ativo": True},
            depois={
                "senha_hash": "hash novo",
                "new_password": "senha temporaria",
                "access_token": "token confidencial",
                "perfil": {"senha": "senha confidencial"},
                "valor": Decimal("12.3400"),
                "data": date(2026, 10, 16),
            },
        )
        event_id = event.id

    with SessionLocal() as session:
        stored_event = session.get(AuditLog, event_id)
        assert stored_event is not None
        assert stored_event.antes == {"senha_hash": "[REDACTED]", "ativo": True}
        assert stored_event.depois == {
            "senha_hash": "[REDACTED]",
            "new_password": "[REDACTED]",
            "access_token": "[REDACTED]",
            "perfil": {"senha": "[REDACTED]"},
            "valor": "12.3400",
            "data": "2026-10-16",
        }
        assert "hash novo" not in str(stored_event.depois)
        assert "senha temporaria" not in str(stored_event.depois)
        assert "token confidencial" not in str(stored_event.depois)


def test_system_audit_event_can_have_no_user(
    audit_tenants: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a_id, _, _, _ = audit_tenants
    with SessionLocal.begin() as session:
        event = registrar_evento_auditoria(
            session,
            organizacao_id=organization_a_id,
            usuario_id=None,
            acao="FERIADO_IMPORTADO",
            entidade="feriado_nacional",
            entidade_id="2026-01-01",
        )
        event_id = event.id

    with SessionLocal() as session:
        stored_event = session.get(AuditLog, event_id)
        assert stored_event is not None
        assert stored_event.usuario_id is None
        assert stored_event.antes is None
        assert stored_event.depois is None


def test_audit_event_uses_callers_transaction(
    audit_tenants: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a_id, user_a_id, _, _ = audit_tenants
    with SessionLocal() as session:
        event = registrar_evento_auditoria(
            session,
            organizacao_id=organization_a_id,
            usuario_id=user_a_id,
            acao="CLIENTE_CRIADO",
            entidade="cliente",
            entidade_id="cliente-rollback",
            depois={"nome": "Não persistir sem commit externo"},
        )
        event_id = event.id
        session.rollback()

    with SessionLocal() as session:
        assert session.get(AuditLog, event_id) is None
