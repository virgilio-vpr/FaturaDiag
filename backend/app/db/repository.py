from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql import Select

from app.db.base import Base


class TenantRequiredError(ValueError):
    pass


class TenantScopeError(PermissionError):
    pass


class BaseRepository[ModelT: Base]:
    def __init__(
        self,
        session: Session,
        model: type[ModelT],
        organizacao_id: UUID | None = None,
    ) -> None:
        if organizacao_id is None:
            raise TenantRequiredError("organizacao_id é obrigatório para acessar dados de negócio.")

        tenant_column = getattr(model, "organizacao_id", None)
        if tenant_column is None:
            raise TenantScopeError("O modelo não possui escopo de organização.")

        self.session = session
        self.model = model
        self.organizacao_id = organizacao_id
        self._tenant_column = cast(InstrumentedAttribute[UUID], tenant_column)

    def statement(self) -> Select[ModelT]:
        return select(self.model).where(self._tenant_column == self.organizacao_id)

    def get(self, entity_id: UUID) -> ModelT | None:
        statement = self.statement().where(self.model.id == entity_id)
        return self.session.scalars(statement).one_or_none()

    def list(self) -> list[ModelT]:
        return list(self.session.scalars(self.statement()).all())

    def add(self, entity: ModelT) -> ModelT:
        entity_organization_id = cast(UUID, getattr(entity, "organizacao_id", None))
        if entity_organization_id != self.organizacao_id:
            raise TenantScopeError("A entidade não pertence à organizacao_id do repositório.")
        self.session.add(entity)
        return entity
