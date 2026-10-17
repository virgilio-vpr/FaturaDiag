from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import Organizacao, Usuario
from app.modules.auth.security import hash_password
from app.modules.tarifas.parametros import semear_parametros_regulatorios
from app.scripts.seed_catalogs import seed_reference_catalog

DEMO_ORGANIZATION_NAME = "FaturaDiag Demo"
logger = structlog.get_logger(__name__)


class SeedConfigurationError(ValueError):
    pass


class SeedConflictError(ValueError):
    pass


@dataclass(frozen=True)
class SeedResult:
    organization_id: UUID
    admin_id: UUID
    organization_created: bool
    admin_created: bool


def seed_demo_admin(session: Session, *, admin_email: str, admin_password: str) -> SeedResult:
    normalized_email = admin_email.strip().casefold()
    if not normalized_email:
        raise SeedConfigurationError("SEED_ADMIN_EMAIL não pode ser vazio.")
    if not admin_password.strip():
        raise SeedConfigurationError("SEED_ADMIN_PASSWORD deve ser definida para executar o seed.")

    organizations = list(
        session.scalars(select(Organizacao).where(Organizacao.nome == DEMO_ORGANIZATION_NAME)).all()
    )
    if len(organizations) > 1:
        raise SeedConflictError("Há mais de uma organização demo; o seed foi interrompido.")
    organization = organizations[0] if organizations else None

    admin = session.scalar(select(Usuario).where(func.lower(Usuario.email) == normalized_email))
    if admin is not None:
        if organization is None or admin.organizacao_id != organization.id:
            raise SeedConflictError(
                "O email configurado para o ADMIN já pertence a outra organização."
            )
        if admin.papel != "ADMIN" or not admin.ativo:
            raise SeedConflictError("O usuário existente não é um ADMIN ativo.")
        return SeedResult(
            organization_id=organization.id,
            admin_id=admin.id,
            organization_created=False,
            admin_created=False,
        )

    organization_created = organization is None
    if organization is None:
        organization = Organizacao(nome=DEMO_ORGANIZATION_NAME)
        session.add(organization)
        session.flush()

    admin = Usuario(
        organizacao_id=organization.id,
        email=normalized_email,
        nome="Administrador",
        senha_hash=hash_password(admin_password),
        papel="ADMIN",
        ativo=True,
    )
    session.add(admin)
    session.flush()

    return SeedResult(
        organization_id=organization.id,
        admin_id=admin.id,
        organization_created=organization_created,
        admin_created=True,
    )


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        with SessionLocal.begin() as session:
            result = seed_demo_admin(
                session,
                admin_email=settings.seed_admin_email,
                admin_password=settings.seed_admin_password.get_secret_value(),
            )
            catalog_result = seed_reference_catalog(session)
            parameters_created = semear_parametros_regulatorios(session)
    except (SeedConfigurationError, SeedConflictError) as error:
        logger.error("demo_seed_failed", reason=str(error))
        raise SystemExit(1) from error

    logger.info(
        "demo_seed_completed",
        organizacao_id=str(result.organization_id),
        organization_created=result.organization_created,
        admin_created=result.admin_created,
        distributors_created=catalog_result.distributors_created,
        holidays_created=catalog_result.holidays_created,
        regulatory_parameters_created=parameters_created,
    )


if __name__ == "__main__":
    main()
