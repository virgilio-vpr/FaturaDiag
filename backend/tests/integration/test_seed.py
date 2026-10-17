from uuid import uuid4

import pytest
from app.db import SessionLocal
from app.db.models import Organizacao, Usuario
from app.modules.auth.security import verify_password
from app.scripts.seed import (
    DEMO_ORGANIZATION_NAME,
    SeedConfigurationError,
    SeedConflictError,
    seed_demo_admin,
)
from sqlalchemy import func, select


def test_seed_creates_demo_organization_and_admin() -> None:
    email = f"{uuid4().hex}@example.com"
    password = "senha-de-seed-de-teste"
    with SessionLocal() as session:
        result = seed_demo_admin(session, admin_email=email, admin_password=password)
        organization = session.get(Organizacao, result.organization_id)
        admin = session.get(Usuario, result.admin_id)

        assert organization is not None
        assert organization.nome == DEMO_ORGANIZATION_NAME
        assert admin is not None
        assert admin.organizacao_id == organization.id
        assert admin.email == email
        assert admin.papel == "ADMIN"
        assert admin.ativo is True
        assert verify_password(password, admin.senha_hash)
        session.rollback()


def test_seed_is_idempotent_for_the_same_admin_credentials() -> None:
    email = f"{uuid4().hex}@example.com"
    with SessionLocal() as session:
        first = seed_demo_admin(session, admin_email=email, admin_password="senha-seed")
        second = seed_demo_admin(session, admin_email=email, admin_password="senha-seed")
        user_count = session.scalar(
            select(func.count()).select_from(Usuario).where(func.lower(Usuario.email) == email)
        )

        assert first.organization_id == second.organization_id
        assert first.admin_id == second.admin_id
        assert second.organization_created is False
        assert second.admin_created is False
        assert user_count == 1
        session.rollback()


def test_seed_does_not_move_an_existing_admin_between_tenants() -> None:
    email = f"{uuid4().hex}@example.com"
    with SessionLocal() as session:
        organization = Organizacao(nome=f"Outra organização {uuid4()}")
        session.add(organization)
        session.flush()
        user = Usuario(
            organizacao_id=organization.id,
            email=email,
            nome="Usuario existente",
            senha_hash="hash-existente",
            papel="ADMIN",
        )
        session.add(user)
        session.flush()

        with pytest.raises(SeedConflictError):
            seed_demo_admin(session, admin_email=email, admin_password="senha-seed")

        assert user.organizacao_id == organization.id
        session.rollback()


def test_seed_requires_a_nonempty_password() -> None:
    with SessionLocal() as session, pytest.raises(SeedConfigurationError):
        seed_demo_admin(session, admin_email="admin@example.com", admin_password=" ")


def test_seed_does_not_create_duplicate_demo_organizations() -> None:
    email_a = f"{uuid4().hex}@example.com"
    email_b = f"{uuid4().hex}@example.com"
    with SessionLocal() as session:
        seed_demo_admin(session, admin_email=email_a, admin_password="senha-seed")
        seed_demo_admin(session, admin_email=email_b, admin_password="senha-seed")
        demo_org_count = session.scalar(
            select(func.count())
            .select_from(Organizacao)
            .where(Organizacao.nome == DEMO_ORGANIZATION_NAME)
        )

        assert demo_org_count == 1
        session.rollback()
